"""Qdrant 搜索共享工具

从 server.py 抽取的与 Qdrant 相关的通用函数，供 server.py 和 neo4j_tool.py 共用，
消除两者之间的循环依赖。
"""
from __future__ import annotations

import os
import re
import time as _time
from pathlib import Path as _Path

from qdrant_client import QdrantClient as _QdrantClient

from app.retrievers.qdrant_store import QdrantVectorStore

# =====================================================================
#  Qdrant 连接 & Collection 缓存
# =====================================================================

_shared_qdrant_client: _QdrantClient | None = None
_qdrant_col_cache: list | None = None
_qdrant_col_cache_time: float = 0
_QDRANT_COL_CACHE_TTL = 30.0
_qdrant_store_cache: dict = {}


def _get_shared_qdrant_client() -> _QdrantClient:
    global _shared_qdrant_client
    if _shared_qdrant_client is None:
        host = os.getenv("QDRANT_HOST", "localhost")
        port = int(os.getenv("QDRANT_PORT", "6333"))
        _shared_qdrant_client = _QdrantClient(host=host, port=port)
    return _shared_qdrant_client


def invalidate_qdrant_cache():
    """上传/删除 collection 后调用，立即刷新缓存"""
    global _qdrant_col_cache, _qdrant_col_cache_time, _qdrant_store_cache
    _qdrant_col_cache = None
    _qdrant_col_cache_time = 0
    _qdrant_store_cache.clear()


def get_all_qdrant_collections() -> list[str]:
    """获取 Qdrant 中所有可用的 collections（带 30s 缓存）"""
    global _qdrant_col_cache, _qdrant_col_cache_time
    now = _time.time()
    if _qdrant_col_cache is not None and (now - _qdrant_col_cache_time) < _QDRANT_COL_CACHE_TTL:
        return _qdrant_col_cache
    try:
        client = _get_shared_qdrant_client()
        collections = client.get_collections().collections
        _qdrant_col_cache = [c.name for c in collections]
        _qdrant_col_cache_time = now
        return _qdrant_col_cache
    except Exception as e:
        print(f"[Qdrant] 获取 collections 失败: {e}")
        return _qdrant_col_cache or []


# ── 注册表缓存 ────────────────────────────────────────
_registry_cache: dict | None = None
_registry_cache_time: float = 0
_REGISTRY_CACHE_TTL = 5.0


def _load_registry_cached() -> list:
    """读取 collection_registry.json（带 5s 内存缓存）"""
    global _registry_cache, _registry_cache_time
    import json as _json
    now = _time.time()
    if _registry_cache is not None and (now - _registry_cache_time) < _REGISTRY_CACHE_TTL:
        return _registry_cache.get("active", [])
    registry_file = _Path(__file__).resolve().parent.parent.parent / "collection_registry.json"
    if registry_file.exists():
        try:
            _registry_cache = _json.loads(registry_file.read_text(encoding="utf-8"))
            _registry_cache_time = now
            return _registry_cache.get("active", [])
        except Exception:
            pass
    _registry_cache = {}
    _registry_cache_time = now
    return []


def get_target_qdrant_collections() -> list[str]:
    """获取本次检索要使用的 collections（带缓存）。

    优先顺序：
    1) collection_registry.json（前端动态管理）
    2) QDRANT_COLLECTIONS (逗号分隔)
    3) QDRANT_COLLECTION (单个)
    4) 全部 collections
    """
    existing = set(get_all_qdrant_collections())

    # 1) 注册表
    active = _load_registry_cached()
    if active:
        result = [c for c in active if c in existing]
        if result:
            return result

    # 2) 环境变量
    env_multi = os.getenv("QDRANT_COLLECTIONS", "").strip()
    env_single = os.getenv("QDRANT_COLLECTION", "").strip()

    if env_multi:
        candidates = [c.strip() for c in env_multi.split(",") if c.strip()]
    elif env_single:
        candidates = [env_single]
    else:
        return list(existing)

    return [c for c in candidates if c in existing] or candidates


def _get_qdrant_store(collection_name: str) -> QdrantVectorStore:
    """复用 QdrantVectorStore 实例，避免重复建连接"""
    if collection_name not in _qdrant_store_cache:
        _qdrant_store_cache[collection_name] = QdrantVectorStore(collection_name=collection_name)
    return _qdrant_store_cache[collection_name]


# =====================================================================
#  Station 相关工具
# =====================================================================

def _extract_station_from_query(query: str) -> str:
    """从用户问题中提取工位编号，如 AM22-B1、PM15-B2、EM21-A3 等"""
    m = re.search(r'[A-Z]{2,3}\d{1,3}-[A-Z]\d+', query)
    return m.group(0) if m else ''


def _get_station_boost_value(default: float = 0.08) -> float:
    try:
        return float(os.getenv('QDRANT_STATION_BOOST', str(default)))
    except Exception:
        return default


def _get_problem_boost_value(default: float = 0.05) -> float:
    """问题字段加权，默认低于 station boost。"""
    try:
        configured = float(os.getenv('QDRANT_PROBLEM_BOOST', str(default)))
        # 保护：问题权重不得高于工位权重
        return min(configured, _get_station_boost_value())
    except Exception:
        return default


def _get_station_candidate_limit(query: str, top_k: int) -> int:
    """带工位查询时扩大候选池，避免在 boost 前就被截断。"""
    station = _extract_station_from_query(query)
    if not station:
        return top_k
    try:
        configured = int(os.getenv('QDRANT_STATION_CANDIDATE_LIMIT', '50'))
    except Exception:
        configured = 50
    return max(top_k, configured)


def _apply_station_boost(docs: list, station: str, boost: float | None = None) -> list:
    """对精确匹配工位的记录加分后重排，提升用户指定工位的排序优先级"""
    if not station:
        return docs
    boost = _get_station_boost_value() if boost is None else boost
    station_upper = station.upper()
    boosted = 0
    for doc in docs:
        if str(doc.get('station', '')).upper() == station_upper:
            doc['score'] = min(1.0, (doc.get('score') or 0) + boost)
            boosted += 1
    if boosted:
        docs.sort(key=lambda x: x.get('score', 0), reverse=True)
        print(f"[Qdrant] Station boost: '{station}' +{boost} 应用于 {boosted} 条记录")
    return docs


_PROBLEM_BOOST_KWS = [
    '报警', '故障', '异常', '无信号', '报错', '停机', '卡滞', '失败', '不良',
    '过电流', '高温', '温度', '漏油', '漏气', '漏水', '松动', '断裂', '磨损',
    '卡死', '抖动', '噪音', '振动', '发热', '短路', '断路', '超时',
]


def _extract_problem_terms_from_query(query: str) -> list[str]:
    """从用户查询中提取可用于匹配 payload.problem 的关键词。"""
    if not query:
        return []

    terms: list[str] = []
    q = str(query)

    # 先抓明显故障关键词
    for kw in _PROBLEM_BOOST_KWS:
        if kw in q and kw not in terms:
            terms.append(kw)

    # 再抓部件关键词（问题列常包含部件+现象）
    for kw in _COMPONENT_KEYWORDS:
        if kw in q and kw not in terms:
            terms.append(kw)

    # 最后抽取连续文本块（中英数字，长度>=2）
    chunks = re.findall(r'[\u4e00-\u9fffA-Za-z0-9\.]{2,}', q)
    stopwords = {
        '怎么', '如何', '处理', '解决', '原因', '措施', '排查', '是什么', '为什么',
        '这个', '那个', '今天', '昨天', '记录', '历史', '问题', '故障',
    }
    station = _extract_station_from_query(q).upper()
    for c in chunks:
        cc = c.strip()
        if not cc or cc in stopwords:
            continue
        if station and cc.upper() == station:
            continue
        if cc not in terms:
            terms.append(cc)

    # 限制数量，避免误匹配过多
    return terms[:8]


def _apply_problem_boost(docs: list, query: str, boost: float | None = None) -> list:
    """按 query 与 payload.problem 的命中关系加分，提升“问题列”相关结果。"""
    if not docs or not query:
        return docs

    terms = _extract_problem_terms_from_query(query)
    if not terms:
        return docs

    boost = _get_problem_boost_value() if boost is None else boost
    # 双保险：永不高于 station boost
    boost = min(boost, _get_station_boost_value())

    boosted = 0
    for doc in docs:
        problem_text = str(doc.get('problem') or doc.get('problem_description') or '').strip().lower()
        if not problem_text:
            continue
        hit_count = sum(1 for t in terms if t.lower() in problem_text)
        if hit_count <= 0:
            continue
        # 命中越多加分越高，但上限仍为 problem boost
        ratio = min(1.0, hit_count / max(1, min(len(terms), 3)))
        add_score = boost * ratio
        doc['score'] = min(1.0, (doc.get('score') or 0) + add_score)
        boosted += 1

    if boosted:
        docs.sort(key=lambda x: x.get('score', 0), reverse=True)
        print(f"[Qdrant] Problem boost: +<= {boost}，命中词={terms[:4]}，应用于 {boosted} 条记录")
    return docs


def _problem_group_key(doc: dict) -> str:
    """提取并归一化问题字段，作为聚类键。"""
    txt = str(doc.get('problem') or doc.get('problem_description') or '').strip().lower()
    if not txt:
        return ''
    # 去掉空白和常见分隔符，提升“同问题”归并稳定性
    txt = re.sub(r'[\s\|,，。;；:：\-_/]+', '', txt)
    return txt


def _group_docs_by_problem(docs: list) -> list:
    """将相同 problem 的记录放在一起，并优先展示重复问题组。"""
    if not docs:
        return docs

    groups: dict[str, list] = {}
    for idx, doc in enumerate(docs):
        key = _problem_group_key(doc)
        # 空 problem 不强行归组，避免无问题文本的大组污染排序
        gk = key if key else f"__ungrouped__{idx}"
        if gk not in groups:
            groups[gk] = []
        groups[gk].append(doc)

    grouped_items = []
    for gk, items in groups.items():
        # 组内先按分数降序
        items.sort(key=lambda x: x.get('score', 0) or 0, reverse=True)
        grouped_items.append((gk, items))

    # 组间排序：
    # 1) 重复问题组优先（size>=2）
    # 2) 组内最高分更高优先
    # 3) 组更大优先
    grouped_items.sort(
        key=lambda kv: (
            1 if len(kv[1]) >= 2 else 0,
            kv[1][0].get('score', 0) or 0,
            len(kv[1]),
        ),
        reverse=True,
    )

    merged = []
    for _, items in grouped_items:
        merged.extend(items)

    multi_groups = sum(1 for _, items in grouped_items if len(items) >= 2)
    if multi_groups:
        print(f"[Qdrant] Problem grouping: {len(grouped_items)} 组，其中重复问题组 {multi_groups} 组")
    return merged


# =====================================================================
#  结构化字段提取 + Qdrant Filter 构建
# =====================================================================

# 常见设备 / 部件关键词 — 用于从用户查询中提取 component 信息
_COMPONENT_KEYWORDS: list[str] = [
    # 刀具 / 刀库
    "刀库门", "刀库", "刀夹", "刀具", "换刀", "刀套", "刀臂", "刀盘",
    # 主轴
    "主轴", "电主轴",
    # 轴 / 丝杠
    "X轴", "Y轴", "Z轴", "A轴", "B轴", "C轴", "W轴", "丝杠", "导轨", "线轨",
    # 液压 / 气动
    "液压", "气缸", "气动", "油压", "调压阀", "电磁阀", "油缸",
    # 冷却 / 润滑
    "冷却", "切削液", "润滑", "油冷",
    # 夹具 / 工装
    "夹具", "卡盘", "夹爪", "顶针", "尾座",
    # 电气
    "伺服", "电机", "编码器", "传感器", "变频器", "PLC", "IO模块",
    # 机械手 / 上下料
    "机械手", "料仓", "料盘", "上下料", "桁架", "坦克链", "拖链",
    # 转盘 / 工作台
    "转盘", "工作台", "回转台", "托盘",
    # 振动盘 / 输送
    "振动盘", "输送", "皮带",
    # 防护门 / 安全
    "防护门", "安全门", "门锁",
]

# 按长度降序排列，优先匹配较长关键词（如 "刀库门" 优先于 "刀库"）
_COMPONENT_KEYWORDS.sort(key=len, reverse=True)


# 产线 / 区域关键词映射 — 将用户自然语言映射到 Qdrant payload.line 值
_LINE_ALIASES: dict[str, list[str]] = {
    "EPB": ["EPB", "epb"],
    "FND": ["FND", "fnd"],
    "MGU": ["MGU", "mgu"],
}

# OP 工位模式（2024 / 2023 集合: OP10, OP30, OP70, OP100.2 等）
_OP_STATION_RE = re.compile(r'OP\d+(?:\.\d+)?', re.IGNORECASE)


def _extract_structured_fields(query: str) -> dict:
    """从用户查询中提取所有可用的结构化字段。

    返回 dict，键为 payload 字段名，值为提取到的内容：
        station  — 工位编号（精确匹配）
        line     — 产线（精确匹配）
        components — 部件关键词列表（包含匹配，可能多个）
    未提取到的字段不会包含在返回结果中。
    """
    fields: dict = {}
    q_upper = query.upper()

    # 1) station — Machining 格式（AM22-B1）和 OP 格式（OP70）
    station = _extract_station_from_query(query)
    if not station:
        m_op = _OP_STATION_RE.search(query)
        if m_op:
            station = m_op.group(0).upper()
    if station:
        fields["station"] = station

    # 2) line — 从查询中匹配已知产线关键词
    for line_val, aliases in _LINE_ALIASES.items():
        for alias in aliases:
            if alias in query:
                fields["line"] = line_val
                break
        if "line" in fields:
            break
    # 也检测 "C11", "A40", "TMC21" 等形式
    if "line" not in fields:
        m_line = re.search(r'\b([A-Z]{1,4}\d{1,3})\b', q_upper)
        if m_line:
            candidate = m_line.group(1)
            station_val = fields.get("station", "")
            is_station_prefix = station_val and station_val.startswith(candidate)
            if candidate != station_val and not is_station_prefix:
                fields["line"] = candidate

    # 3) component — 包含匹配，取所有命中的关键词
    components = []
    for kw in _COMPONENT_KEYWORDS:
        if kw in query:
            components.append(kw)
    if components:
        fields["components"] = components

    return fields


def _build_qdrant_filter(fields: dict):
    """根据提取到的结构化字段构建 Qdrant Filter 对象。

    策略：
    - station: 精确匹配 (MatchValue)
    - line:    精确匹配 (MatchValue)
    - components: 任一关键词出现在 problem 字段中 (MatchText，should 逻辑)

    返回 qdrant_client.models.Filter 或 None。
    """
    from qdrant_client.models import Filter, FieldCondition, MatchValue, MatchText

    must_conditions = []

    if "station" in fields:
        must_conditions.append(
            FieldCondition(key="station", match=MatchValue(value=fields["station"]))
        )

    if "line" in fields:
        must_conditions.append(
            FieldCondition(key="line", match=MatchValue(value=fields["line"]))
        )

    # component 采用 should 逻辑（任一匹配即可），嵌套在 must 外层
    should_conditions = []
    for comp in fields.get("components", []):
        should_conditions.append(
            FieldCondition(key="problem", match=MatchText(text=comp))
        )

    if not must_conditions and not should_conditions:
        return None

    if must_conditions and should_conditions:
        return Filter(
            must=must_conditions,
            should=should_conditions,
        )
    elif must_conditions:
        return Filter(must=must_conditions)
    else:
        return Filter(should=should_conditions)


# =====================================================================
#  跨 Collection 搜索 / 滚动
# =====================================================================

def search_all_collections(
    query_vector: list,
    limit: int = 20,
    query_filter=None,
) -> list:
    """在所有 Qdrant collections 中搜索，合并去重结果。"""
    all_results = []
    collections = get_target_qdrant_collections()

    filter_tag = " (带 filter)" if query_filter else ""
    print(f"[Qdrant] 搜索 {len(collections)} 个 collections{filter_tag}: {collections}")

    for coll_name in collections:
        try:
            store = _get_qdrant_store(coll_name)
            results = store.search(
                [query_vector],
                limit=limit,
                query_filter=query_filter,
            )
            docs = results[0] if results else []

            for doc in docs:
                doc['_collection'] = coll_name
                all_results.append(doc)
        except Exception as e:
            print(f"[Qdrant] 搜索 {coll_name} 失败: {e}")

    # 去重：按 CSV 原始整行去重
    dedup = {}
    for doc in all_results:
        row_key = (
            str(doc.get('line', '')).strip(),
            str(doc.get('station', '')).strip(),
            str(doc.get('problem', '') or doc.get('problem_description', '')).strip(),
            str(doc.get('cause', '') or doc.get('cause_analysis', '')).strip(),
            str(doc.get('action', '') or doc.get('containment_action', '')).strip(),
            str(doc.get('plan', '') or doc.get('action_plan', '')).strip(),
            str(doc.get('date', '')).strip(),
        )
        existing = dedup.get(row_key)
        if not existing or (doc.get('score') or 0) > (existing.get('score') or 0):
            dedup[row_key] = doc

    dedup_results = list(dedup.values())
    dedup_results.sort(key=lambda x: x.get('score', 0), reverse=True)
    print(f"[Qdrant] 去重: {len(all_results)} -> {len(dedup_results)} 条")
    return dedup_results[:limit]


def scroll_all_collections(
    query_filter,
    limit: int = 200,
) -> list:
    """在所有 Qdrant collections 中使用 scroll 方式取出所有匹配记录。

    适合枚举型查询（如「某设备出过哪些故障」）：不做向量相似度排序，
    直接按过滤条件取出全部匹配的原始 CSV 行。
    """
    all_results = []
    collections = get_target_qdrant_collections()

    print(f"[Qdrant] scroll 搜索 {len(collections)} 个 collections (带 filter): {collections}")

    for coll_name in collections:
        try:
            store = _get_qdrant_store(coll_name)
            docs = store.scroll_by_filter(query_filter=query_filter, limit=limit)
            for doc in docs:
                doc['_collection'] = coll_name
                all_results.append(doc)
            print(f"[Qdrant] scroll {coll_name}: {len(docs)} 条")
        except Exception as e:
            print(f"[Qdrant] scroll {coll_name} 失败: {e}")

    # 去重
    dedup = {}
    for doc in all_results:
        row_key = (
            str(doc.get('line', '')).strip(),
            str(doc.get('station', '')).strip(),
            str(doc.get('problem', '') or doc.get('problem_description', '')).strip(),
            str(doc.get('cause', '') or doc.get('cause_analysis', '')).strip(),
            str(doc.get('action', '') or doc.get('containment_action', '')).strip(),
            str(doc.get('plan', '') or doc.get('action_plan', '')).strip(),
            str(doc.get('date', '')).strip(),
        )
        if row_key not in dedup:
            dedup[row_key] = doc

    dedup_results = list(dedup.values())
    dedup_results.sort(key=lambda x: str(x.get('date', '') or ''), reverse=True)
    print(f"[Qdrant] scroll 去重: {len(all_results)} -> {len(dedup_results)} 条")
    return dedup_results[:limit]
