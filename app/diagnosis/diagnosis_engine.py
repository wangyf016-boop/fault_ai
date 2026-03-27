"""
智能故障诊断引擎

三段式诊断流程：
  第一部分 — 从 Neo4j 知识图谱中检索相关子图，返回 ECharts 格式的图谱数据
  第二部分 — 利用图谱关键词增强查询，从 Qdrant 检索 top-20 / score≥0.6 的原始记录
  第三部分 — 对记录进行四维度优先级排序，生成排查流程数据
"""

from __future__ import annotations

import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv()

# ECharts 类别颜色（与前端 KnowledgeGraph.jsx 保持一致）
KG_CATEGORIES = [
    {"name": "Problem"},
    {"name": "Cause"},
    {"name": "Solution"},
    {"name": "Area"},
    {"name": "Equipment"},
    {"name": "Component"},
]


# ---------------------------------------------------------------------------
# 第一部分：知识图谱子图检索
# ---------------------------------------------------------------------------
def query_kg_subgraph(
    question: str,
    embedder: Any,
    *,
    neo4j_uri: Optional[str] = None,
    neo4j_user: Optional[str] = None,
    neo4j_password: Optional[str] = None,
    top_k: int = 5,
) -> Dict[str, Any]:
    """
    使用向量相似度在 Neo4j 中找到与用户问题最相关的 Problem 节点，
    并展开其邻居节点（Cause / Solution / Area / Equipment / Component），
    返回 ECharts graph series 可直接消费的 ``{nodes, links, categories}`` 数据。

    Parameters
    ----------
    question : str
        用户输入的故障描述
    embedder : EmbeddingModel
        embedding 实例
    top_k : int
        向量检索返回的 Problem 数量

    Returns
    -------
    dict
        - nodes : list[dict]   — ECharts graph 节点
        - links : list[dict]   — ECharts graph 边
        - categories : list    — ECharts categories
        - summary : str        — 简短文本摘要（模板，不调用 LLM）
    """
    uri = neo4j_uri or os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687")
    user = neo4j_user or os.getenv("NEO4J_USERNAME", "neo4j")
    pwd = neo4j_password or os.getenv("NEO4J_PASSWORD", "12345678")

    t0 = time.time()
    query_vector = embedder.embed_query(question).tolist()
    t1 = time.time()
    print(f"[Diagnosis-KG] ⏱️ Embedding 耗时: {t1 - t0:.2f}s")

    driver = GraphDatabase.driver(uri, auth=(user, pwd), encrypted=False)
    nodes_map: Dict[str, Dict] = {}
    links: List[Dict] = []

    try:
        _db = os.getenv("NEO4J_DATABASE", "machining")
        with driver.session(database=_db) as session:
            # 向量检索最相关的 Problem 节点 + 其 1-hop 邻居
            cypher = """
            CALL db.index.vector.queryNodes('problem_embedding', $top_k, $vec)
            YIELD node AS p, score
            OPTIONAL MATCH (p)-[r]-(neighbor)
            RETURN
                elementId(p)       AS pid,
                labels(p)          AS p_labels,
                p.name             AS p_desc,
                p.name             AS p_pheno,
                score,
                type(r)            AS rel_type,
                elementId(neighbor) AS nid,
                labels(neighbor)   AS n_labels,
                COALESCE(neighbor.name, '') AS n_name
            """
            result = session.run(cypher, vec=query_vector, top_k=top_k)

            for rec in result:
                pid = rec["pid"]
                if pid and pid not in nodes_map:
                    # Problem 节点
                    raw_desc = rec["p_pheno"] or rec["p_desc"] or ""
                    display = _extract_phenomenon(raw_desc)
                    nodes_map[pid] = _make_echarts_node(
                        pid, display, category=0, size=40, full_name=raw_desc,
                    )

                nid = rec["nid"]
                rel_type = rec["rel_type"]
                if nid and nid not in nodes_map:
                    n_labels = rec["n_labels"] or []
                    n_name = rec["n_name"] or ""
                    cat = _label_to_category(n_labels)
                    nodes_map[nid] = _make_echarts_node(
                        nid, n_name, category=cat, size=32,
                    )

                if pid and nid and rel_type:
                    link_id = f"{pid}_{nid}_{rel_type}"
                    if not any(l.get("_id") == link_id for l in links):
                        links.append({
                            "source": pid,
                            "target": nid,
                            "name": _rel_display(rel_type),
                            "_id": link_id,
                            "lineStyle": {"width": 1.5},
                        })
    finally:
        driver.close()

    t2 = time.time()
    print(f"[Diagnosis-KG] ⏱️ Neo4j 子图查询耗时: {t2 - t1:.2f}s, "
          f"节点={len(nodes_map)}, 边={len(links)}")

    # 清理辅助字段
    nodes_list = list(nodes_map.values())
    for lk in links:
        lk.pop("_id", None)

    summary = f"知识图谱中找到 {len(nodes_list)} 个相关节点、{len(links)} 条关系。"

    return {
        "nodes": nodes_list,
        "links": links,
        "categories": KG_CATEGORIES,
        "summary": summary,
    }


# ---------------------------------------------------------------------------
# 第二部分：向量数据库原始记录检索
# ---------------------------------------------------------------------------
def query_original_records(
    question: str,
    embedder: Any,
    search_fn,           # server.search_all_collections
    *,
    kg_nodes: Optional[List[Dict]] = None,
    limit: int = 20,
    score_threshold: float = 0.6,
) -> Tuple[List[Dict], str]:
    """
    利用知识图谱关键词增强查询，在 Qdrant 中检索原始故障记录。

    Parameters
    ----------
    question : str
        用户提问
    embedder : EmbeddingModel
        embedding 实例
    search_fn : callable
        ``server.search_all_collections(vec, limit)``
    kg_nodes : list[dict], optional
        第一部分返回的 KG 节点（可从中提取关键词增强查询）
    limit : int
        最多返回条数（默认 20）
    score_threshold : float
        最低相似度阈值（默认 0.6）

    Returns
    -------
    (records, summary)
        records: 前端可用的字典列表
        summary: 简短文本摘要
    """
    t0 = time.time()

    # 增强查询：拼接 KG 中关键的 Cause / Equipment 名称
    enhanced_query = question
    if kg_nodes:
        extras = []
        for n in kg_nodes:
            cat = n.get("category", -1)
            name = n.get("fullName") or n.get("name") or ""
            if cat in (1, 4) and name:          # Cause / Equipment
                extras.append(name[:40])
        if extras:
            enhanced_query = f"{question} {' '.join(extras[:5])}"
            print(f"[Diagnosis-Records] 增强查询: {enhanced_query[:100]}...")

    vec = embedder.embed_query(enhanced_query).tolist()
    t1 = time.time()
    print(f"[Diagnosis-Records] ⏱️ Embedding 耗时: {t1 - t0:.2f}s")

    # Qdrant 多 collection 检索
    raw_docs = search_fn(vec, limit=limit)
    t2 = time.time()
    print(f"[Diagnosis-Records] ⏱️ Qdrant 检索耗时: {t2 - t1:.2f}s, 原始={len(raw_docs)} 条")

    # 格式化 + 过滤
    records: List[Dict] = []
    for doc in raw_docs:
        score = doc.get("score") or 0
        if score < score_threshold:
            continue
        records.append({
            "id":         str(doc.get("id", "")),
            "line":       str(doc.get("line", "")),
            "station":    str(doc.get("station", "")),
            "problem":    str(doc.get("problem_description", "") or doc.get("problem", "")),
            "cause":      str(doc.get("cause_analysis", "") or doc.get("cause", "")),
            "action":     str(doc.get("containment_action", "") or doc.get("action", "")),
            "plan":       str(doc.get("action_plan", "") or doc.get("plan", "")),
            "date":       str(doc.get("date", "")),
            "downtime":   str(doc.get("downtime", "") or doc.get("总停机时间 (Minutes)", "") or "0"),
            "score":      score,
            "score_percent": round(score * 100, 2),
            "collection": doc.get("_collection", ""),
        })

    # 限制最多 20 条
    records = records[:limit]

    if records:
        top_score = max(r["score_percent"] for r in records)
        summary = (
            f"向量数据库中检索到 {len(records)} 条相似度≥{int(score_threshold * 100)}% 的故障记录，"
            f"最高相似度 {top_score:.1f}%。"
        )
    else:
        summary = f"未检索到相似度≥{int(score_threshold * 100)}% 的故障记录。"

    return records, summary


# ---------------------------------------------------------------------------
# 第三部分：优先级排序 + 流程图数据
# ---------------------------------------------------------------------------
def build_flowchart_data(
    records: List[Dict],
) -> Tuple[List[Dict], str]:
    """
    对检索到的记录进行四维度优先级排序，返回排查流程数据。

    Returns
    -------
    (sorted_records, summary)
        sorted_records: 按优先级排序后的记录（含 priority_* 字段）
        summary: 简短排查建议摘要
    """
    from app.diagnosis.priority_scorer import compute_priority, scored_to_dicts

    if not records:
        return [], "无可用记录，无法生成排查流程。"

    scored = compute_priority(records)
    sorted_records = scored_to_dicts(scored)

    # 生成简短排查建议（不调用 LLM）
    lines = ["根据**频率、相似度、近期度、排查效率**四维度分析，建议排查顺序：\n"]
    for s in scored[:5]:                        # 只显示 top-5
        r = s.record
        cause = r.get("cause") or r.get("cause_analysis") or "原因未知"
        cause_short = cause[:40] + ("..." if len(cause) > 40 else "")
        lines.append(
            f"{s.rank}. **{cause_short}**  "
            f"（综合评分 {s.total_score:.2f} · "
            f"出现 {s.occurrence_count} 次 · "
            f"相似度 {s.similarity_score:.0%}）"
        )

    summary = "\n".join(lines)
    return sorted_records, summary


# ---------------------------------------------------------------------------
# 内部辅助
# ---------------------------------------------------------------------------
def _extract_phenomenon(desc: str) -> str:
    """从 Problem.description 中截取故障现象部分"""
    if not desc:
        return "未知问题"
    if "故障现象：" in desc:
        start = desc.index("故障现象：") + len("故障现象：")
        end = desc.find(" |", start)
        phen = desc[start:end].strip() if end > start else desc[start:].strip()
        return phen[:50] + "..." if len(phen) > 50 else phen
    if "|" in desc:
        return desc.split("|")[0].strip()[:50]
    return desc[:50] + ("..." if len(desc) > 50 else "")


def _label_to_category(labels: List[str]) -> int:
    """Neo4j label → ECharts category index"""
    mapping = {
        "Problem": 0, "Cause": 1, "Solution": 2,
        "Area": 3, "Equipment": 4, "Component": 5,
    }
    for lb in labels:
        if lb in mapping:
            return mapping[lb]
    return 0


def _rel_display(rel_type: str) -> str:
    """关系类型 → 中文显示"""
    mapping = {
        "INCLUDE": "包含",
        "HAS_PART": "部件",
        "HAS_FAULT": "故障",
        "CAUSED_BY": "原因",
        "SOLVED_BY": "解决方案",
    }
    return mapping.get(rel_type, rel_type)


def _make_echarts_node(
    node_id: str,
    name: str,
    category: int,
    size: int = 30,
    full_name: str = "",
) -> Dict:
    """创建 ECharts graph series 节点"""
    display = name[:25] + "..." if len(name) > 25 else name
    colors = ["#ef4444", "#f97316", "#4827AF", "#3b82f6", "#14b8a6", "#10b981"]
    return {
        "id": node_id,
        "name": display,
        "fullName": full_name or name,
        "category": category,
        "symbolSize": size,
        "value": size,
        "itemStyle": {"color": colors[category] if category < len(colors) else "#9ca3af"},
    }
