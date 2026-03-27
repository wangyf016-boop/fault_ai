"""
故障排查优先级评分模块

基于四个维度对检索到的故障记录进行优先级排序：
1. 频率 (frequency)   — 同一原因出现次数越多，优先排查
2. 相似度 (similarity) — 向量检索分数越高，优先排查
3. 近期度 (recency)    — 距今越近，优先排查
4. 效率 (efficiency)   — 停机时间越短（排查更快），优先排查

权重暂时固定，后续可通过配置文件或前端调节。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# 权重配置（固定）
# ---------------------------------------------------------------------------
WEIGHTS: Dict[str, float] = {
    "frequency":  0.35,
    "similarity": 0.30,
    "recency":    0.20,
    "efficiency": 0.15,
}


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------
@dataclass
class ScoredRecord:
    """打分后的故障记录"""

    record: Dict                         # 原始 Qdrant/Neo4j 记录
    frequency_score: float = 0.0         # 归一化频率分
    similarity_score: float = 0.0        # 归一化相似度分
    recency_score: float = 0.0           # 归一化近期度分
    efficiency_score: float = 0.0        # 归一化效率分
    total_score: float = 0.0             # 加权总分
    occurrence_count: int = 0            # 同一原因出现次数
    rank: int = 0                        # 最终排名（1-based）


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------
def _parse_date(date_str: str) -> Optional[datetime]:
    """尝试将各种日期格式解析为 datetime"""
    if not date_str or not isinstance(date_str, str):
        return None
    date_str = date_str.strip()[:10]
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    return None


def _parse_downtime(val) -> float:
    """解析停机时间（分钟），容错处理"""
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    try:
        # 去除非数字字符后取第一段
        cleaned = re.sub(r"[^\d.]", " ", str(val)).strip()
        if cleaned:
            return float(cleaned.split()[0])
    except (ValueError, IndexError):
        pass
    return 0.0


def _normalize_cause(text: str) -> str:
    """将原因文本归一化以便统计频次"""
    if not text:
        return ""
    s = str(text).lower()
    s = re.sub(r"[^\w\u4e00-\u9fff]+", "", s)
    return s[:120]


# ---------------------------------------------------------------------------
# 核心算法
# ---------------------------------------------------------------------------
def compute_priority(
    records: List[Dict],
    weights: Optional[Dict[str, float]] = None,
    today: Optional[datetime] = None,
) -> List[ScoredRecord]:
    """
    对故障记录进行四维度优先级排序。

    Parameters
    ----------
    records : list[dict]
        Qdrant / Neo4j 返回的故障记录列表，每条至少包含：
        - cause / cause_analysis  : 原因
        - score                    : 向量相似度（0-1）
        - date                     : 日期字符串
        - downtime / 总停机时间     : 停机分钟数（可选）
    weights : dict, optional
        四维度权重，默认使用模块常量 WEIGHTS
    today : datetime, optional
        "今天" 的日期，默认 datetime.now()

    Returns
    -------
    list[ScoredRecord]
        按 total_score 降序排列的打分记录
    """
    if not records:
        return []

    w = weights or WEIGHTS
    now = today or datetime.now()

    # ---- 1. 统计每个原因的出现频次 ----
    cause_count: Dict[str, int] = {}
    for r in records:
        cause_key = _normalize_cause(
            r.get("cause") or r.get("cause_analysis") or ""
        )
        cause_count[cause_key] = cause_count.get(cause_key, 0) + 1

    # ---- 2. 预处理各维度原始值 ----
    raw_freq: List[int] = []
    raw_sim: List[float] = []
    raw_days: List[float] = []
    raw_downtime: List[float] = []

    for r in records:
        cause_key = _normalize_cause(
            r.get("cause") or r.get("cause_analysis") or ""
        )
        raw_freq.append(cause_count.get(cause_key, 1))
        raw_sim.append(float(r.get("score") or 0))

        d = _parse_date(str(r.get("date", "")))
        raw_days.append((now - d).days if d else 365)

        dt = _parse_downtime(
            r.get("downtime")
            or r.get("总停机时间 (Minutes)")
            or r.get("downtime_minutes")
            or 0
        )
        raw_downtime.append(dt)

    # ---- 3. 归一化（Min-Max → [0, 1]） ----
    max_freq = max(raw_freq) if raw_freq else 1
    max_sim = max(raw_sim) if raw_sim else 1.0
    max_days = max(raw_days) if raw_days else 1
    max_dt = max(raw_downtime) if raw_downtime else 1.0

    # 防止除零
    max_freq = max_freq or 1
    max_sim = max_sim or 1.0
    max_days = max_days or 1
    max_dt = max_dt or 1.0

    # ---- 4. 逐条打分 ----
    scored: List[ScoredRecord] = []
    for i, r in enumerate(records):
        freq_s = raw_freq[i] / max_freq
        sim_s = raw_sim[i] / max_sim
        recency_s = 1.0 - (raw_days[i] / max_days)         # 越近分越高
        eff_s = 1.0 - (raw_downtime[i] / max_dt)            # 停机越短分越高

        total = (
            w["frequency"]  * freq_s
            + w["similarity"] * sim_s
            + w["recency"]    * recency_s
            + w["efficiency"] * eff_s
        )

        scored.append(ScoredRecord(
            record=r,
            frequency_score=round(freq_s, 4),
            similarity_score=round(sim_s, 4),
            recency_score=round(recency_s, 4),
            efficiency_score=round(eff_s, 4),
            total_score=round(total, 4),
            occurrence_count=raw_freq[i],
        ))

    # ---- 5. 排序并赋予排名 ----
    scored.sort(key=lambda x: x.total_score, reverse=True)
    for idx, s in enumerate(scored, 1):
        s.rank = idx

    return scored


# ---------------------------------------------------------------------------
# 辅助：序列化为前端 JSON
# ---------------------------------------------------------------------------
def scored_to_dicts(scored_records: List[ScoredRecord]) -> List[Dict]:
    """将 ScoredRecord 列表转为可 JSON 序列化的字典列表"""
    result = []
    for s in scored_records:
        item = dict(s.record)                       # 浅拷贝原始记录
        item["priority_rank"] = s.rank
        item["priority_total"] = s.total_score
        item["priority_frequency"] = s.frequency_score
        item["priority_similarity"] = s.similarity_score
        item["priority_recency"] = s.recency_score
        item["priority_efficiency"] = s.efficiency_score
        item["occurrence_count"] = s.occurrence_count
        result.append(item)
    return result
