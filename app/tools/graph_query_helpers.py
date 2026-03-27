"""Neo4j 图查询辅助函数

从 server.py 抽取的图查询构建工具，供 server.py 和 neo4j_tool.py 共用，
消除两者之间的循环依赖。
"""
from __future__ import annotations

import re

# =====================================================================
#  Graph Cypher 构建工具
# =====================================================================

_GRAPH_COL_MAP = {
    "area": "a.name",
    "equipment": "e.name",
    "component": "c.name",
    "problem": "p.name",
    "cause": "ca.name",
    "solution": "s.name",
}

_GRAPH_NUM_PREFIX_RE = re.compile(r'^[\d一二三四五六七八九十百零#]+[号站线]?')


def _graph_field_variants(raw: str, max_variants: int = 12) -> list:
    """生成 fallback 子串列表：原词(=) → 去前缀(CONTAINS) → 连续子串(CONTAINS)。"""
    if not raw:
        return []
    variants: list[tuple[str, str]] = [(raw, '='), (raw, 'CONTAINS')]
    stripped = _GRAPH_NUM_PREFIX_RE.sub('', raw).strip()
    if stripped and stripped != raw:
        variants.append((stripped, 'CONTAINS'))

    base = stripped or raw
    seen = {raw, stripped} if stripped else {raw}
    for length in range(len(base) - 1, 1, -1):
        for start in range(len(base) - length + 1):
            sub = base[start:start + length]
            if sub not in seen:
                seen.add(sub)
                variants.append((sub, 'CONTAINS'))
                if len(variants) >= max_variants:
                    return variants
    return variants


def _build_graph_condition(field: str, value: str, op: str, param_name: str) -> tuple:
    """构建单个 WHERE 条件片段和参数字典。"""
    col = _GRAPH_COL_MAP[field]
    if op == '=':
        return f"  AND toLower({col}) = toLower(${param_name})", {param_name: value}
    return f"  AND toLower({col}) CONTAINS toLower(${param_name})", {param_name: value}


def _build_component_problem_trials(component: str, problem: str) -> list:
    """生成 component × problem 的 fallback 组合列表。"""
    comp_variants = _graph_field_variants(component) if component else []
    prob_variants = _graph_field_variants(problem) if problem else []

    trial_pairs = []
    if comp_variants and prob_variants:
        for cv, cop in comp_variants:
            for pv, pop in prob_variants:
                trial_pairs.append(((cv, cop), (pv, pop)))
        for cv, cop in comp_variants:
            trial_pairs.append(((cv, cop), None))
        for pv, pop in prob_variants:
            trial_pairs.append((None, (pv, pop)))
        trial_pairs.append((None, None))
    elif comp_variants:
        for cv, cop in comp_variants:
            trial_pairs.append(((cv, cop), None))
        trial_pairs.append((None, None))
    elif prob_variants:
        for pv, pop in prob_variants:
            trial_pairs.append((None, (pv, pop)))
        trial_pairs.append((None, None))
    else:
        trial_pairs.append((None, None))
    return trial_pairs
