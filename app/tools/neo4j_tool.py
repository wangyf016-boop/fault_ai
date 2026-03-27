"""Neo4j RAG Tool - 完整的查询生成、执行和总结流程"""
from __future__ import annotations

import os
import re
import json
from typing import Optional, Any, Dict, List

from dotenv import load_dotenv
from neo4j import GraphDatabase
from app.chains.search_records import qdrant_doc_to_frontend_record
from app.settings.settings_router import get_prompts
from app.retrievers.qdrant_search import (
    search_all_collections,
    scroll_all_collections,
    _extract_structured_fields,
    _build_qdrant_filter,
    _apply_station_boost,
    _apply_problem_boost,
    _group_docs_by_problem,
)
from app.tools.graph_query_helpers import (
    _build_component_problem_trials,
    _build_graph_condition,
)

load_dotenv()


_STATION_RE = re.compile(r'([A-Z]{2,3}\d{1,3}-[A-Z]\d+|OP\d+(?:\.\d+)?|ST\d+(?:\.\d+)?)', re.IGNORECASE)
_ENUM_QUERY_KWS = ['哪些', '有什么', '列出', '列举', '出过', '全部', '所有', '过往', '曾经']
_GENERIC_PROBLEM_KWS = {'故障', '问题'}
_WEAK_PROBLEM_KWS = {'报警', '异常'}
_FAULT_INTENT_KWS = {'故障', '报警', '异常', '无信号', '报错', '停机', '卡滞', '失败', '不良', '过电流', '高温', '漏油', '漏气', '漏水', '断裂', '怎么办', '怎么处理', '怎么解决', '如何处理', '如何解决'}
_NON_FAULT_NOISE_KWS = {'计划', '测试', '移机', '点检', '保养', '换型', '任务', '更换电池', '恢复'}


class TextToCypherGenerator:
    """将自然语言问题转换为 Neo4j Cypher 查询"""

    def __init__(self, llm: Any, schema_description: str, verbose: bool = False):
        self.llm = llm
        self.schema_description = schema_description
        self.verbose = verbose

    def generate(self, question: str, chat_history: List[Dict[str, str]] = None, is_followup: bool = False) -> Dict[str, Any]:
        """生成 Cypher 查询"""
        if not question:
            return {}
        
        # 追问时：从历史提取上下文，用精确查询
        if is_followup and chat_history:
            context = self._extract_context_from_history(chat_history)
            if self.verbose:
                print(f"[TextToCypher] 追问上下文: {context}")
            
            # 如果能提取到站点或日期，使用精确查询
            if context.get('station') or context.get('date'):
                return self._generate_context_query(context, question)

        # 新问题：若已显式给出工位 / 部件 / 故障关键词，优先走结构化精确查询
        structured_context = self._extract_structured_context_from_question(question)
        if structured_context.get('station') or structured_context.get('component') or structured_context.get('problem'):
            if self.verbose:
                print(f"[TextToCypher] 使用结构化精确查询: {structured_context}")
            return self._generate_structured_query(structured_context)
        
        # 新问题：使用向量检索
        if self.verbose:
            print(f"[TextToCypher] 使用向量检索")
        return self._generate_vector_query()

    def _extract_station_token(self, text: str) -> str:
        if not text:
            return ''
        m = _STATION_RE.search(text)
        return m.group(1).upper() if m else ''

    def _extract_context_from_history(self, chat_history: List[Dict[str, str]]) -> Dict[str, Any]:
        """从对话历史中提取站点、日期等上下文"""
        context = {}
        
        if not chat_history:
            return context
        
        # 策略：优先从用户问题中提取，按时间倒序查找
        user_messages = [m.get('content', '') for m in chat_history if m.get('role') == 'user']
        assistant_messages = [m.get('content', '') for m in chat_history if m.get('role') == 'assistant']
        
        if self.verbose:
            print(f"[TextToCypher] 用户消息数: {len(user_messages)}, AI消息数: {len(assistant_messages)}")
        
        # 1. 从用户历史问题中提取站点（倒序，优先最近的）
        station = None
        for msg in reversed(user_messages):
            station = self._extract_station_token(msg)
            if station:
                if self.verbose:
                    print(f"[TextToCypher] 从用户问题提取站点: {station}")
                break
        
        # 2. 如果用户问题中没有站点，从AI回复中提取（通常AI会复述站点名）
        if not station:
            for msg in reversed(assistant_messages):
                station = self._extract_station_token(msg)
                if station:
                    if self.verbose:
                        print(f"[TextToCypher] 从AI回复提取站点: {station}")
                    break
        
        if station:
            context['station'] = station
        
        # 3. 提取日期/月份 - 先从用户消息中找，再从AI回复中找
        all_text = " ".join([m.get('content', '') for m in chat_history[-4:]])
        
        # 格式1: 2022-10-19 或 2022/10/19
        date_match = re.search(r'(\d{4})[-/](\d{1,2})[-/](\d{1,2})', all_text)
        if date_match:
            year, month, day = date_match.groups()
            context['date'] = f"{year}-{month.zfill(2)}-{day.zfill(2)}"
            context['year_month'] = f"{year}-{month.zfill(2)}"
        else:
            # 格式2: 2022年7月27日 - 完整日期
            date_match2 = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日', all_text)
            if date_match2:
                year, month, day = date_match2.groups()
                context['date'] = f"{year}-{month.zfill(2)}-{day.zfill(2)}"
                context['year_month'] = f"{year}-{month.zfill(2)}"
            else:
                # 格式3: 只有年月 2022年7月
                month_match = re.search(r'(\d{4})年(\d{1,2})月', all_text)
                if month_match:
                    year, month = month_match.groups()
                    context['year_month'] = f"{year}-{month.zfill(2)}"
        
        # 如果还没有 year_month，尝试从 AI 回复中提取最近提到的日期
        if not context.get('year_month'):
            for msg in reversed(assistant_messages):
                # 匹配 "2025年3月19日" 格式
                ai_date_match = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日', msg)
                if ai_date_match:
                    year, month, day = ai_date_match.groups()
                    context['year_month'] = f"{year}-{month.zfill(2)}"
                    if self.verbose:
                        print(f"[TextToCypher] 从AI回复提取年月: {context['year_month']}")
                    break
        
        # 4. 保存上一个用户问题（用于追问时向量检索找到目标记录）
        if user_messages:
            context['previous_question'] = user_messages[-1]
        
        if self.verbose:
            print(f"[TextToCypher] 提取的上下文: {context}")
        
        return context

    def _extract_structured_context_from_question(self, question: str) -> Dict[str, Any]:
        """从新问题中提取 station/component/problem，供 Neo4j 精确查询使用。"""
        context: Dict[str, Any] = {}
        q = (question or '').strip()
        if not q:
            return context

        fields = _extract_structured_fields(q)
        station = fields.get('station') or self._extract_station_token(q)
        components = fields.get('components') or []
        component = components[0] if components else ''

        is_enum_query = any(kw in q for kw in _ENUM_QUERY_KWS)
        problem = ''
        problem_kws = [
            '故障报警', '检测报警', '刀库门报警', '报警', '故障', '异常', '无信号', '报错', '停机', '卡滞',
            '失败', '不良', '超差', '偏差', '过电流', '高温', '漏油', '漏气', '漏水', '松动', '断裂', '超时'
        ]

        for kw in problem_kws:
            if kw in q:
                problem = kw
                break

        if is_enum_query and problem in _GENERIC_PROBLEM_KWS:
            problem = ''
        if station and not component and problem in _WEAK_PROBLEM_KWS and is_enum_query:
            problem = ''

        if station:
            context['station'] = station
        if component:
            context['component'] = component
        if problem:
            context['problem'] = problem
        return context

    def _generate_structured_query(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """为明确工位/部件/故障的新问题生成精确 Cypher。"""
        where_parts = []
        params: Dict[str, Any] = {}

        if context.get('station'):
            where_parts.append("(e.name CONTAINS $station OR c.name CONTAINS $station)")
            params['station'] = context['station']
        if context.get('component'):
            where_parts.append("(c.name CONTAINS $component OR p.name CONTAINS $component)")
            params['component'] = context['component']
        if context.get('problem'):
            where_parts.append("p.name CONTAINS $problem")
            params['problem'] = context['problem']

        where_clause = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""
        cypher = f"""MATCH path = (a:Area)-[r0:INCLUDE]->(e:Equipment)-[r1:HAS_PART]->(c:Component)
      -[r2:HAS_FAULT]->(p:Problem)-[r3:CAUSED_BY]->(ca:Cause)-[r4:SOLVED_BY]->(sol:Solution)
{where_clause}
WITH path, a, e, c, p, ca, sol,
     r1, r2, r3, r4,
     [r IN [r2, r3, r4] WHERE r.source_rows IS NOT NULL AND size(r.source_rows) > 0 | r.source_rows] AS sr_lists
WITH path, a, e, c, p, ca, sol, r1, sr_lists,
     CASE WHEN size(sr_lists) = 0 THEN NULL
          ELSE head([x IN sr_lists[0] WHERE ALL(lst IN sr_lists WHERE x IN lst)])
     END AS shared_row
WHERE (size(sr_lists) = 0 OR shared_row IS NOT NULL)
  AND (shared_row IS NULL OR shared_row IN coalesce(r1.row_ids, r1.source_rows, []))
RETURN a.name AS line, e.name AS station, c.name AS component,
       p.name AS problem, ca.name AS cause, sol.name AS action
LIMIT 60"""

        return {
            'cypher': cypher,
            'parameters': params,
            'reasoning': f'结构化精确查询: {params}'
        }

    def _generate_context_query(self, context: Dict[str, Any], question: str) -> Dict[str, Any]:
        """基于上下文生成精确查询（追问用）— 适配 Version2 schema
        Version2 schema: Area-[INCLUDE]->Equipment-[HAS_PART]->Component-[HAS_FAULT]->Problem-[CAUSED_BY]->Cause-[SOLVED_BY]->Solution
        """
        match_clauses = ["MATCH (p:Problem)"]
        conditions = []
        params = {}
        
        if context.get('station'):
            # Version2 没有 Station 节点，站点信息可能在 Equipment/Component 的 name 中
            match_clauses.append("MATCH (comp:Component)-[:HAS_FAULT]->(p)")
            match_clauses.append("MATCH (eq:Equipment)-[:HAS_PART]->(comp)")
            conditions.append("(eq.name CONTAINS $station OR comp.name CONTAINS $station)")
            params['station'] = context['station']
        
        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        
        limit = 10
        
        cypher = f"""{chr(10).join(match_clauses)}
{where_clause}
OPTIONAL MATCH (p)-[:CAUSED_BY]->(c:Cause)
OPTIONAL MATCH (c)-[:SOLVED_BY]->(sol:Solution)
OPTIONAL MATCH (comp2:Component)-[:HAS_FAULT]->(p)
OPTIONAL MATCH (eq2:Equipment)-[:HAS_PART]->(comp2)
OPTIONAL MATCH (area:Area)-[:INCLUDE]->(eq2)
WITH p, c, eq2, area, COLLECT(DISTINCT sol.name) AS actions
RETURN p.name AS problem, c.name AS cause,
       CASE WHEN size(actions) > 0 THEN reduce(acc='', x IN actions | acc + CASE WHEN acc='' THEN '' ELSE '、' END + COALESCE(x,'')) ELSE NULL END AS action,
       COALESCE(area.name, '') AS line, COALESCE(eq2.name, '') AS station
LIMIT {limit}"""
        
        if self.verbose:
            print(f"[TextToCypher] 使用精确查询: station={params.get('station')}")
        
        return {
            'cypher': cypher,
            'parameters': params,
            'reasoning': f'基于上下文精确查询: {params}'
        }

    def _generate_vector_query(self) -> Dict[str, Any]:
        """生成向量检索查询 — 完整路径 + shared_row 同源一致性。

        路径: Area→Equipment→Component→Problem→Cause→Solution。
        同源锚点由 r2/r3/r4（HAS_FAULT/CAUSED_BY/SOLVED_BY）source_rows 交集得到，
        且要求 shared_row 也出现在 r1(HAS_PART) 的 row_ids/source_rows 中。
        """
        cypher = """CALL db.index.vector.queryNodes('problem_embedding', 10, $query_vector)
YIELD node AS p, score
    MATCH (a:Area)-[:INCLUDE]->(e:Equipment)-[r1:HAS_PART]->(c:Component)
      -[r2:HAS_FAULT]->(p)-[r3:CAUSED_BY]->(ca:Cause)-[r4:SOLVED_BY]->(sol:Solution)
WITH a, e, c, p, ca, sol, score,
        r1, r2, r3, r4,
     [r IN [r2, r3, r4] WHERE r.source_rows IS NOT NULL AND size(r.source_rows) > 0 | r.source_rows] AS sr_lists
    WITH a, e, c, p, ca, sol, score, r1, sr_lists,
     CASE WHEN size(sr_lists) = 0 THEN NULL
          ELSE head([x IN sr_lists[0] WHERE ALL(lst IN sr_lists WHERE x IN lst)])
        END AS shared_row
WHERE (size(sr_lists) = 0 OR shared_row IS NOT NULL)
  AND (shared_row IS NULL OR shared_row IN coalesce(r1.row_ids, r1.source_rows, []))
RETURN a.name AS line, e.name AS station, c.name AS component,
       p.name AS problem, ca.name AS cause, sol.name AS action, score
ORDER BY score DESC
LIMIT 15"""

        return {
            'cypher': cypher,
            'parameters': {},
            'reasoning': '向量检索 + 完整路径 + shared_row 同源一致性（含 r1 约束）'
        }


class Neo4jRAGTool:
    """Neo4j RAG 工具 - 将自然语言转换为 Cypher，执行查询并总结结果"""

    def __init__(self, llm: Any, neo4j_uri: str, neo4j_user: str, neo4j_password: str, 
                 schema_description: str, verbose: bool = False):
        self.llm = llm
        self.verbose = verbose
        self.cypher_generator = TextToCypherGenerator(llm=llm, schema_description=schema_description, verbose=verbose)
        self.driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password), encrypted=False)

    def close(self):
        self.driver.close()

    @staticmethod
    def _is_fault_intent_query(question: str) -> bool:
        q = (question or '').strip()
        return any(kw in q for kw in _FAULT_INTENT_KWS)

    @staticmethod
    def _is_fault_like_problem(problem: str) -> bool:
        text = (problem or '').strip()
        if not text:
            return False
        if any(kw in text for kw in _NON_FAULT_NOISE_KWS) and not any(kw in text for kw in _FAULT_INTENT_KWS):
            return False
        return True

    def _filter_fault_like_docs(self, docs: List[Dict], question: str, min_keep: int = 5) -> List[Dict]:
        if not docs or not self._is_fault_intent_query(question):
            return docs
        filtered = []
        for doc in docs:
            problem = str(doc.get('problem') or doc.get('problem_description') or '')
            if self._is_fault_like_problem(problem):
                filtered.append(doc)
        return filtered if len(filtered) >= min_keep else docs

    def query(self, question: str, chat_history: List[Dict[str, str]] = None, is_followup: bool = False) -> str:
        """RAG 流程：生成向量 -> 执行Cypher -> LLM总结 (返回文本)"""
        result = self.query_with_records(question, chat_history=chat_history, is_followup=is_followup)
        return result.get('answer', '')

    def query_with_records(self, question: str, chat_history: List[Dict[str, str]] = None, is_followup: bool = False, records_only: bool = False) -> Dict[str, Any]:
        """RAG 流程：生成向量 -> 执行Cypher -> LLM总结 (返回 answer + records)
        records_only=True 时跳过 LLM 总结，直接返回记录（用于前端已有 RESULTS_LEAD_TEXT 的场景）"""
        from app.retrievers.embedding import EmbeddingModel
        
        if self.verbose:
            print(f"\n[Neo4jRAG] 问题: {question}")
            print(f"[Neo4jRAG] 是否追问: {is_followup}")
        
        # 步骤1: 生成 Cypher（追问用精确查询，新问题用向量检索）
        cypher_result = self.cypher_generator.generate(question, chat_history=chat_history, is_followup=is_followup)
        
        # 处理需要向量检索获取上下文的情况
        if cypher_result.get('need_vector_lookup'):
            previous_question = cypher_result.get('previous_question')
            if previous_question:
                # 用上一个问题做向量检索，找到目标记录的设备信息
                target_info = self._lookup_target_record(previous_question)
                if target_info:
                    station = target_info.get('station')
                    if self.verbose:
                        print(f"[Neo4jRAG] 向量检索找到目标记录: station={station}")
                    # 生成查询同设备其他记录的 Cypher
                    if station:
                        cypher_result = self._generate_same_station_query(station)
                    else:
                        return {'answer': "无法确定相关设备信息，请提供更多详情。", 'records': []}
                else:
                    if self.verbose:
                        print(f"[Neo4jRAG] 向量检索未找到目标记录")
                    return {'answer': "无法确定您询问的是哪条记录，请提供更多信息。", 'records': []}
            else:
                return {'answer': "无法确定您询问的是哪条记录，请提供更多信息。", 'records': []}
        
        # 步骤2: 生成查询向量（仅向量检索需要）
        cypher = cypher_result.get('cypher', '')
        parameters = cypher_result.get('parameters', {})
        
        if '$query_vector' in cypher:
            embedder = EmbeddingModel()
            query_vector = embedder.embed_query(question).tolist()
            parameters['query_vector'] = query_vector
            if self.verbose:
                print(f"[Neo4jRAG] 向量维度: {len(query_vector)}")
        
        # 步骤3: 执行查询
        try:
            if self.verbose:
                print(f"[Neo4jRAG] Cypher: {cypher[:100]}...")
                print(f"[Neo4jRAG] 参数: { {k: v for k, v in parameters.items() if k != 'query_vector'} }")
            
            results = self._execute_cypher(cypher, parameters)
            
            if self.verbose:
                print(f"[Neo4jRAG] 查询返回 {len(results)} 条记录")
            
            if not results:
                # Neo4j 主查询为空时，回退 Qdrant 原始记录，避免“有历史记录但图谱没命中”直接空结果
                query_vector = parameters.get('query_vector')
                if not query_vector:
                    embedder = EmbeddingModel()
                    query_vector = embedder.embed_query(question).tolist()

                fallback_records = self._qdrant_to_frontend_records(query_vector=query_vector, limit=20, question=question)
                if not fallback_records:
                    return {'answer': "未找到相关问题记录。", 'records': []}

                if records_only:
                    if self.verbose:
                        print("[Neo4jRAG] Neo4j未命中，records_only 下返回 Qdrant 兜底记录")
                    return {'answer': '', 'records': fallback_records}

                answer_records = self._select_raw_records_for_answer(question, fallback_records, top_k=8)
                pseudo_graph_rows: List[Dict[str, Any]] = []
                for r in fallback_records[:15]:
                    pseudo_graph_rows.append({
                        'line': str(r.get('line', '') or ''),
                        'station': str(r.get('station', '') or ''),
                        'component': str(r.get('component', '') or ''),
                        'problem': str(r.get('problem', '') or ''),
                        'cause': str(r.get('cause', '') or ''),
                        'action': str(r.get('action', '') or r.get('plan', '') or ''),
                        'date': str(r.get('date', '') or ''),
                    })

                fallback_answer = self._summarize_results(question, pseudo_graph_rows, raw_records=answer_records)
                return {'answer': fallback_answer, 'records': fallback_records}
            
            # 步骤4: 组织“双源上下文”供回答（图谱 + Qdrant 原始记录）
            query_vector = parameters.get('query_vector')
            if not query_vector:
                embedder = EmbeddingModel()
                query_vector = embedder.embed_query(question).tolist()
                if self.verbose:
                    print(f"[Neo4jRAG] 生成表格补充向量: {len(query_vector)}")

            graph_records = self._convert_to_frontend_records(results, query_vector=query_vector, question=question)
            records = self._qdrant_to_frontend_records(query_vector=query_vector, limit=20, question=question)
            if not records:
                records = graph_records
            answer_records = self._select_raw_records_for_answer(question, records or graph_records, top_k=8)

            # 关键：回答侧图谱证据与前端 /graph/search 对齐（component/problem 子串回退）
            seed_station, seed_component, seed_problem = self._extract_component_problem_seed(question, answer_records or records)
            aligned_graph_rows, aligned_trace = self._search_graph_rows_aligned(
                station=seed_station,
                component=seed_component,
                problem=seed_problem,
                limit=15,
            )
            if aligned_graph_rows:
                if self.verbose:
                    print(f"[Neo4jRAG] 对齐图谱命中: station='{seed_station}', component='{seed_component}', problem='{seed_problem}', trace='{aligned_trace}'")
                results_for_answer = aligned_graph_rows
            else:
                if self.verbose:
                    print(f"[Neo4jRAG] 对齐图谱未命中，回退原查询结果: station='{seed_station}', component='{seed_component}', problem='{seed_problem}'")
                results_for_answer = results

            # 步骤5: LLM 总结（records_only=True 时跳过，节省 LLM 调用时间）
            if records_only:
                if self.verbose:
                    print(f"[Neo4jRAG] records_only=True，跳过 LLM 总结")
                return {'answer': '', 'records': records}
            answer = self._summarize_results(question, results_for_answer, raw_records=answer_records)
            
            return {'answer': answer, 'records': records}
            
        except Exception as e:
            if self.verbose:
                print(f"[Neo4jRAG] 执行错误: {e}")
            return {'answer': f"查询执行出错: {str(e)}", 'records': []}

    def _convert_to_frontend_records(self, results: List[Dict], query_vector: list = None, question: str = '') -> List[Dict]:
        """将 Neo4j 查询结果转换为前端表格格式。
        
        优化：复用已有的 query_vector 做 1 次 Qdrant 搜索补充日期等字段，
        替代之前逐条 embedding + 逐条搜索的方式（N次→1次）。
        """
        import math
        
        # ── 一次性从 Qdrant 取候选行（用于补充日期等 Neo4j 没有的字段）──
        qdrant_docs: List[Dict] = []
        if query_vector:
            try:
                qdrant_filter = None
                fields = {}
                if question:
                    fields = _extract_structured_fields(question)
                    qdrant_filter = _build_qdrant_filter(fields) if fields else None
                qdrant_docs = search_all_collections(
                    query_vector,
                    limit=max(len(results) * 3, 20),
                    query_filter=qdrant_filter,
                )
                if self.verbose:
                    print(f"[Neo4jRAG] Qdrant 补充查询: 获取 {len(qdrant_docs)} 条候选行")
            except Exception as e:
                if self.verbose:
                    print(f"[Neo4jRAG] Qdrant 补充查询失败（不影响主结果）: {e}")
        
        records = []
        for idx, result in enumerate(results):
            # 处理日期格式
            date_val = result.get('date', '')
            if hasattr(date_val, 'year') and hasattr(date_val, 'month') and hasattr(date_val, 'day'):
                date_str = f"{date_val.year}-{str(date_val.month).zfill(2)}-{str(date_val.day).zfill(2)}"
            else:
                date_str = str(date_val) if date_val else ''
            
            problem_desc = str(result.get('problem', ''))
            station = str(result.get('station', ''))
            cause = result.get('cause') or ''
            action = result.get('action') or ''
            
            # ── 从 Qdrant 候选行中匹配补充（内存匹配，无额外网络调用）──
            qdrant_date = None
            qdrant_action = None
            qdrant_cause = None
            if qdrant_docs and problem_desc:
                for doc in qdrant_docs:
                    doc_problem = doc.get('problem') or doc.get('problem_description') or ''
                    doc_station = str(doc.get('station') or '')
                    # 匹配条件：problem 文本匹配 + station 匹配
                    if (doc_problem == problem_desc or doc_problem in problem_desc or problem_desc in doc_problem) \
                            and (not station or not doc_station or doc_station == station):
                        qdrant_date = doc.get('date') or doc.get('dt') or None
                        qdrant_action = doc.get('action') or None
                        qdrant_cause = doc.get('cause') or None
                        break
            
            # 合并：Neo4j 优先，Qdrant 补空
            final_cause = cause if cause else (str(qdrant_cause) if qdrant_cause else '')
            final_action = action if action else (str(qdrant_action) if qdrant_action else '')
            final_date = date_str if date_str else (str(qdrant_date) if qdrant_date else '')
            
            # 提取仅故障现象部分作为 problem 显示
            display_problem = self._extract_phenomenon(problem_desc)
            
            # Ensure score is JSON safe (no NaN/Infinity)
            score = result.get('score')
            try:
                if score is not None and (math.isnan(score) or math.isinf(score)):
                    score = None
            except:
                pass

            records.append({
                "id": str(idx + 1),
                "line": str(result.get('line', '')),
                "station": station,
                "problem": display_problem,
                "cause": final_cause,
                "action": final_action,
                "plan": str(result.get('plan', '')),
                "date": final_date,
                "score": score
            })
        return records

    def _qdrant_to_frontend_records(self, query_vector: list = None, limit: int = 20, question: str = '') -> List[Dict]:
        """从 Qdrant 获取原始 CSV 行，转换为前端表格格式。

        Qdrant 存储的是完整 CSV 原始数据（line, station, problem, cause, action, plan, date），
        比 Neo4j 的实体碎片更适合直接展示在表格中。
        """
        if not query_vector:
            return []

        try:
            fields = _extract_structured_fields(question) if question else {}
            qdrant_filter = _build_qdrant_filter(fields) if fields else None

            # ── 枚举型查询判断 ──
            # 含「哪些/出过/全部/所有/曾经/过往」等关键词，且有精确工位过滤时，
            # 改用 scroll（无向量排序）取出该工位的全量故障记录，避免向量检索截断
            is_enum_q = any(kw in (question or '') for kw in _ENUM_QUERY_KWS)
            has_station_filter = bool(fields.get('station'))
            has_component_filter = bool(fields.get('components'))
            use_scroll = is_enum_q and has_station_filter and not has_component_filter and qdrant_filter

            qdrant_docs = []
            if use_scroll:
                enum_limit = max(limit * 10, 200)  # 枚举查询取更多
                qdrant_docs = scroll_all_collections(qdrant_filter, limit=enum_limit)
                if self.verbose:
                    print(f"[Neo4jRAG] Qdrant 枚举 scroll: station={fields.get('station')} -> {len(qdrant_docs)} 条")
            elif qdrant_filter:
                qdrant_docs = search_all_collections(query_vector, limit=limit, query_filter=qdrant_filter)
                if self.verbose:
                    print(f"[Neo4jRAG] Qdrant 表格过滤: {fields} -> {len(qdrant_docs)} 条")

            # 普通查询：不足 3 条时加入无过滤的回退结果
            if not use_scroll and len(qdrant_docs) < 3:
                fallback_docs = search_all_collections(query_vector, limit=limit)
                seen_keys = {
                    (str(doc.get('line', '')).strip(), str(doc.get('station', '')).strip(), str(doc.get('problem', '')).strip())
                    for doc in qdrant_docs
                }
                for doc in fallback_docs:
                    key = (
                        str(doc.get('line', '')).strip(),
                        str(doc.get('station', '')).strip(),
                        str(doc.get('problem', '')).strip(),
                    )
                    if key not in seen_keys:
                        qdrant_docs.append(doc)
                        seen_keys.add(key)

            station = fields.get('station', '') if fields else ''
            if station and not use_scroll:
                # scroll 已经按日期排好序，无需重新 boost
                qdrant_docs = _apply_station_boost(qdrant_docs, station)
            if not use_scroll:
                qdrant_docs = _apply_problem_boost(qdrant_docs, question)
                qdrant_docs = _group_docs_by_problem(qdrant_docs)

            qdrant_docs = self._filter_fault_like_docs(qdrant_docs, question)

            if self.verbose:
                print(f"[Neo4jRAG] Qdrant 表格查询: 获取 {len(qdrant_docs)} 条原始 CSV 行")
        except Exception as e:
            if self.verbose:
                print(f"[Neo4jRAG] Qdrant 表格查询失败: {e}")
            return []

        records = []
        for idx, doc in enumerate(qdrant_docs):
            records.append(
                qdrant_doc_to_frontend_record(
                    doc,
                    source="qdrant",
                    include_collection=False,
                    record_id=str(idx + 1),
                )
            )
        return records

    def _select_raw_records_for_answer(self, question: str, records: List[Dict], top_k: int = 8) -> List[Dict]:
        """回答专用轻量重排（不影响表格展示）。

        策略：
        1) 相对分差过滤：score >= best - 0.03
        2) 字段命中加权：line/station/problem/cause/action
        3) 去重并取 top_k
        """
        if not records:
            return []

        import math

        def _safe_score(x: Any) -> float:
            try:
                v = float(x)
                if math.isnan(v) or math.isinf(v):
                    return 0.0
                return v
            except Exception:
                return 0.0

        def _tokens(text: str) -> List[str]:
            text = (text or "").strip().lower()
            text = re.sub(r"[^\w\u4e00-\u9fff]+", " ", text)
            parts = [p for p in text.split() if len(p) >= 2]
            zh = re.sub(r"[^\u4e00-\u9fff]", "", text)
            for n in (4, 3, 2):
                for i in range(0, max(0, len(zh) - n + 1)):
                    parts.append(zh[i:i + n])
            seen, out = set(), []
            for p in parts:
                if p not in seen:
                    seen.add(p)
                    out.append(p)
            return out[:40]

        q_tokens = _tokens(question)
        best = max(_safe_score(r.get("score")) for r in records)
        min_keep = max(0.0, best - 0.03)

        rescored = []

        def _compute_combined_score(base_score: float, hit_ratio: float, question: str, doc: Dict) -> float:
            """自适应权重组合：
            - 默认更信任向量相似度
            - 若 query 明确包含工位或设备等结构化提示，提升文本命中权重
            """
            station_in_query = bool(re.search(r'[A-Z]{2,3}\d{1,3}-[A-Z]\d+', (question or "")))
            component_hint = any(k in (question or "").lower() for k in ["设备", "工位", "部件", "equipment", "component"])
            # 默认权重（偏向向量相似）
            base_w = 0.85
            hit_w = 0.15
            if station_in_query or component_hint:
                base_w = 0.75
                hit_w = 0.25
            return base_w * (base_score or 0.0) + hit_w * (hit_ratio or 0.0)

        for rec in records:
            base = _safe_score(rec.get("score"))
            if base < min_keep:
                continue

            text_blob = " ".join([
                str(rec.get("line", "")),
                str(rec.get("station", "")),
                str(rec.get("problem", "")),
                str(rec.get("cause", "")),
                str(rec.get("action", "")),
            ]).lower()

            hits = 0
            for t in q_tokens:
                if t in text_blob:
                    hits += 1
            hit_ratio = hits / max(1, len(q_tokens))

            final = _compute_combined_score(base, hit_ratio, question, rec)
            rec2 = dict(rec)
            rec2["_final_score"] = final
            rescored.append(rec2)

        if not rescored:
            rescored = [dict(r) for r in records[:top_k]]

        rescored.sort(key=lambda x: x.get("_final_score", 0.0), reverse=True)

        deduped = []
        seen_keys = set()
        for rec in rescored:
            key = (
                str(rec.get("line", "")).strip(),
                str(rec.get("station", "")).strip(),
                str(rec.get("problem", "")).strip(),
                str(rec.get("cause", "")).strip(),
                str(rec.get("action", "")).strip(),
            )
            if key in seen_keys:
                continue
            seen_keys.add(key)
            rec.pop("_final_score", None)
            deduped.append(rec)
            if len(deduped) >= top_k:
                break

        return deduped

    def _format_raw_records_for_context(self, records: List[Dict]) -> str:
        if not records:
            return "（无结果）"
        lines = []
        for idx, r in enumerate(records, 1):
            lines.append(f"\n原始记录 {idx}:")
            if r.get("line"):
                lines.append(f"  - line: {r.get('line')}")
            if r.get("station"):
                lines.append(f"  - station: {r.get('station')}")
            if r.get("problem"):
                lines.append(f"  - problem: {r.get('problem')}")
            if r.get("cause"):
                lines.append(f"  - cause: {r.get('cause')}")
            if r.get("action"):
                lines.append(f"  - action: {r.get('action')}")
            if r.get("date"):
                lines.append(f"  - date: {r.get('date')}")
        return "\n".join(lines)

    def _parse_problem_description(self, description: str) -> Dict[str, str]:
        """从 problem 描述中解析出原因和措施"""
        result = {'cause': '', 'action': ''}
        
        if not description:
            return result
        
        # 尝试解析格式：故障现象：xxx | 原因：xxx | 解决方案：xxx
        import re
        
        # 提取原因
        cause_match = re.search(r'原因[：:]\s*([^|]+)', description)
        if cause_match:
            result['cause'] = cause_match.group(1).strip()
        
        # 提取解决方案/措施
        action_match = re.search(r'解决方案[：:]\s*(.+?)(?:\||$)', description, re.DOTALL)
        if action_match:
            result['action'] = action_match.group(1).strip()
        
        return result
    
    def _extract_phenomenon(self, description: str) -> str:
        """从描述中提取故障现象部分"""
        if not description:
            return ''
        
        import re
        # 尝试匹配 "故障现象：xxx" 格式
        match = re.search(r'故障现象[：:]\s*([^|]+)', description)
        if match:
            return match.group(1).strip()
        
        # 如果没有标记，返回第一个 | 之前的内容或整个描述
        if '|' in description:
            return description.split('|')[0].strip()
        
        return description

    def _lookup_target_record(self, question: str) -> Optional[Dict[str, str]]:
        """用向量检索找到目标记录的站点和日期 — 适配 Version2 schema"""
        from app.retrievers.embedding import EmbeddingModel
        
        try:
            embedder = EmbeddingModel()
            query_vector = embedder.embed_query(question).tolist()
            
            cypher = """CALL db.index.vector.queryNodes('problem_embedding', 1, $query_vector) YIELD node AS p, score
OPTIONAL MATCH (comp:Component)-[:HAS_FAULT]->(p)
OPTIONAL MATCH (eq:Equipment)-[:HAS_PART]->(comp)
RETURN p.name AS problem, COALESCE(eq.name, '') AS station, score"""
            
            results = self._execute_cypher(cypher, {'query_vector': query_vector})
            
            if results and len(results) > 0:
                record = results[0]
                station = record.get('station')
                
                if self.verbose:
                    print(f"[Neo4jRAG] 目标记录: problem={record.get('problem','')[:30]}..., station={station}")
                
                return {'station': station, 'problem': record.get('problem')}
        except Exception as e:
            if self.verbose:
                print(f"[Neo4jRAG] 向量检索目标记录失败: {e}")
        return None

    def _generate_same_station_query(self, station: str) -> Dict[str, Any]:
        """生成查询同设备其他记录的 Cypher — 适配 Version2 schema"""
        cypher = """MATCH (eq:Equipment)-[:HAS_PART]->(comp:Component)-[:HAS_FAULT]->(p:Problem)
WHERE eq.name CONTAINS $station
OPTIONAL MATCH (p)-[:CAUSED_BY]->(c:Cause)
OPTIONAL MATCH (c)-[:SOLVED_BY]->(sol:Solution)
OPTIONAL MATCH (area:Area)-[:INCLUDE]->(eq)
WITH p, c, eq, area, COLLECT(DISTINCT sol.name) AS actions
RETURN p.name AS problem, c.name AS cause,
       CASE WHEN size(actions) > 0 THEN reduce(acc='', x IN actions | acc + CASE WHEN acc='' THEN '' ELSE '、' END + COALESCE(x,'')) ELSE NULL END AS action,
       COALESCE(area.name, '') AS line, eq.name AS station
LIMIT 10"""
        return {
            'cypher': cypher,
            'parameters': {'station': station},
            'reasoning': f'查询同设备记录: station={station}'
        }

    def _extract_component_problem_seed(self, question: str, records: List[Dict]) -> tuple[str, str, str]:
        """从问题和原始记录提取 station/component/problem 种子。"""
        problem_kws = [
            '故障报警', '检测报警', '报警', '故障', '异常', '无信号', '报错', '停机', '卡滞',
            '失败', '不良', '超差', '偏差', '过电流', '高温', '漏油', '漏气', '松动', '断裂', '超时'
        ]
        q = (question or '').strip()
        is_enum_query = any(kw in q for kw in _ENUM_QUERY_KWS)
        station, component, problem = '', '', ''

        fields = _extract_structured_fields(q)
        station = fields.get('station', '')
        components = fields.get('components') or []
        if components:
            component = components[0]

        for kw in problem_kws:
            if kw in q:
                problem = kw
                break

        if problem in _GENERIC_PROBLEM_KWS and is_enum_query:
            problem = ''
        if problem in _WEAK_PROBLEM_KWS and is_enum_query and station and not component:
            problem = ''

        if not component:
            left = q
            if station:
                left = left.replace(station, ' ')
            if problem:
                left = left.replace(problem, ' ')
            left = re.sub(r'(有哪些|有什么|哪些|列出|列举|出过|全部|所有|过往|曾经)', ' ', left)
            left = re.sub(r'(怎么办|怎么解决|怎么处理|怎么修|如何解决|如何处理|为什么|是什么|有哪些|有什么|列出|列举|出过|吗|呢|啊|呀|吧|嘛|的)\s*[?？!！。.,，]*$', '', left).strip()
            left = re.sub(r'\s+', ' ', left)
            if left and left not in {'有什么', '哪些', '问题', '故障', '有什么故障', '哪些问题'} and not any(kw in left for kw in _ENUM_QUERY_KWS):
                component = left

        top = records[0] if records else {}
        if not component:
            component = str(top.get('component', '')).strip()
        if not problem and not is_enum_query:
            problem = str(top.get('problem', '')).strip()
            for kw in problem_kws:
                if kw in problem:
                    problem = kw
                    break

        return station, component, problem

    def _search_graph_rows_aligned(self, station: str, component: str, problem: str, limit: int = 15) -> tuple[List[Dict], str]:
        """使用与 /graph/search 同口径的 station/component/problem 回退，返回结构化行结果。"""
        if not station and not component and not problem:
            return [], ''

        trial_pairs = _build_component_problem_trials(component, problem)
        matched_trace = ''
        rows: List[Dict] = []

        _db = os.getenv("NEO4J_DATABASE", "machining")
        with self.driver.session(database=_db) as session:
            for comp_item, prob_item in trial_pairs:
                where_parts, params = [], {"limit": max(1, limit)}

                if station:
                    where_parts.append("AND (e.name CONTAINS $station OR c.name CONTAINS $station)")
                    params['station'] = station

                if comp_item:
                    cv, cop = comp_item
                    frag, p = _build_graph_condition("component", cv, cop, "component")
                    where_parts.append(frag)
                    params.update(p)
                if prob_item:
                    pv, pop = prob_item
                    frag, p = _build_graph_condition("problem", pv, pop, "problem")
                    where_parts.append(frag)
                    params.update(p)

                if not where_parts:
                    continue

                where_clause = "\n".join(where_parts)
                cypher = f"""
MATCH path = (a:Area)-[r0:INCLUDE]->(e:Equipment)-[r1:HAS_PART]->(c:Component)
             -[r2:HAS_FAULT]->(p:Problem)-[r3:CAUSED_BY]->(ca:Cause)-[r4:SOLVED_BY]->(s:Solution)
WHERE true
{where_clause}
WITH path, a, e, c, p, ca, s,
    r1, r2, r3, r4,
    [r IN [r2, r3, r4] WHERE r.source_rows IS NOT NULL AND size(r.source_rows) > 0 | r.source_rows] AS sr_lists
WITH path, a, e, c, p, ca, s, r1, r2, r3, r4, sr_lists,
    CASE WHEN size(sr_lists) = 0 THEN NULL
         ELSE head([x IN sr_lists[0] WHERE ALL(lst IN sr_lists WHERE x IN lst)])
    END AS shared_row
WHERE (size(sr_lists) = 0 OR shared_row IS NOT NULL)
    AND (shared_row IS NULL OR shared_row IN coalesce(r1.row_ids, r1.source_rows, []))
RETURN a.name AS line, e.name AS station, c.name AS component,
       p.name AS problem, ca.name AS cause, s.name AS action
LIMIT toInteger($limit)
"""
                try:
                    result = list(session.run(cypher, **params))
                except Exception as exc:
                    if self.verbose:
                        print(f"[Neo4jRAG] 对齐图谱 trial failed: {exc}")
                    continue

                if result:
                    rows = [dict(r) for r in result]
                    parts_desc = []
                    if station:
                        parts_desc.append(f"station = '{station}'")
                    if comp_item:
                        parts_desc.append(f"component {comp_item[1]} '{comp_item[0]}'")
                    if prob_item:
                        parts_desc.append(f"problem {prob_item[1]} '{prob_item[0]}'")
                    matched_trace = ' + '.join(parts_desc)
                    break

        return rows, matched_trace

    def _execute_cypher(self, cypher: str, parameters: Dict = None) -> List[Dict]:
        _db = os.getenv("NEO4J_DATABASE", "machining")
        with self.driver.session(database=_db) as session:
            result = session.run(cypher, parameters or {})
            records = []
            for record in result:
                record_dict = {}
                for key in record.keys():
                    value = record[key]
                    record_dict[key] = dict(value._properties) if hasattr(value, '_properties') else value
                records.append(record_dict)
            return records

    def get_neighbors(self, node_id, limit: int = 50) -> Dict[str, Any]:
        """返回指定节点的邻居节点与关系，附带前端友好的显示字段（label/props）。
        支持两种 node_id 格式：
        - 纯数字 ID（旧版 Neo4j）
        - elementId 格式如 "4:xxx:123"（Neo4j 5.x+）
        """
        # 判断是否是 elementId 格式
        node_id_str = str(node_id)
        if ':' in node_id_str:
            # elementId 格式，使用 elementId() 查询
            cypher = """
            MATCH (n) WHERE elementId(n) = $id
            MATCH (n)-[r]-(m)
            RETURN elementId(n) AS source, elementId(m) AS target, labels(m) AS labels, m AS node, elementId(r) AS rel_id, type(r) AS rel_type, r AS rel_props
            LIMIT $limit
            """
            center_cypher = "MATCH (n) WHERE elementId(n)=$id RETURN elementId(n) AS id, labels(n) AS labels, n AS node"
            query_id = node_id_str
        else:
            # 纯数字 ID
            cypher = """
            MATCH (n) WHERE id(n) = $id
            MATCH (n)-[r]-(m)
            RETURN id(n) AS source, id(m) AS target, labels(m) AS labels, m AS node, elementId(r) AS rel_id, type(r) AS rel_type, r AS rel_props
            LIMIT $limit
            """
            center_cypher = "MATCH (n) WHERE id(n)=$id RETURN id(n) AS id, labels(n) AS labels, n AS node"
            query_id = int(node_id)

        nodes: Dict[str, Dict[str, Any]] = {}
        relations: List[Dict[str, Any]] = []

        _db = os.getenv("NEO4J_DATABASE", "machining")
        with self.driver.session(database=_db) as session:
            result = session.run(cypher, {"id": query_id, "limit": int(limit)})
            for rec in result:
                source = str(rec["source"])
                target = str(rec["target"])
                labels = rec["labels"]
                node_val = rec["node"]
                rel_type = rec["rel_type"]
                rel_id = rec["rel_id"]
                rel_props = rec["rel_props"]

                # node properties
                node_props = dict(node_val._properties) if hasattr(node_val, '_properties') else {}
                if target not in nodes:
                    nodes[target] = self._format_node(target, labels, node_props)

                # relation props
                rel_props_dict = dict(rel_props._properties) if hasattr(rel_props, '_properties') else {}
                relations.append({
                    "id": str(rel_id) if rel_id is not None else None,
                    "source": source,
                    "target": target,
                    "type": rel_type,
                    "props": rel_props_dict,
                })

        # also include the center node (if not already)
        try:
            with self.driver.session(database=_db) as session:
                center = session.run(center_cypher, {"id": query_id}).single()
                if center:
                    cid = str(center["id"])
                    if cid not in nodes:
                        c_labels = center["labels"]
                        c_node = center["node"]
                        c_props = dict(c_node._properties) if hasattr(c_node, '_properties') else {}
                        nodes[cid] = self._format_node(cid, c_labels, c_props)
        except Exception:
            pass

        return {"nodes": list(nodes.values()), "relations": relations}

    def _format_node(self, node_id, labels: List[str], props: Dict[str, Any]) -> Dict[str, Any]:
        """生成前端友好的节点表示，包含 `label`（显示名）和 `props`（关键属性）。
        node_id 可以是 int 或 str（elementId）"""
        # choose display name
        display = None
        for key in ("name", "record_id", "phenomenon", "title"):
            if props.get(key):
                display = props.get(key)
                break

        if not display:
            desc = props.get("description") or props.get("phenomenon") or ""
            
            # 对于 Problem 节点，只显示故障现象部分
            if "Problem" in labels and desc:
                # 格式可能是 "故障现象：xxx | 原因：xxx | 解决方案：xxx"
                if "故障现象：" in desc:
                    # 提取故障现象部分
                    start = desc.find("故障现象：") + len("故障现象：")
                    end = desc.find(" |", start) if " |" in desc[start:] else len(desc)
                    phenomenon = desc[start:end].strip()
                    display = phenomenon[:50] + "..." if len(phenomenon) > 50 else phenomenon
                else:
                    # 没有标准格式，取前50字符
                    display = (desc[:50] + "...") if len(desc) > 50 else desc
            else:
                display = (desc[:60] + "...") if len(desc) > 60 else desc

        # select a small set of props to return
        selected = {}
        for k in ("name", "uid", "record_id", "phenomenon", "description", "timestamp", "created_at"):
            if props.get(k) is not None:
                selected[k] = props.get(k)

        return {
            "id": str(node_id),  # 统一转为字符串，支持 elementId
            "labels": labels,
            "label": str(display),
            "props": selected,
        }

    def _summarize_results(self, question: str, results: List[Dict], raw_records: Optional[List[Dict]] = None) -> str:
        """让 LLM 总结查询结果"""
        import re
        # safety limits to avoid exceeding LLM context
        MAX_RAG_RECORDS = int(os.getenv('MAX_RAG_RECORDS', '5'))
        MAX_FIELD_CHARS = int(os.getenv('MAX_FIELD_CHARS', '1200'))

        def _truncate(text: Any, max_chars: int = MAX_FIELD_CHARS) -> Any:
            if text is None:
                return text
            try:
                s = str(text)
            except Exception:
                return text
            if len(s) <= max_chars:
                return s
            return s[:max_chars] + '...'
        
        # apply limits: keep only top-N records and truncate long fields
        truncated_results = []
        for rec in (results[:MAX_RAG_RECORDS] if results else []):
            t = {}
            for k, v in rec.items():
                # always keep score but truncate large text fields
                if k in ('problem', 'cause', 'action', 'plan', 'description'):
                    t[k] = _truncate(v)
                else:
                    t[k] = v
            truncated_results.append(t)

        graph_text = self._format_results(truncated_results)
        raw_records = raw_records or []
        raw_text = self._format_raw_records_for_context(raw_records)
        results_text = f"【图谱检索结果】\n{graph_text}\n\n【原始记录检索结果】\n{raw_text}"
        
        if self.verbose:
            print(f"\n[Neo4jRAG] ========== 图谱检索结果（已截断展示，top {MAX_RAG_RECORDS}） ==========")
            for idx, record in enumerate(truncated_results, 1):
                print(f"记录 {idx}: {record}")
            if raw_records:
                print(f"[Neo4jRAG] ---------- 回答使用的Qdrant原始记录（top {len(raw_records)}） ----------")
                for idx, record in enumerate(raw_records, 1):
                    print(f"原始 {idx}: {record}")
            print(f"[Neo4jRAG] ==========================================\n")
        
        # 检测用户问题的语言（改进版）
        def detect_language(text: str) -> str:
            """检测语言：只看是否有中文字符来判断"""
            # 移除数字和标点，只看实际文字内容
            cleaned = re.sub(r'[0-9\s\-\.\,\?\!\:\;\'\"\(\)\[\]\{\}\/\\]', '', text)
            chinese_chars = re.findall(r'[\u4e00-\u9fff]', cleaned)
            english_chars = re.findall(r'[a-zA-Z]', cleaned)
            
            # 如果有中文字符，认为是中文问题
            if len(chinese_chars) > 0:
                return "chinese"
            # 纯英文
            elif len(english_chars) > 0:
                return "english"
            else:
                return "chinese"  # 默认中文
        
        user_language = detect_language(question)
        if self.verbose:
            print(f"[Neo4jRAG] 检测到用户问题语言: {user_language}")
        
        # 根据语言选择提示模板
        if user_language == "english":
            # 纯英文问题使用英文模板
            prompt = f"""You are a production problem analyst. The user asked in English, you MUST answer in English.

**User Question:**
{question}

**Query Results (data is in Chinese, you need to translate/explain in English):**
{results_text}

**STRICT Rules:**
1. ANSWER IN ENGLISH ONLY - this is mandatory
2. The results above are in Chinese. READ them carefully and TRANSLATE/SUMMARIZE into English.
3. Extract: station names (like OP190, C14), problem descriptions, causes, actions, dates
4. Use graph results as primary evidence, and raw records as supporting evidence
5. Do NOT say "no information" if there are results - analyze them!
6. If you see Chinese text in results, translate the key information to English

**Answer in English:**"""
        else:
            # 中文问题使用配置的中文模板
            prompts_config = get_prompts()
            prompt_template = prompts_config.get("neo4j_rag_prompt", """你是一个生产问题分析助手。

【用户问题】：
{question}

【查询结果】：
{context}

【核心规则】：
1. 禁止编造日期
2. 禁止添加结果中没有的信息
3. 必须引用具体数据
4. 图谱检索结果优先，原始记录用于补充与佐证

【回答】：""")
            prompt = prompt_template.replace("{question}", question).replace("{context}", results_text)

        response = self.llm.invoke(prompt)
        return (response.content if hasattr(response, 'content') else str(response)).strip()

    def _format_results(self, results: List[Dict]) -> str:
        """格式化查询结果为可读文本"""
        if not results:
            return "（无结果）"
        
        # 过滤掉不需要展示给LLM的字段
        exclude_keys = {'score', 'distance', 'id'}
        
        lines = []
        for idx, record in enumerate(results, 1):
            lines.append(f"\n记录 {idx}:")
            for key, value in record.items():
                if key in exclude_keys:
                    continue  # 跳过评分等内部字段
                if value:  # 只显示非空值
                    # 处理 Neo4j DateTime 对象
                    if hasattr(value, 'year') and hasattr(value, 'month') and hasattr(value, 'day'):
                        value = f"{value.year}年{value.month}月{value.day}日"
                    lines.append(f"  - {key}: {value}")
        
        return "\n".join(lines)


_rag_tool_instance: Optional[Neo4jRAGTool] = None
_rag_tool_instance_key: Optional[str] = None

def get_neo4j_rag_tool(ollama_model: str | None = None, ollama_base_url: str | None = None) -> Neo4jRAGTool:
    """Create or return a Neo4jRAGTool.

    If `ollama_model` / `ollama_base_url` are provided they take precedence over environment values.
    """
    global _rag_tool_instance, _rag_tool_instance_key

    # 每次重新加载 .env，确保密码等配置是最新的
    load_dotenv(override=True)

    llm_type = (os.getenv("LLM_TYPE", "ollama") or "ollama").strip().lower()

    # Resolve model and base_url for ollama only
    model = ollama_model or os.getenv("OLLAMA_MODEL", "qwen3:8b")
    base_url = ollama_base_url or os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")

    cache_key = f"{llm_type}||{model}||{base_url}||{os.getenv('API_BASE_URL','')}||{os.getenv('GLM_MODEL','')}"

    # If an instance already exists and matches cache key, reuse it
    if _rag_tool_instance is not None and _rag_tool_instance_key == cache_key:
        return _rag_tool_instance

    # Otherwise, close previous and recreate
    if _rag_tool_instance is not None:
        try:
            _rag_tool_instance.close()
        except Exception:
            pass
        _rag_tool_instance = None

    if llm_type == "openai":
        from langchain_openai import ChatOpenAI

        api_base_url = (os.getenv("API_BASE_URL", "") or "").strip()
        api_key = (
            os.getenv("GLM_API_KEY", "")
            or os.getenv("OPENAI_API_KEY", "")
            or "any"
        )
        openai_model = (
            os.getenv("GLM_MODEL", "")
            or os.getenv("MODEL_NAME", "")
            or "gpt-3.5-turbo"
        )
        llm = ChatOpenAI(
            base_url=api_base_url or None,
            api_key=api_key,
            model=openai_model,
            temperature=0,
        )
    elif llm_type == "glm":
        from langchain_community.chat_models import ChatZhipuAI

        api_key = os.getenv("GLM_API_KEY", "") or os.getenv("ZHIPUAI_API_KEY", "")
        model = os.getenv("GLM_MODEL", "glm-4-flash")
        os.environ["ZHIPUAI_API_KEY"] = api_key
        llm = ChatZhipuAI(
            model=model,
            temperature=0,
        )
    else:
        from langchain_community.chat_models import ChatOllama

        llm = ChatOllama(
            model=model,
            base_url=base_url,
            temperature=0,  # 设为0确保一致性输出
            num_predict=2048,
            repeat_penalty=1.1,
        )

    schema = """
    节点: Area(name), Equipment(name), Component(name), Problem(name), Cause(name), Solution(name)
    关系: INCLUDE(Area->Equipment), HAS_PART(Equipment->Component), HAS_FAULT(Component->Problem), CAUSED_BY(Problem->Cause), SOLVED_BY(Cause->Solution)
    """

    _rag_tool_instance = Neo4jRAGTool(
        llm=llm,
        neo4j_uri=os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687"),
        neo4j_user=os.getenv("NEO4J_USERNAME", "neo4j"),
        neo4j_password=os.getenv("NEO4J_PASSWORD", "12345678"),
        schema_description=schema,
        verbose=True,
    )
    _rag_tool_instance_key = cache_key

    return _rag_tool_instance
