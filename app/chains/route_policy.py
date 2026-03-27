from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from app.retrievers.qdrant_search import _extract_structured_fields


BuildContextSnippets = Callable[[list[dict[str, Any]]], str]


DIAGNOSIS_KEYWORDS = [
    "诊断",
    "排查",
    "排故",
    "故障诊断",
    "智能诊断",
    "排查流程",
    "怎么排查",
    "如何排查",
    "排查顺序",
    "排查建议",
    "诊断分析",
    "diagnos",
    "troubleshoot",
    "root cause analysis",
]

HYBRID_KEYWORDS = [
    "混合",
    "综合",
    "全面",
    "详细",
    "hybrid",
    "comprehensive",
    "detailed",
    "complete",
]

ENUM_KEYWORDS = [
    "哪些",
    "有什么",
    "列出",
    "列举",
    "出过",
    "全部",
    "所有",
    "过往",
    "曾经",
    "all",
    "list",
    "which",
    "what problems",
    "what issues",
]

SIMILAR_KEYWORDS = [
    "类似",
    "相似",
    "similar",
    "history",
    "previous",
    "past",
    "历史案例",
    "历史记录",
]

SOLUTION_KEYWORDS = [
    "怎么办",
    "怎么解决",
    "怎么处理",
    "怎么修",
    "如何解决",
    "如何处理",
    "解决方案",
    "处理方法",
    "原因是什么",
    "为什么",
    "how to",
    "how do",
    "solution",
    "fix",
    "solve",
    "resolve",
    "why",
    "cause",
    "reason",
]

GRAPH_KEYWORDS = [
    "知识图谱",
    "图谱",
    "关系图",
    "节点",
    "可视化",
    "graph",
    "visualize",
]

TABLE_KEYWORDS = [
    "表格",
    "列表",
    "list",
    "table",
]

PROBLEM_KEYWORDS = [
    "故障报警",
    "检测报警",
    "刀库门报警",
    "报警",
    "故障",
    "异常",
    "无信号",
    "报错",
    "停机",
    "卡滞",
    "失败",
    "不良",
    "超差",
    "偏差",
    "过电流",
    "高温",
    "漏油",
    "漏气",
    "漏水",
    "松动",
    "断裂",
    "超时",
]


@dataclass(frozen=True)
class RoutePlan:
    route: str
    reason: str
    top_k: int | None = None
    context: str | None = None
    qdrant_records: list[dict[str, Any]] | None = None
    search_strategy: str | None = None
    show_graph: bool | None = None
    show_table: bool | None = None


def build_route_plan(
    state: Mapping[str, Any],
    *,
    build_context_snippets: BuildContextSnippets,
) -> RoutePlan:
    query = str(state["query"])
    show_graph, show_table = _detect_display_intent(query)

    if state.get("is_followup", False):
        return _build_followup_plan(
            state,
            build_context_snippets=build_context_snippets,
            show_graph=show_graph,
            show_table=show_table,
        )

    return _build_search_plan(
        query,
        current_top_k=state.get("top_k"),
        show_graph=show_graph,
        show_table=show_table,
    )


def _build_followup_plan(
    state: Mapping[str, Any],
    *,
    build_context_snippets: BuildContextSnippets,
    show_graph: bool,
    show_table: bool,
) -> RoutePlan:
    followup_records = state.get("followup_records", []) or state.get("qdrant_records", [])
    history_text = _build_recent_history_text(state.get("messages", []))
    context_parts: list[str] = []
    normalized_records: list[dict[str, Any]] | None = None

    if followup_records:
        normalized_records = followup_records
        context_parts.append(
            f"[来源: 当前结果记录]\n\n{build_context_snippets(normalized_records[:60])}"
        )
    if history_text:
        context_parts.append(f"[来源: 对话历史]\n\n{history_text}")

    context = "\n\n".join(context_parts) if context_parts else "[来源: 对话历史]\n\n"
    return RoutePlan(
        route="history",
        reason="followup_forced_history",
        context=context,
        qdrant_records=normalized_records,
        show_graph=show_graph,
        show_table=show_table,
    )


def _build_search_plan(
    query: str,
    *,
    current_top_k: Any,
    show_graph: bool,
    show_table: bool,
) -> RoutePlan:
    query_lower = query.lower()

    if _contains_keyword(query, query_lower, DIAGNOSIS_KEYWORDS):
        return RoutePlan(
            route="diagnosis",
            reason="diagnosis_keywords",
            top_k=40,
            show_graph=True,
            show_table=True,
        )

    if _contains_keyword(query, query_lower, HYBRID_KEYWORDS):
        return RoutePlan(
            route="search",
            reason="hybrid_keywords",
            search_strategy="hybrid",
            top_k=10,
            show_graph=show_graph,
            show_table=show_table,
        )

    is_enum = _contains_keyword(query, query_lower, ENUM_KEYWORDS)
    is_similar = _contains_keyword(query, query_lower, SIMILAR_KEYWORDS)
    if is_enum or is_similar:
        if is_enum and not is_similar:
            return RoutePlan(
                route="search",
                reason="enum_keywords",
                search_strategy="neo4j",
                top_k=25,
                show_graph=show_graph,
                show_table=show_table,
            )
        return RoutePlan(
            route="search",
            reason="similar_or_mixed_keywords",
            search_strategy="qdrant",
            top_k=25,
            show_graph=show_graph,
            show_table=show_table,
        )

    if _looks_like_precise_structured_query(query):
        return RoutePlan(
            route="search",
            reason="structured_precise_query",
            search_strategy="neo4j",
            top_k=12,
            show_graph=show_graph,
            show_table=show_table,
        )

    baseline_top_k = 3 if current_top_k == 3 or current_top_k is None else None
    has_solution_keyword = _contains_keyword(query, query_lower, SOLUTION_KEYWORDS)

    if not has_solution_keyword and len(query) < 100:
        return RoutePlan(
            route="search",
            reason="short_fault_description",
            search_strategy="qdrant",
            top_k=20,
            show_graph=show_graph,
            show_table=show_table,
        )

    if has_solution_keyword:
        return RoutePlan(
            route="search",
            reason="solution_keywords",
            search_strategy="neo4j",
            top_k=baseline_top_k,
            show_graph=show_graph,
            show_table=show_table,
        )

    return RoutePlan(
        route="search",
        reason="default_qdrant",
        search_strategy="qdrant",
        top_k=20,
        show_graph=show_graph,
        show_table=show_table,
    )


def _contains_keyword(query: str, query_lower: str, keywords: Sequence[str]) -> bool:
    return any(kw in query for kw in keywords) or any(kw in query_lower for kw in keywords)


def _detect_display_intent(query: str) -> tuple[bool, bool]:
    query_lower = query.lower()
    show_graph = _contains_keyword(query, query_lower, GRAPH_KEYWORDS)
    show_table = _contains_keyword(query, query_lower, TABLE_KEYWORDS)
    return show_graph, show_table


def _looks_like_precise_structured_query(query: str) -> bool:
    fields = _extract_structured_fields(query)
    has_station = bool(fields.get("station"))
    has_component = bool(fields.get("components"))
    has_problem = any(kw in query for kw in PROBLEM_KEYWORDS)
    return has_station and (has_component or has_problem)


def _build_recent_history_text(messages: Sequence[Any]) -> str:
    return "\n".join(
        message.content
        for message in messages[-8:]
        if hasattr(message, "content")
    )
