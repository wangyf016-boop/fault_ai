"""
FastAPI Server with LangGraph Routing
LangChain 生态标准结构
"""

from __future__ import annotations

import os
import re
import uuid
import csv
import hashlib
import threading
import unicodedata
import logging
from typing import Dict, List, Optional, Literal, TypedDict, Annotated, Any
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse

# 关闭 LangChain 调试日志（减少控制台输出）
import langchain
import json
import asyncio
langchain.debug = False
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from langchain_community.chat_models import ChatOllama
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages

# 内部模块导入
from app.retrievers.embedding import EmbeddingModel
from app.retrievers.qdrant_store import QdrantVectorStore
from app.chains.followup_detector import FollowUpDetector
from app.chains.route_policy import build_route_plan
from app.chains.search_records import qdrant_docs_to_frontend_records
from app.tools.neo4j_tool import get_neo4j_rag_tool
from app.db.database import get_database
from app.ocr.ocr_router import router as ocr_router
from app.dataset.dataset_router import router as dataset_router
from app.settings.settings_router import router as settings_router, get_prompts
from app.diagnosis.diagnosis_engine import (
    query_kg_subgraph,
    query_original_records,
    build_flowchart_data,
)
from app.logger_config import setup_logging, request_id_var

load_dotenv()
setup_logging()
logger = logging.getLogger(__name__)

# ===================== FastAPI App ===================== #

app = FastAPI(title="Agentic RAG API with LangGraph Routing", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=3600,
)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    incoming_request_id = request.headers.get("X-Request-ID")
    request_id = incoming_request_id or str(uuid.uuid4())
    token = request_id_var.set(request_id)
    try:
        response = await call_next(request)
    finally:
        request_id_var.reset(token)
    response.headers["X-Request-ID"] = request_id
    return response

# 注册 OCR 路由
app.include_router(ocr_router)

# 注册数据集嵌入路由
app.include_router(dataset_router)

# 注册设置路由
app.include_router(settings_router)

# ===================== Global Instances ===================== #

db = get_database()
embedder = EmbeddingModel()
followup_detector = FollowUpDetector()

# Qdrant 搜索 / 字段提取 / Filter 构建（共享模块，消除与 neo4j_tool 的循环依赖）
from app.retrievers.qdrant_search import (
    invalidate_qdrant_cache,
    get_all_qdrant_collections,
    get_target_qdrant_collections,
    _get_qdrant_store,
    _extract_station_from_query,
    _get_station_boost_value,
    _get_station_candidate_limit,
    _apply_station_boost,
    _extract_structured_fields,
    _build_qdrant_filter,
    search_all_collections,
    scroll_all_collections,
)

# Graph 查询辅助（共享模块，消除与 neo4j_tool 的循环依赖）
from app.tools.graph_query_helpers import (
    _GRAPH_COL_MAP,
    _graph_field_variants,
    _build_graph_condition,
    _build_component_problem_trials,
)


def _format_date_val(val) -> str:
    """统一格式化 date 字段为 YYYY-MM-DD 字符串或空串"""
    if not val:
        return ''
    # Neo4j DateTime-like object
    try:
        if hasattr(val, 'year') and hasattr(val, 'month') and hasattr(val, 'day'):
            return f"{val.year}-{str(val.month).zfill(2)}-{str(val.day).zfill(2)}"
    except Exception:
        pass
    # 如果已经是字符串，尝试取前10字符（YYYY-MM-DD）
    if isinstance(val, str):
        return val[:10]
    # 其它类型，转成字符串
    return str(val)


_global_neo4j_tool = None
_global_neo4j_tool_model = None

def get_global_neo4j_tool():
    """Return a global Neo4j tool. If the configured Ollama model/base_url changed
    in the .env, recreate the tool with the new settings.
    """
    global _global_neo4j_tool, _global_neo4j_tool_model

    # reload .env to pick up runtime changes from settings API
    try:
        load_dotenv(override=True)
    except Exception:
        load_dotenv()

    model = os.getenv("OLLAMA_MODEL", "qwen3:8b")
    base_url = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")

    # If no instance yet or the model/base_url changed, recreate
    current_key = f"{model}||{base_url}"
    if _global_neo4j_tool is None or _global_neo4j_tool_model != current_key:
        # close previous if exists
        try:
            if _global_neo4j_tool is not None:
                _global_neo4j_tool.close()
        except Exception:
            pass

        # create new instance with chosen model/base_url
        _global_neo4j_tool = get_neo4j_rag_tool(ollama_model=model, ollama_base_url=base_url)
        _global_neo4j_tool_model = current_key

    return _global_neo4j_tool

def get_llm():
    """获取 LLM 实例，支持动态重载配置
    
    根据 LLM_TYPE 环境变量选择：
    - 'openai': 使用 OpenAI 兼容 API（如本地 LM Studio、vLLM 等）
    - 'ollama': 使用 Ollama 原生 API
    """
    load_dotenv(override=True)
    llm_type = os.getenv("LLM_TYPE", "ollama").lower().strip().strip("'\"")
    
    if llm_type == "openai":
        # OpenAI 兼容模式（支持 LM Studio、vLLM、LocalAI 等）
        base_url = os.getenv("API_BASE_URL", "http://127.0.0.1:1235").strip().strip("'\"")
        model_name = os.getenv("MODEL_NAME") or os.getenv("GLM_MODEL", "gpt-3.5-turbo")
        model_name = model_name.strip().strip("'\"")
        api_key = os.getenv("GLM_API_KEY") or os.getenv("OPENAI_API_KEY", "sk-no-key-required")
        api_key = api_key.strip().strip("'\"") if api_key else "sk-no-key-required"
        
        print(f"[LLM] 使用 OpenAI 兼容模式: base_url={base_url}, model={model_name}")
        return ChatOpenAI(
            model=model_name,
            base_url=base_url,
            api_key=api_key,
            temperature=0,
            max_tokens=2048,
        )
    else:
        # Ollama 原生模式
        model = os.getenv("OLLAMA_MODEL", "qwen3:8b").strip().strip("'\"")
        base_url = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").strip().strip("'\"")
        
        print(f"[LLM] 使用 Ollama 模式: base_url={base_url}, model={model}")
        return ChatOllama(
            model=model,
            base_url=base_url,
            temperature=0,
            num_predict=2048,
            repeat_penalty=1.1,
            top_p=0.9,
        )

# 默认实例
llm = get_llm()

# ===================== LangGraph State ===================== #

class GraphState(TypedDict):
    messages: Annotated[list, add_messages]
    query: str
    route: str
    search_strategy: str
    first_search_strategy: str
    context: str
    final_answer: str
    is_followup: bool
    top_k: int
    qdrant_records: List[Dict]  # 存储 Qdrant 检索的原始记录
    retry_count: int  # 重试计数器
    retry_pending: bool
    first_route: str  # 记录首次路由，避免重复
    show_graph: bool  # 是否显示知识图谱
    show_table: bool  # 是否显示表格
    diagnosis_kg: Dict       # 诊断-知识图谱数据
    diagnosis_records: List[Dict]  # 诊断-原始记录
    diagnosis_flowchart: List[Dict]  # 诊断-排查流程
    diagnosis_flow_plan: Dict  # 诊断-LLM结构化流程计划
    diagnosis_kg_summary: str
    diagnosis_records_summary: str
    diagnosis_flowchart_summary: str
    followup_records: List[Dict]  # 前端或历史消息传入的追问关联记录

# ===================== Helper Functions ===================== #

def build_context_snippets(results: List[Dict]) -> str:
    """构建清晰的上下文信息"""
    if not results:
        return "未检索到任何相关记录。"
    
    lines: List[str] = []
    for idx, doc in enumerate(results, start=1):
        lines.append(f"【记录 {idx}】")
        lines.append(f"  产线: {doc.get('line', 'N/A')}")
        lines.append(f"  工位: {doc.get('station', 'N/A')}")
        lines.append(f"  日期: {doc.get('date', 'N/A')}")
        lines.append(f"  问题描述: {doc.get('problem_description') or doc.get('problem', 'N/A')}")
        lines.append(f"  原因分析: {doc.get('cause_analysis') or doc.get('cause', 'N/A')}")
        lines.append(f"  应对措施: {doc.get('containment_action') or doc.get('action', 'N/A')}")
        lines.append(f"  行动计划: {doc.get('action_plan') or doc.get('plan', 'N/A')}")
        score_val = doc.get('score')
        lines.append(f"  相似度: {score_val:.2%}" if isinstance(score_val, (int, float)) else "  相似度: N/A")
        lines.append("")  # 空行分隔
    
    return "\n".join(lines)


def _extract_recent_records_from_messages(messages: List[Dict], limit: int = 50) -> List[Dict]:
    """从最近多条带 records 的助手消息中提取追问可用记录。"""
    if not messages:
        return []

    deduped: List[Dict] = []
    seen = set()

    for msg in reversed(messages):
        raw_records = msg.get("qdrant_records")
        if not raw_records:
            continue
        try:
            records = json.loads(raw_records) if isinstance(raw_records, str) else raw_records
        except Exception:
            continue

        if not isinstance(records, list):
            continue

        for idx, record in enumerate(records):
            if not isinstance(record, dict):
                continue
            key = (
                str(record.get("line", "")),
                str(record.get("station", "")),
                str(record.get("problem", "")),
                str(record.get("cause", "")),
                str(record.get("action", "")),
                str(record.get("date", "")),
                idx,
            )
            if key in seen:
                continue
            seen.add(key)
            deduped.append(record)
            if len(deduped) >= limit:
                return deduped

    return deduped


def _resolve_followup_records(payload_records: Optional[List[Dict]], messages: List[Dict]) -> List[Dict]:
    """聚合历史多轮结果；前端传入记录作为补充，尽量给追问更多可用记录。"""
    payload_records = payload_records or []
    history_records = _extract_recent_records_from_messages(messages, limit=120)

    merged: List[Dict] = []
    seen = set()
    for source in (history_records, payload_records):
        for idx, record in enumerate(source):
            if not isinstance(record, dict):
                continue
            key = (
                str(record.get("line", "")),
                str(record.get("station", "")),
                str(record.get("problem_description") or record.get("problem", "")),
                str(record.get("cause_analysis") or record.get("cause", "")),
                str(record.get("containment_action") or record.get("action", "")),
                str(record.get("date", "")),
                idx if source is payload_records else "h",
            )
            if key in seen:
                continue
            seen.add(key)
            merged.append(record)
            if len(merged) >= 120:
                return merged
    return merged


def _detect_user_language(text: str) -> str:
    chinese_chars = re.findall(r'[\u4e00-\u9fff\u3000-\u303f]', text or "")
    english_chars = re.findall(r'[a-zA-Z]', text or "")
    if len(english_chars) > len(chinese_chars):
        return "english"
    return "chinese"


def _record_problem(record: Dict) -> str:
    return str(record.get('problem_description') or record.get('problem') or '').strip()


def _record_cause(record: Dict) -> str:
    return str(record.get('cause_analysis') or record.get('cause') or '').strip()


def _record_action(record: Dict) -> str:
    return str(record.get('containment_action') or record.get('action') or '').strip()


def _record_plan(record: Dict) -> str:
    return str(record.get('action_plan') or record.get('plan') or '').strip()


def _parse_record_date(record: Dict) -> str:
    return str(record.get('date') or '').strip()


def _extract_series_tokens(query: str) -> List[str]:
    upper = (query or '').upper()
    tokens: List[str] = []

    for m in re.finditer(r'([A-Z]{1,5}\d*)(?:系列)', upper):
        token = m.group(1)
        if token and token not in tokens:
            tokens.append(token)

    for m in re.finditer(r'(?<![A-Z0-9-])([A-Z]{1,5}\d+)(?![-A-Z0-9])', upper):
        token = m.group(1)
        if token.startswith('OP'):
            continue
        if token not in tokens:
            tokens.append(token)

    return tokens


def _filter_followup_records(query: str, records: List[Dict]) -> tuple[List[Dict], List[str]]:
    filtered = list(records)
    applied_filters: List[str] = []
    query_upper = (query or '').upper()

    station = _extract_station_from_query(query)
    if station:
        station_upper = station.upper()
        matched = [r for r in filtered if str(r.get('station', '')).upper() == station_upper]
        if matched:
            filtered = matched
            applied_filters.append(f"工位={station_upper}")

    structured_fields = _extract_structured_fields(query)
    line = structured_fields.get('line')
    if line:
        matched = [r for r in filtered if str(r.get('line', '')).upper() == str(line).upper()]
        if matched:
            filtered = matched
            applied_filters.append(f"产线={str(line).upper()}")

    for token in _extract_series_tokens(query):
        token_upper = token.upper()
        matched = []
        for r in filtered:
            haystacks = [
                str(r.get('station', '')).upper(),
                str(r.get('line', '')).upper(),
                _record_problem(r).upper(),
                _record_cause(r).upper(),
                _record_action(r).upper(),
                _record_plan(r).upper(),
            ]
            if any(token_upper in text for text in haystacks if text):
                matched.append(r)
        if matched:
            filtered = matched
            applied_filters.append(f"关键词={token_upper}")

    return filtered, applied_filters


def _format_group_lines(groups: List[tuple[str, List[Dict]]], field_name: str, max_items: int = 12) -> List[str]:
    lines: List[str] = []
    for idx, (name, rows) in enumerate(groups[:max_items], 1):
        stations = [s for s in sorted({str(r.get('station', '')).strip() for r in rows if str(r.get('station', '')).strip()}) if s]
        latest_date = max((_parse_record_date(r) for r in rows if _parse_record_date(r)), default='')
        extra_parts = [f"出现{len(rows)}次"]
        if stations:
            extra_parts.append(f"工位：{'、'.join(stations[:3])}{' 等' if len(stations) > 3 else ''}")
        if latest_date:
            extra_parts.append(f"最近日期：{latest_date}")
        lines.append(f"{idx}. {name}（{'；'.join(extra_parts)}）")
    if len(groups) > max_items:
        lines.append(f"另有 {len(groups) - max_items} 项未展开。")
    return lines


def _answer_followup_from_records(query: str, records: List[Dict]) -> Optional[str]:
    if not records:
        return None

    query = (query or '').strip()
    if not query:
        return None

    query_lower = query.lower()
    structured_keywords = ["有哪些", "列出", "汇总", "总结", "统计", "多少", "几条", "哪些", "分别", "问题", "原因", "措施", "处理", "处置", "工位", "站点"]
    if not any(kw in query for kw in structured_keywords) and not any(kw in query_lower for kw in ["list", "count", "summary", "summarize", "issue", "cause", "action"]):
        return None

    filtered, applied_filters = _filter_followup_records(query, records)
    user_language = _detect_user_language(query)
    if not filtered:
        return "基于当前结果未找到匹配记录。" if user_language != "english" else "No matching records were found in the current results."

    ask_count = any(kw in query for kw in ["多少", "几条", "数量", "统计"]) or any(kw in query_lower for kw in ["count", "how many"])
    ask_problem = ("问题" in query) or any(kw in query_lower for kw in ["issue", "problem"])
    ask_cause = ("原因" in query)
    ask_action = any(kw in query for kw in ["措施", "处理", "处置", "对策"]) or any(kw in query_lower for kw in ["action", "measure", "solution", "handle"])
    ask_station = any(kw in query for kw in ["工位", "站点", "站别"]) or any(kw in query_lower for kw in ["station"])

    if ask_station:
        values = sorted({str(r.get('station', '')).strip() for r in filtered if str(r.get('station', '')).strip()})
        if ask_count and not (ask_problem or ask_cause or ask_action):
            prefix = f"按{'、'.join(applied_filters)}过滤后，" if applied_filters else ""
            return f"{prefix}共涉及 {len(values)} 个工位：{'、'.join(values)}。"
        prefix = f"按{'、'.join(applied_filters)}过滤后，涉及的工位有 {len(values)} 个：" if applied_filters else f"涉及的工位有 {len(values)} 个："
        return prefix + "、".join(values) + "。"

    if ask_cause:
        key_fn = _record_cause
        field_name = "原因"
    elif ask_action:
        key_fn = _record_action
        field_name = "措施"
    else:
        key_fn = _record_problem
        field_name = "问题"

    grouped: Dict[str, List[Dict]] = {}
    for record in filtered:
        key = key_fn(record) or f"未填写{field_name}"
        grouped.setdefault(key, []).append(record)

    groups = sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0]))

    if ask_count and not any([ask_problem, ask_cause, ask_action]):
        prefix = f"按{'、'.join(applied_filters)}过滤后，" if applied_filters else ""
        return f"{prefix}共找到 {len(filtered)} 条记录。"

    prefix = f"按{'、'.join(applied_filters)}过滤后，" if applied_filters else "基于当前结果，"
    if ask_count:
        summary = f"共找到 {len(filtered)} 条记录，去重后涉及 {len(groups)} 个{field_name}："
    else:
        summary = f"共归纳出 {len(groups)} 个{field_name}："
    lines = _format_group_lines(groups, field_name)
    return prefix + summary + "\n" + "\n".join(lines)


def _normalize_flow_action_text(text: str) -> str:
    """将流程文本归一化为可执行动作句。"""
    t = str(text or "").strip()
    if not t:
        return ""

    # 已是动作句
    if re.match(r"^(检查|确认|核对|排查|测试|复位|重启|更换|清理|紧固|调整|恢复|观察|记录|验证|执行)", t):
        return t

    # 原因/现象类短语转换为动作句
    if re.search(r"(故障|异常|报警|不良|损坏|卡滞|松动|接触不良|未找到原因|无信号|停机)", t):
        return f"检查并处理：{t}"

    return f"执行：{t}"




def _compact_core_text(text: str, max_len: int = 18) -> str:
    """压缩为核心动作短句（用于流程图展示）。"""
    t = str(text or "").strip()
    if not t:
        return ""
    t = re.sub(r"^(执行|处理|操作)[：:]\s*", "", t)
    t = re.sub(r"^检查并处理[：:]\s*", "检查", t)
    t = re.sub(r"\s+", " ", t).strip(" ；;，,。")
    if len(t) > max_len:
        t = t[:max_len]
    return t




def _extract_problem_core_from_query(query: str) -> str:
    """从用户问题提取核心现象短语（后端兜底）。"""
    q = str(query or "").strip()
    if not q:
        return ""
    t = re.sub(r"^[\s，。！？,.!?]*(请问|请教|帮我|麻烦|想问下|我想问下|我想问|咨询一下|咨询)\s*", "", q, flags=re.I)
    t = re.sub(r"^(关于|针对)\s*", "", t, flags=re.I)
    t = re.sub(r"(怎么办|咋办|怎么处理|如何处理|怎么解决|如何解决|怎么排查|如何排查|怎么修|如何修|是什么原因|原因是什么|为什么|为啥|怎么回事|行吗|可以吗|呢|吗|\?|？)+\s*$", "", t, flags=re.I)
    t = re.sub(r"[，。！？,.!?]+$", "", t).strip()
    return t[:24]




def _parse_record_date_safe(date_text: str) -> Optional[datetime]:
    t = str(date_text or "").strip()
    if not t:
        return None
    fmts = ["%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y-%m-%d %H:%M:%S"]
    for f in fmts:
        try:
            return datetime.strptime(t[:19], f)
        except Exception:
            continue
    return None


def _rerank_records_for_flow(records: List[Dict], station_hint: str = "", top_k: int = 6) -> List[Dict]:
    """方案B：对召回记录做轻量重排，降低噪声后再交给 LLM。"""
    station_up = str(station_hint or "").upper().strip()
    now = datetime.now()

    scored = []
    for r in records:
        score_percent = r.get("score_percent")
        if score_percent is None:
            try:
                score_percent = float(r.get("score", 0) or 0) * 100
            except Exception:
                score_percent = 0

        # 归一到 0~1
        sim = max(0.0, min(1.0, float(score_percent or 0) / 100.0))

        station = str(r.get("station", "")).upper().strip()
        station_boost = 1.0 if (station_up and station == station_up) else (0.25 if station_up else 0.0)

        cause = str(r.get("cause", "")).strip()
        action = str(r.get("action", "")).strip()
        problem = str(r.get("problem", "")).strip()
        completeness = (0.4 if problem else 0.0) + (0.3 if cause else 0.0) + (0.3 if action else 0.0)

        d = _parse_record_date_safe(r.get("date", ""))
        if d:
            days = max(0, (now - d).days)
            recency = max(0.0, 1.0 - min(days, 3650) / 3650.0)
        else:
            recency = 0.2

        final = 0.55 * sim + 0.20 * station_boost + 0.15 * recency + 0.10 * completeness
        scored.append((final, r))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [r for _, r in scored[:max(1, top_k)]]




def _build_flow_plan_with_llm(query: str, flowchart_records: List[Dict], flowchart_summary: str = "", station_hint: str = "") -> Dict:
    """方案B：重排 topK + LLM 直接输出 DSL + 兼容字段回填。"""
    plan_default = {
        "likely_cause": "",
        "steps": [],
        "verify": "处理后连续复测通过",
        "branch_mode": "single",
        "cause_branches": [],
        "diagram_spec": {
            "version": "dsl_v1",
            "problem": "当前问题",
            "likely_cause": "",
            "mode": "single",
            "steps": [],
            "branches": [],
            "verify": "处理后连续复测通过",
        },
    }

    if not flowchart_records:
        return plan_default

    # 方案B：先重排后压缩
    source_records = _rerank_records_for_flow(flowchart_records, station_hint=station_hint, top_k=6)

    evidence_lines = []
    for idx, r in enumerate(source_records, 1):
        evidence_lines.append(
            f"[{idx}] 工位:{r.get('station','')} 问题:{r.get('problem','')} 原因:{r.get('cause','')} 措施:{r.get('action','')} 日期:{r.get('date','')} 相似度:{r.get('score_percent', r.get('score', ''))}"
        )
    evidence_text = "\n".join(evidence_lines)

    prompt = (
        "根据下方故障记录，生成排查流程 DSL（JSON）。\n"
        "只输出纯 JSON，不要解释。\n"
        "不得编造记录中不存在的设备/动作。\n\n"
        "JSON schema:\n"
        "{\n"
        "  \"problem\": \"字符串(6~20字)\",\n"
        "  \"mode\": \"single|by_cause\",\n"
        "  \"likely_cause\": \"字符串(6~16字)\",\n"
        "  \"steps\": [{\"check\":\"动作短句(6~18字)\",\"action\":\"动作短句(可空)\"}],\n"
        "  \"branches\": [{\"cause\":\"原因短句(6~16字)\",\"steps\":[\"动作短句\",\"动作短句\"]}],\n"
        "  \"verify\": \"动作短句(6~20字)\"\n"
        "}\n\n"
        "规则:\n"
        "- 优先综合 top 记录做整体结论，不要逐条复述\n"
        "- 若原因分歧明显用 by_cause，否则 single\n"
        "- single: steps 3~4 条；by_cause: branches 2~4 个、每分支 1~3 步\n"
        "- 去掉编号/解释/客套词，只保留核心动作\n\n"
        f"用户问题:\n{query}\n\n"
        f"故障记录:\n{evidence_text}"
    )

    try:
        current_llm = get_llm()
        response = current_llm.invoke(prompt)
        content = response.content if hasattr(response, "content") else str(response)

        m = re.search(r"\{[\s\S]*\}", content)
        raw = m.group(0) if m else content
        dsl = json.loads(raw)

        mode = str(dsl.get("mode", "single")).strip().lower()
        mode = mode if mode in {"single", "by_cause"} else "single"

        problem = _compact_core_text(dsl.get("problem", ""), max_len=20) or _extract_problem_core_from_query(query) or "当前问题"
        likely_cause = _compact_core_text(dsl.get("likely_cause", ""), max_len=16)
        verify = _compact_core_text(dsl.get("verify", "处理后连续复测通过"), max_len=20) or "处理后连续复测通过"

        # 规范 single steps
        norm_steps = []
        if isinstance(dsl.get("steps"), list):
            for it in dsl.get("steps", [])[:4]:
                if isinstance(it, str):
                    check = _compact_core_text(it, max_len=18)
                    if check:
                        norm_steps.append({"check": check, "action": ""})
                    continue
                if not isinstance(it, dict):
                    continue
                check = _compact_core_text(it.get("check", ""), max_len=18)
                action = _compact_core_text(it.get("action", ""), max_len=18)
                if check:
                    norm_steps.append({"check": check, "action": action})

        # 规范 branches
        norm_branches = []
        if isinstance(dsl.get("branches"), list):
            for b in dsl.get("branches", [])[:4]:
                if not isinstance(b, dict):
                    continue
                cause = _compact_core_text(b.get("cause", ""), max_len=16)
                b_steps = b.get("steps", []) if isinstance(b.get("steps", []), list) else []
                b_steps = [_compact_core_text(x, max_len=18) for x in b_steps]
                b_steps = [x for x in b_steps if x][:3]
                if cause or b_steps:
                    norm_branches.append({
                        "cause": cause or "原因分支",
                        "steps": b_steps or ["执行对应处置"],
                        "confidence": 0.0,
                    })

        if mode == "single" and not norm_steps and norm_branches:
            norm_steps = [{"check": s, "action": ""} for s in norm_branches[0].get("steps", [])[:3]]
        if mode == "by_cause" and len(norm_branches) < 2:
            mode = "single"

        diagram_spec = {
            "version": "dsl_v1",
            "problem": problem,
            "likely_cause": likely_cause,
            "mode": mode,
            "steps": norm_steps,
            "branches": norm_branches,
            "verify": verify,
        }

        # 回填兼容字段（给旧前端/调试）
        compat_steps = [{"check": s.get("check", ""), "yes_action": s.get("action", ""), "no_action": ""} for s in norm_steps]
        compat_branches = [{"cause": b.get("cause", ""), "steps": b.get("steps", []), "count": 1, "confidence": b.get("confidence", 0.0)} for b in norm_branches]

        return {
            "likely_cause": likely_cause,
            "steps": compat_steps,
            "verify": verify,
            "branch_mode": mode,
            "cause_branches": compat_branches,
            "diagram_spec": diagram_spec,
        }
    except Exception as e:
        print(f"[FlowPlan-B] LLM/解析失败，回退最小DSL: {e}")
        fallback_problem = _extract_problem_core_from_query(query) or str((source_records[0] or {}).get("problem", "当前问题"))
        fallback = dict(plan_default)
        fallback["diagram_spec"] = {
            "version": "dsl_v1",
            "problem": _compact_core_text(fallback_problem, max_len=20) or "当前问题",
            "likely_cause": "",
            "mode": "single",
            "steps": [
                {"check": "确认故障复现条件", "action": ""},
                {"check": "检查关键部件状态", "action": "执行对应处置"},
                {"check": "复位并连续复测", "action": ""},
            ],
            "branches": [],
            "verify": "处理后连续复测通过",
        }
        fallback["steps"] = [{"check": s["check"], "yes_action": s["action"], "no_action": ""} for s in fallback["diagram_spec"]["steps"]]
        return fallback


def route_query(state: GraphState) -> GraphState:
    query = state["query"]
    is_followup = state.get("is_followup", False)

    def _log_route_decision(reason: str) -> None:
        logger.info(
            "[RouteDecision] route=%s reason=%s top_k=%s followup=%s query=%s",
            state.get("route", ""),
            reason,
            state.get("top_k", ""),
            is_followup,
            query[:120],
        )
    
    logger.info("[RouteInput] followup=%s query=%s", is_followup, query[:120])

    plan = build_route_plan(state, build_context_snippets=build_context_snippets)
    state["route"] = plan.route
    if plan.top_k is not None:
        state["top_k"] = plan.top_k
    if plan.search_strategy is not None:
        state["search_strategy"] = plan.search_strategy
        if not state.get("first_search_strategy"):
            state["first_search_strategy"] = plan.search_strategy
    if plan.qdrant_records is not None:
        state["qdrant_records"] = plan.qdrant_records
    if plan.context is not None:
        state["context"] = plan.context
    if plan.show_graph is not None:
        state["show_graph"] = bool(plan.show_graph)
    if plan.show_table is not None:
        state["show_table"] = bool(plan.show_table)

    _log_route_decision(plan.reason)
    return state


def _check_need_new_query(query: str, history: str) -> bool:
    """判断追问是否需要新查询，基于规则"""
    import re
    query_lower = query.lower()
    
    # 需要新查询的关键词
    new_query_keywords = ["其他", "还有", "别的", "更多", "同一天", "当日", "当天", 
                         "什么时候", "时间", "日期", "几号", "哪天", "多久",
                         "other", "more", "another", "else", "when", "time", "date", "how long"]
    
    # 如果问的是"其他/还有"类问题，检查历史中是否有多条记录
    if any(kw in query for kw in new_query_keywords) or any(kw in query_lower for kw in new_query_keywords):
        # 检查历史中是否有多条记录（通过记录编号判断）
        record_count = len(re.findall(r'\[\d+\]|记录\s*\d+|problem_id|record', history, re.IGNORECASE))
        if record_count <= 1:
            return True  # 历史只有1条或没有，需要查询更多
    
    # 如果问的是具体细节，检查历史中是否有相关信息
    detail_keywords = ["原因", "措施", "解决", "计划", "分析", "时间", "日期",
                       "cause", "reason", "solution", "action", "plan", "analysis", "time", "date"]
    if any(kw in query for kw in detail_keywords) or any(kw in query_lower for kw in detail_keywords):
        if not any(kw in history for kw in detail_keywords) and not any(kw in history.lower() for kw in detail_keywords):
            return True  # 历史中没有相关细节，需要查询
    
    return False  # 默认可以从历史回答


#LLM的追问判断实现
# 
# def _check_need_new_query_with_llm(query: str, history: str) -> bool:
#     """
#     用 LLM 判断历史是否足够回答追问
#     
#     优点：语义理解更准确，能判断历史内容与追问的相关性
#     缺点：增加一次 LLM 调用，延迟 +500ms~1s
#     
#     使用方法：在 route_query 函数中将 _check_need_new_query 替换为此函数
#     """
#     
#     prompt = f"""你是一个判断助手。用户正在追问，请判断对话历史中的信息是否足够回答这个追问。
# 
# 【用户追问】：
# {query}
# 
# 【对话历史】：
# {history[-2000:] if len(history) > 2000 else history}
# 
# 【判断标准】：
# 1. 历史中是否有与追问直接相关的具体数据（如工位、故障描述、原因、措施等）
# 2. 如果用户问"还有其他/更多"，历史中是否已经列出了多条相关记录
# 3. 如果用户问具体细节（原因、措施、解决方案），历史中是否有足够的细节信息
# 4. 如果用户问的是不同工位/时间的问题，历史中是否有对应数据
# 
# 【回答格式】：
# 只回答 "yes" 或 "no"
# - yes：历史信息不足，需要重新查询数据库
# - no：历史信息足够，可以直接回答
# 
# 你的判断："""
# 
#     try:
#         response = llm.invoke(prompt)
#         answer = response.content.strip().lower()
#         need_query = "yes" in answer
#         print(f"否需要新查询: {need_query} (原始回答: {answer})")
#         return need_query
#     except Exception as e:
#         print(f"调用失败: {e}，回退到规则判断")
#         return _check_need_new_query(query, history)  # 失败时回退到规则版本


def query_neo4j(state: GraphState) -> GraphState:
    query = state["query"]
    messages = state.get("messages", [])
    is_followup = state.get("is_followup", False)

    logger.info("[RouteExec] route=neo4j followup=%s top_k=%s query=%s", is_followup, state.get("top_k", ""), query[:120])
    
    chat_history = []
    for msg in messages[-6:]:
        if hasattr(msg, 'content'):
            role = "user" if isinstance(msg, HumanMessage) else "assistant"
            chat_history.append({"role": role, "content": msg.content})
    
    try:
        # 支持请求级别的 Ollama 模型切换：如果 state 中包含 ollama_model/ollama_base_url，
        # 使用这些值创建（或重建）Neo4j RAG 工具，仅对本次请求生效。
        ollama_model = state.get("ollama_model")
        ollama_base_url = state.get("ollama_base_url")

        if ollama_model or ollama_base_url:
            tool = get_neo4j_rag_tool(ollama_model=ollama_model, ollama_base_url=ollama_base_url)
        else:
            tool = get_global_neo4j_tool()

        # 使用 query_with_records 获取答案和记录
        result = tool.query_with_records(query, chat_history=chat_history, is_followup=is_followup)
        state["final_answer"] = result.get('answer', '')
        state["qdrant_records"] = result.get('records', [])
        state["context"] = result.get('answer', '')  # 同时存到 context 供验证节点检查
        print(f"[Neo4j] 查询成功，获取到 {len(state['qdrant_records'])} 条记录")
    except Exception as e:
        print(f"[Neo4j] 查询失败: {e}")
        state["final_answer"] = f"知识图谱查询出错: {str(e)}"
        state["context"] = ""
        state["qdrant_records"] = []
    return state


def _extract_component_problem_seed(query: str, docs: List[Dict]) -> tuple[str, str]:
    """从用户问题 + Qdrant 首条记录提取 component/problem 种子。"""
    problem_kws = [
        "故障报警", "检测报警", "报警", "故障", "异常", "无信号", "报错", "停机", "卡滞",
        "失败", "不良", "超差", "偏差", "过电流", "高温", "漏油", "漏气", "松动", "断裂",
    ]
    q = (query or "").strip()
    comp, prob = "", ""

    for kw in problem_kws:
        if kw in q:
            prob = kw
            left = q.replace(kw, " ").strip()
            left = re.sub(r"(怎么办|怎么解决|怎么处理|怎么修|如何解决|如何处理|为什么|是什么|有哪些|吗|呢|啊|呀|吧|嘛)[\?？!！。,.，\s]*$", "", left).strip()
            if left:
                comp = left
            break

    top = docs[0] if docs else {}
    if not comp:
        comp = str(top.get("component", "")).strip()
    if not prob:
        prob = str(top.get("problem_description", "") or top.get("problem", "")).strip()
        for kw in problem_kws:
            if kw in prob:
                prob = kw
                break

    return comp, prob


def _build_graph_evidence_context(
    component: str,
    problem: str,
    area: str = "",
    equipment: str = "",
    limit: int = 12,
) -> tuple[str, str]:
    """复用 /graph/search 同口径结构化检索，生成回答用图谱证据摘要。"""
    from neo4j import GraphDatabase

    if not component and not problem and not area and not equipment:
        return "", ""

    neo4j_uri = os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687")
    neo4j_user = os.getenv("NEO4J_USERNAME", "neo4j")
    neo4j_password = os.getenv("NEO4J_PASSWORD", "12345678")
    driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))

    try:
        _db = os.getenv("NEO4J_DATABASE", "machining")
        with driver.session(database=_db) as session:
            result = _run_structured_graph_search(
                session,
                filters={
                    "area": area,
                    "equipment": equipment,
                    "component": component,
                    "problem": problem,
                    "cause": "",
                    "solution": "",
                },
                limit=max(1, limit),
            )
            nodes = result.get("nodes", [])
            links = result.get("links", [])
            trace = result.get("matched_trace", "") or ""

            if not nodes:
                return "", trace

            by_type: Dict[str, List[str]] = {}
            for n in nodes:
                by_type.setdefault(n.type, [])
                if n.name and n.name not in by_type[n.type]:
                    by_type[n.type].append(n.name)

            order = ["Area", "Equipment", "Component", "Problem", "Cause", "Solution"]
            lines = [
                f"图谱命中: {len(nodes)} 个节点, {len(links)} 条关系",
                f"命中策略: {trace or '结构化匹配'}",
            ]
            for t in order:
                names = by_type.get(t, [])[:3]
                if names:
                    lines.append(f"{t}: " + " / ".join(names))

            return "\n".join(lines), trace
    except Exception as e:
        print(f"[Qdrant->GraphEvidence] 构建图谱证据失败: {e}")
        return "", ""
    finally:
        driver.close()


def query_qdrant(state: GraphState) -> GraphState:
    import time
    query = state["query"]
    top_k = state.get("top_k", 15)
    # 结果不足时回退的阈值（至少返回这么多条才算"足够"）
    _MIN_FILTERED_RESULTS = 3

    logger.info("[RouteExec] route=qdrant followup=%s top_k=%s query=%s", state.get("is_followup", False), top_k, query[:120])

    try:
        # 计时：Embedding 生成（添加重试机制）
        t0 = time.time()
        max_retries = 2
        for attempt in range(max_retries):
            try:
                vec = embedder.embed_query(query).tolist()
                break
            except Exception as e:
                if attempt < max_retries - 1:
                    print(f"[Qdrant] Embedding 失败（第{attempt+1}次），重试中...")
                    time.sleep(1)
                else:
                    raise

        t1 = time.time()
        print(f"[Qdrant] ⏱️ Embedding 耗时: {t1-t0:.2f}s，维度: {len(vec)}")

        # ---- 结构化字段提取 + Filter 构建 ----
        fields = _extract_structured_fields(query)
        qdrant_filter = _build_qdrant_filter(fields) if fields else None
        if fields:
            print(f"[Qdrant] 提取到结构化字段: {fields}")

        # ---- 第一轮：带 filter 搜索 ----
        t2 = time.time()
        docs = []
        used_filter = False
        if qdrant_filter:
            docs = search_all_collections(vec, limit=top_k, query_filter=qdrant_filter)
            used_filter = True
            print(f"[Qdrant] Filter 搜索命中 {len(docs)} 条记录")

        # ---- 回退：结果不足时去掉 filter 重新搜索 ----
        if len(docs) < _MIN_FILTERED_RESULTS:
            if used_filter:
                print(f"[Qdrant] Filter 结果不足({len(docs)}<{_MIN_FILTERED_RESULTS})，回退到全量搜索")
            candidate_limit = _get_station_candidate_limit(query, top_k)
            fallback_docs = search_all_collections(vec, limit=candidate_limit)
            # 合并：filter 命中的排前面，再追加 fallback 去重
            seen_ids = {doc.get("id") for doc in docs}
            for fd in fallback_docs:
                if fd.get("id") not in seen_ids:
                    docs.append(fd)
                    seen_ids.add(fd.get("id"))

        t3 = time.time()
        print(f"[Qdrant] ⏱️ 检索耗时: {t3-t2:.2f}s，最终 {len(docs)} 条记录")

        # Station boost：精确匹配工位的记录加分，提升排序优先级
        station_in_query = fields.get("station", "")
        if station_in_query:
            docs = _apply_station_boost(docs, station_in_query)
        
        state["qdrant_records"] = qdrant_docs_to_frontend_records(
            docs,
            limit=top_k,
            source="qdrant",
            include_collection=True,
        )

        base_context = f"[来源: Qdrant 多 Collection 向量检索]\n\n{build_context_snippets(docs[:top_k])}"
        seed_component, seed_problem = _extract_component_problem_seed(query, docs[:3])
        graph_area = str(fields.get("line", "") or (docs[0].get("line", "") if docs else "")).strip()
        graph_equipment = str(fields.get("station", "") or (docs[0].get("station", "") if docs else "")).strip()
        graph_context, graph_trace = _build_graph_evidence_context(
            component=seed_component,
            problem=seed_problem,
            area=graph_area,
            equipment=graph_equipment,
            limit=min(12, max(6, top_k)),
        )

        if graph_context:
            state["context"] = base_context + "\n\n[来源: Neo4j 图谱证据]\n" + graph_context
            print(
                f"[Qdrant] 图谱证据已附加: area='{graph_area}', equipment='{graph_equipment}', "
                f"component='{seed_component}', problem='{seed_problem}', trace='{graph_trace}'"
            )
        else:
            state["context"] = base_context
            print(
                f"[Qdrant] 未命中图谱证据: area='{graph_area}', equipment='{graph_equipment}', "
                f"component='{seed_component}', problem='{seed_problem}'"
            )
    except TimeoutError as e:
        print(f"[Qdrant] Embedding 超时: {e}")
        state["context"] = "向量检索超时，请稍后重试或减少查询复杂度"
        state["qdrant_records"] = []
    except Exception as e:
        print(f"[Qdrant] 检索失败: {e}")
        import traceback
        traceback.print_exc()
        state["context"] = f"向量检索出错: {str(e)}"
        state["qdrant_records"] = []
    return state


def query_diagnosis(state: GraphState) -> GraphState:
    """智能诊断路由 — 三段式故障诊断流程

    第一部分：从 Neo4j 知识图谱检索相关子图
    第二部分：从 Qdrant 检索 top-20 / score≥0.6 原始记录
    第三部分：四维度优先级排序 → 排查流程
    """
    import time
    query = state["query"]
    print(f"\n[Diagnosis] ===== 开始三段式智能诊断 =====")

    # ---------- 第一部分：知识图谱子图 ----------
    try:
        kg_data = query_kg_subgraph(query, embedder)
        state["diagnosis_kg"] = kg_data
        state["diagnosis_kg_summary"] = kg_data.get("summary", "")
        print(f"[Diagnosis] Part1 知识图谱: {len(kg_data.get('nodes', []))} 节点, {len(kg_data.get('links', []))} 边")
    except Exception as e:
        print(f"[Diagnosis] Part1 知识图谱查询失败: {e}")
        state["diagnosis_kg"] = {"nodes": [], "links": [], "categories": []}
        state["diagnosis_kg_summary"] = f"知识图谱查询失败: {e}"

    # ---------- 第二部分：向量数据库原始记录 ----------
    try:
        kg_nodes = state.get("diagnosis_kg", {}).get("nodes", [])
        records, records_summary = query_original_records(
            query, embedder, search_all_collections,
            kg_nodes=kg_nodes, limit=20, score_threshold=0.6,
        )
        state["diagnosis_records"] = records
        state["qdrant_records"] = records          # 兼容现有前端表格
        state["diagnosis_records_summary"] = records_summary
        print(f"[Diagnosis] Part2 原始记录: {len(records)} 条 (score≥0.6)")
    except Exception as e:
        print(f"[Diagnosis] Part2 向量检索失败: {e}")
        state["diagnosis_records"] = []
        state["qdrant_records"] = []
        state["diagnosis_records_summary"] = f"向量检索失败: {e}"

    # ---------- 第三部分：优先级排序 + 排查流程 ----------
    try:
        flowchart_records, flowchart_summary = build_flowchart_data(
            state.get("diagnosis_records", [])
        )
        state["diagnosis_flowchart"] = flowchart_records
        state["diagnosis_flowchart_summary"] = flowchart_summary
        state["diagnosis_flow_plan"] = _build_flow_plan_with_llm(
            query=query,
            flowchart_records=flowchart_records,
            flowchart_summary=flowchart_summary,
            station_hint=_extract_station_from_query(query),
        )
        print(f"[Diagnosis] Part3 排查流程: {len(flowchart_records)} 条已排序")
        print(f"[Diagnosis] Part3 flow_plan steps: {len(state['diagnosis_flow_plan'].get('steps', []))}, "
              f"likely_cause: '{state['diagnosis_flow_plan'].get('likely_cause', '')[:30]}', "
              f"verify: '{state['diagnosis_flow_plan'].get('verify', '')[:30]}'")
        if state['diagnosis_flow_plan'].get('steps'):
            print(f"[Diagnosis] Part3 first step: {state['diagnosis_flow_plan']['steps'][0]}")
    except Exception as e:
        print(f"[Diagnosis] Part3 优先级排序失败: {e}")
        state["diagnosis_flowchart"] = []
        state["diagnosis_flowchart_summary"] = f"排序失败: {e}"
        state["diagnosis_flow_plan"] = {"likely_cause": "", "steps": [], "verify": "", "branch_mode": "single", "cause_branches": [], "diagram_spec": {"version": "dsl_v1", "problem": "当前问题", "likely_cause": "", "mode": "single", "steps": [], "branches": [], "verify": "处理后连续复测通过"}}

    # 构建 context 供后续 generate 使用（LLM 总结预留）
    state["context"] = "[来源: 三段式智能诊断]\n\n" + (
        state.get("diagnosis_kg_summary", "") + "\n" +
        state.get("diagnosis_records_summary", "") + "\n" +
        state.get("diagnosis_flowchart_summary", "")
    )
    # 首答仅保留简短引导文字（详细解释放在后续追问）
    state["final_answer"] = "已生成图谱、表格和流程图，请先查看结果；如需解释请在下方继续追问。"
    state["show_graph"] = True
    state["show_table"] = True

    print(f"[Diagnosis] ===== 三段式诊断完成 =====\n")
    return state


def query_visualization(state: GraphState) -> GraphState:
    """可视化路由 - 处理表格和知识图谱请求，同时生成详细回答"""
    import time
    query = state["query"]
    top_k = state.get("top_k", 15)
    
    print(f"[Visualization] 开始处理可视化请求...")
    
    # 检测可视化类型
    graph_keywords = ["知识图谱", "图谱", "关系图", "节点", "可视化"]
    table_keywords = ["表格", "列表"]
    
    show_graph = any(kw in query for kw in graph_keywords)
    show_table = any(kw in query for kw in table_keywords)
    
    # 默认至少显示表格
    if not show_graph and not show_table:
        show_table = True
    
    state["show_graph"] = show_graph
    state["show_table"] = show_table
    
    # 执行多 Collection 向量检索获取数据
    try:
        t0 = time.time()
        vec = embedder.embed_query(query).tolist()
        t1 = time.time()
        print(f"[Visualization] ⏱️ Embedding 耗时: {t1-t0:.2f}s")

        # ---- 结构化字段提取 + Filter ----
        fields = _extract_structured_fields(query)
        qdrant_filter = _build_qdrant_filter(fields) if fields else None
        if fields:
            print(f"[Visualization] 提取到结构化字段: {fields}")

        _MIN_VIS = 3
        docs = []
        if qdrant_filter:
            docs = search_all_collections(vec, limit=top_k, query_filter=qdrant_filter)
            print(f"[Visualization] Filter 搜索命中 {len(docs)} 条记录")

        if len(docs) < _MIN_VIS:
            if qdrant_filter:
                print(f"[Visualization] Filter 结果不足({len(docs)}<{_MIN_VIS})，回退到全量搜索")
            candidate_limit = _get_station_candidate_limit(query, top_k)
            fallback_docs = search_all_collections(vec, limit=candidate_limit)
            seen_ids = {doc.get("id") for doc in docs}
            for fd in fallback_docs:
                if fd.get("id") not in seen_ids:
                    docs.append(fd)
                    seen_ids.add(fd.get("id"))

        station_in_query = fields.get("station", "")
        if station_in_query:
            docs = _apply_station_boost(docs, station_in_query)
        print(f"[Visualization] 最终 {len(docs)} 条记录")
        
        state["qdrant_records"] = qdrant_docs_to_frontend_records(
            docs,
            limit=top_k,
            source="qdrant",
            include_collection=True,
        )
        state["context"] = f"[来源: Qdrant 向量检索]\n\n{build_context_snippets(docs[:top_k])}"
        
        # 不再生成简短回复，让 generate_answer 节点生成详细回答
        # final_answer 留空，后续会走 generate_answer 节点
        
    except Exception as e:
        print(f"[Visualization] 检索失败: {e}")
        state["qdrant_records"] = []
        state["context"] = f"数据检索出错: {str(e)}"
    
    return state


def query_hybrid(state: GraphState) -> GraphState:
    """混合查询 - 优先使用 Qdrant，Neo4j 仅作为参考补充"""
    import time
    query = state["query"]
    messages = state.get("messages", [])
    is_followup = state.get("is_followup", False)
    top_k = state.get("top_k", 10)
    
    print(f"\n[Hybrid] 开始混合查询 (Qdrant 优先, Neo4j 补充)...")
    
    all_records = []
    seen_problems = set()  # 用于去重
    qdrant_has_results = False
    
    # 1. 优先 Qdrant 多 Collection 查询（主数据源）
    try:
        print(f"[Hybrid] Step 1: Qdrant 多 Collection 向量检索 (主数据源)...")
        t0 = time.time()
        vec = embedder.embed_query(query).tolist()

        # ---- 结构化字段提取 + Filter ----
        fields = _extract_structured_fields(query)
        qdrant_filter = _build_qdrant_filter(fields) if fields else None
        if fields:
            print(f"[Hybrid] 提取到结构化字段: {fields}")

        _MIN_HYB = 3
        docs = []
        if qdrant_filter:
            docs = search_all_collections(vec, limit=top_k, query_filter=qdrant_filter)
            print(f"[Hybrid] Filter 搜索命中 {len(docs)} 条记录")

        if len(docs) < _MIN_HYB:
            if qdrant_filter:
                print(f"[Hybrid] Filter 结果不足({len(docs)}<{_MIN_HYB})，回退到全量搜索")
            candidate_limit = _get_station_candidate_limit(query, top_k)
            fallback_docs = search_all_collections(vec, limit=candidate_limit)
            seen_ids = {doc.get("id") for doc in docs}
            for fd in fallback_docs:
                if fd.get("id") not in seen_ids:
                    docs.append(fd)
                    seen_ids.add(fd.get("id"))

        station_in_query = fields.get("station", "")
        if station_in_query:
            docs = _apply_station_boost(docs, station_in_query)
        t1 = time.time()
        
        for doc in docs:
            problem = str(doc.get("problem_description", "") or doc.get("problem", ""))
            action = str(doc.get("containment_action", "") or doc.get("action", ""))
            station = str(doc.get("station", ""))
            # 用 problem+action+station 去重（兼容 Machining 集合 problem 为空的情况）
            content_key = (problem[:50], action[:50], station)

            if content_key not in seen_problems:
                seen_problems.add(content_key)
                all_records.append({
                    "id": str(doc.get("id", "")),
                    "line": str(doc.get("line", "")),
                    "station": station,
                    "problem": problem,
                    "cause": str(doc.get("cause_analysis", "") or doc.get("cause", "")),
                    "action": action,
                    "plan": str(doc.get("action_plan", "") or doc.get("plan", "")),
                    "date": _format_date_val(doc.get("date", "")),
                    "score": doc.get("score"),
                    "score_percent": round((doc.get("score") or 0) * 100, 2),
                    "source": "qdrant",
                    "collection": doc.get("_collection", "")
                })
        
        qdrant_has_results = len(all_records) > 0
        print(f"[Hybrid] ⏱️ Qdrant 耗时: {t1-t0:.2f}s, 获取 {len(all_records)} 条有效记录")
    except Exception as e:
        print(f"[Hybrid] Qdrant 查询失败: {e}")
    
    # 2. Neo4j 补充查询（仅当 Qdrant 结果不足或需要图谱关系时）
    neo4j_records = []
    if not qdrant_has_results or len(all_records) < 3:
        try:
            print(f"[Hybrid] Step 2: Neo4j 图谱补充查询...")
            chat_history = []
            for msg in messages[-6:]:
                if hasattr(msg, 'content'):
                    role = "user" if isinstance(msg, HumanMessage) else "assistant"
                    chat_history.append({"role": role, "content": msg.content})
            
            tool = get_global_neo4j_tool()
            t0 = time.time()
            result = tool.query_with_records(query, chat_history=chat_history, is_followup=is_followup)
            t1 = time.time()
            
            neo4j_raw_records = result.get('records', [])
            
            for rec in neo4j_raw_records:
                # Neo4j 返回的 problem 可能是组合格式: "故障现象：xxx | 原因：xxx | 解决方案：xxx"
                problem_raw = rec.get('problem', '')
                station = rec.get('station', '')
                problem_key = (problem_raw[:50] if problem_raw else '', station)
                
                if problem_key not in seen_problems and problem_raw:
                    seen_problems.add(problem_key)
                    
                    # 解析 Neo4j 组合格式的 problem 字段
                    parsed = _parse_neo4j_problem(problem_raw)
                    
                    neo4j_records.append({
                        "id": str(rec.get('id', '')),
                        "line": str(rec.get('line', '')),
                        "station": station,
                        "problem": parsed.get('problem', problem_raw),
                        "cause": parsed.get('cause', '') or str(rec.get('cause', '') or ''),
                        "action": parsed.get('action', '') or str(rec.get('action', '') or ''),
                        "plan": str(rec.get('plan', '') or ''),
                        "date": _format_date_val(rec.get('date', '') or ''),
                        "score": rec.get('score'),
                        "score_percent": round((rec.get('score') or 0) * 100, 2),
                        "source": "neo4j"
                    })
            
            all_records.extend(neo4j_records)
            print(f"[Hybrid] ⏱️ Neo4j 耗时: {t1-t0:.2f}s, 补充 {len(neo4j_records)} 条")
        except Exception as e:
            print(f"[Hybrid] Neo4j 查询失败: {e}")
    else:
        print(f"[Hybrid] Qdrant 结果充足 ({len(all_records)} 条)，跳过 Neo4j 查询")
    
    # 3. 按相似度排序
    all_records.sort(key=lambda x: x.get('score', 0) or 0, reverse=True)
    state["qdrant_records"] = all_records
    
    # 4. 构建上下文
    context_parts = []
    if all_records:
        qdrant_count = sum(1 for r in all_records if r.get('source') == 'qdrant')
        neo4j_count = sum(1 for r in all_records if r.get('source') == 'neo4j')
        
        source_info = []
        if qdrant_count > 0:
            source_info.append(f"Qdrant {qdrant_count} 条")
        if neo4j_count > 0:
            source_info.append(f"Neo4j {neo4j_count} 条")
        
        context_parts.append(f"[来源: {' + '.join(source_info)}]\n")
        
        for idx, rec in enumerate(all_records[:top_k], 1):  # 最多显示 top_k 条
            source_tag = "📊" if rec.get('source') == 'neo4j' else "🔍"
            context_parts.append(f"{source_tag} 【记录 {idx}】")
            context_parts.append(f"  产线: {rec.get('line', 'N/A')}, 工位: {rec.get('station', 'N/A')}")
            context_parts.append(f"  日期: {rec.get('date', 'N/A')}")
            context_parts.append(f"  问题: {rec.get('problem', 'N/A')}")
            if rec.get('cause'):
                context_parts.append(f"  原因: {rec.get('cause')}")
            if rec.get('action'):
                context_parts.append(f"  措施: {rec.get('action')}")
            context_parts.append("")
    else:
        context_parts.append("未检索到相关故障记录。")
    
    state["context"] = "\n".join(context_parts)
    
    qdrant_count = sum(1 for r in all_records if r.get('source') == 'qdrant')
    neo4j_count = sum(1 for r in all_records if r.get('source') == 'neo4j')
    print(f"[Hybrid] ✅ 混合查询完成: Qdrant {qdrant_count} 条 + Neo4j {neo4j_count} 条 = 总计 {len(all_records)} 条")
    
    return state


def _parse_neo4j_problem(problem_text: str) -> dict:
    """解析 Neo4j 中组合格式的 problem 字段
    
    格式可能为: "故障现象：xxx | 原因：xxx | 解决方案：xxx"
    """
    result = {'problem': '', 'cause': '', 'action': ''}
    
    if not problem_text:
        return result
    
    # 尝试解析组合格式
    import re
    
    # 格式1: "故障现象：xxx | 原因：xxx | 解决方案：xxx"
    problem_match = re.search(r'故障现象[：:]\s*(.+?)(?:\s*\|\s*原因|$)', problem_text)
    cause_match = re.search(r'原因[：:]\s*(.+?)(?:\s*\|\s*解决|$)', problem_text)
    action_match = re.search(r'解决(?:方案|对策)?[：:]\s*(.+?)$', problem_text)
    
    if problem_match:
        result['problem'] = problem_match.group(1).strip()
    else:
        # 没有匹配到格式，原样返回
        result['problem'] = problem_text
    
    if cause_match:
        result['cause'] = cause_match.group(1).strip()
    
    if action_match:
        result['action'] = action_match.group(1).strip()
    
    return result


SEARCH_RETRY_FALLBACKS = {
    "neo4j": "qdrant",
    "qdrant": "neo4j",
    "hybrid": "neo4j",
}

SEARCH_EMPTY_ANSWER_HINTS = [
    "未找到相关",
    "没有相关",
    "无法确定",
    "No relevant",
    "no relevant",
    "Unable to determine",
]


def _reset_search_outputs(state: GraphState) -> None:
    state["context"] = ""
    state["final_answer"] = ""
    state["qdrant_records"] = []
    state["retry_pending"] = False


def run_search_strategy(state: GraphState) -> GraphState:
    strategy = str(state.get("search_strategy") or "qdrant").strip().lower()
    if strategy not in {"neo4j", "qdrant", "hybrid"}:
        strategy = "qdrant"
    state["search_strategy"] = strategy
    _reset_search_outputs(state)
    logger.info(
        "[RouteExec] route=search strategy=%s followup=%s top_k=%s query=%s",
        strategy,
        state.get("is_followup", False),
        state.get("top_k", ""),
        state.get("query", "")[:120],
    )

    if strategy == "neo4j":
        return query_neo4j(state)
    if strategy == "hybrid":
        return query_hybrid(state)
    return query_qdrant(state)


def generate_answer(state: GraphState) -> GraphState:
    import time
    import re
    query = state["query"]
    context = state.get("context", "")
    messages = state.get("messages", [])
    is_followup = state.get("is_followup", False)
    qdrant_records = state.get("qdrant_records", [])
    
    print(f"[生成] 开始生成答案...")
    print(f"[生成] 上下文长度: {len(context)} 字符")
    
    # 检测用户问题的语言
    user_language = _detect_user_language(query)
    print(f"[生成] 检测到用户问题语言: {user_language}")
    
    recent = messages[-6:] if len(messages) > 6 else messages
    
    # 检测是否请求表格形式
    table_keywords = ["表格", "列表", "列出", "列举"]
    wants_table = any(kw in query for kw in table_keywords)
    
    # 如果有qdrant记录且用户想要表格，提示LLM不要生成表格
    table_hint = ""
    if wants_table and qdrant_records:
        table_hint = "\n\n**Note:** Records will be displayed in table format separately." if user_language == "english" else "\n\n**重要：** 检索到的记录将以表格形式在界面上单独展示，你只需要用文字总结关键信息，不要生成Markdown表格。"

    followup_records_hint = ""
    if is_followup and qdrant_records:
        if user_language == "english":
            followup_records_hint = f"""

**Follow-up answering rules for current retrieved records ({len(qdrant_records)} records):**
1. Answer primarily from the current retrieved records, then use conversation history only as supporting context.
2. If the user asks for counts, types, categories, or lists, count distinct matching items instead of just counting records.
3. Explicitly state the scope, such as \"based on the current {len(qdrant_records)} retrieved records\".
4. Do NOT confuse \"number of records\" with \"number of components / issues / causes / stations\" unless the user explicitly asks about records.
5. If the records are insufficient to determine an exact answer, say so clearly instead of guessing."""
        else:
            followup_records_hint = f"""

**追问回答补充规则（当前有 {len(qdrant_records)} 条检索记录）：**
1. 优先基于当前检索记录回答，对话历史仅作为辅助上下文。
2. 如果用户问“多少个 / 多少种 / 有哪些 / 分别是什么 / 统计”，要按匹配对象去重统计，不能直接把记录条数当作答案。
3. 必须明确统计范围，例如“基于当前检索到的 {len(qdrant_records)} 条记录”。
4. 只有当用户明确在问“记录数”时，才能回答“共找到多少条记录”。
5. 若现有记录不足以得出精确结论，要直接说明，不要猜测。"""
    
    # 根据语言选择完全不同的提示模板
    if user_language == "english":
        if is_followup:
            system_msg = f"""You are a production fault query assistant. The user is asking a follow-up question in English.

**Conversation History/Records (may be in Chinese, translate to English when answering):**
{context}

**Rules:**
1. Read the conversation history/records above (they may be in Chinese)
2. Translate and summarize the relevant content into English
3. Do NOT fabricate or use external knowledge{table_hint}{followup_records_hint}"""
        else:
            system_msg = f"""You are a production fault query assistant. The user asked in English, so answer in English.

**Retrieved Records (in Chinese, translate to English when answering):**
{context}

**Rules:**
1. The records above are in Chinese. READ them and TRANSLATE/SUMMARIZE into English.
2. Reference records like "According to Record 1...", "Record 2 shows..."
3. Extract: problem descriptions, causes, solutions, stations, dates
4. Do NOT say "no information" if there are records - analyze them!{table_hint}"""
    else:
        # 中文模板
        prompts_config = get_prompts()
        if is_followup:
            system_prompt_template = prompts_config.get("system_prompt_followup", """你是一个生产问题查询助手。用户正在追问。

**核心规则（违反将被视为错误）：**
1. 你只能使用下方【对话历史/检索记录】中的内容回答
2. 如果历史中没有相关信息，必须回答"对话历史中没有相关信息，请提供更多细节"
3. 禁止编造、推测或使用外部知识

【对话历史/检索记录】：
{context}

请仅根据上述内容回答，不要添加任何未提及的信息。""")
            system_msg = system_prompt_template.replace("{context}", context).replace("{table_hint}", table_hint)
            system_msg += "\n\n补充规则：如果用户在问“有哪些 / 列出 / 汇总 / 统计 / 分别是什么”，请优先完整归纳上下文中所有匹配记录，不要只挑一条最主要记录。"
            system_msg += followup_records_hint
        else:
            system_prompt_template = prompts_config.get("system_prompt_new", """# 角色
你是生产故障查询助手，只能基于检索记录回答。

# 检索记录
{context}

# 严格规则
1. 只能转述检索记录的内容
2. 每个观点标注来源："根据记录1..."
3. 禁止编造任何信息

{table_hint}""")
            system_msg = system_prompt_template.replace("{context}", context).replace("{table_hint}", table_hint)

    if "[来源: Neo4j 图谱证据]" in context:
        if user_language == "english":
            system_msg += "\n\nAdditional rule: If [Neo4j graph evidence] exists in context, provide conclusion based on graph chain first, then use raw records as supporting details."
        else:
            system_msg += "\n\n补充规则：若上下文中存在【来源: Neo4j 图谱证据】，请先基于图谱链路给出结论，再用原始记录补充细节。"
    
    prompt_messages = [SystemMessage(content=system_msg)] + list(recent) + [HumanMessage(content=query)]
    
    try:
        t_gen_start = time.time()
        # 使用最新配置的 LLM
        current_llm = get_llm()
        response = current_llm.invoke(prompt_messages)
        t_gen_end = time.time()
        state["final_answer"] = response.content
        print(f"[生成] ⏱️ LLM 生成耗时: {t_gen_end-t_gen_start:.2f}s ({len(response.content)} 字符)")
    except Exception as e:
        print(f"[生成] 生成失败: {e}")
        state["final_answer"] = f"生成答案出错: {str(e)}"
    return state


# ===================== 结果验证节点 ===================== #

def check_result(state: GraphState) -> GraphState:
    """检查查询结果质量，决定是否需要重试"""
    if state.get("route") != "search":
        state["retry_pending"] = False
        return state

    context = state.get("context", "")
    final_answer = state.get("final_answer", "")
    route = state.get("route", "")
    search_strategy = str(state.get("search_strategy") or "qdrant").strip().lower()
    retry_count = state.get("retry_count", 0)
    qdrant_records = state.get("qdrant_records", [])
    first_search_strategy = state.get("first_search_strategy", "")
    if not first_search_strategy:
        state["first_search_strategy"] = search_strategy

    # 有检索记录则直接视为有效，不再依赖 context 长度
    has_records = len(qdrant_records) > 0

    # 只有真正的错误才触发额外兜底逻辑，不把"字段为空"的正常记录当作异常
    error_indicators = ["查询出错", "检索出错", "向量检索出错", "向量检索超时"]
    combined_text = f"{final_answer}\n{context}"
    has_error = any(ind in combined_text for ind in error_indicators)
    has_empty_answer_hint = any(ind in combined_text for ind in SEARCH_EMPTY_ANSWER_HINTS)
    should_retry = (
        not has_records
        and retry_count == 0
        and (
            search_strategy != "neo4j"
            or has_error
            or has_empty_answer_hint
        )
    )

    logger.info(
        "[RouteCheck] route=%s strategy=%s retry_count=%s records=%s retry=%s",
        route,
        search_strategy,
        retry_count,
        len(qdrant_records),
        should_retry,
    )

    if should_retry:
        fallback_strategy = SEARCH_RETRY_FALLBACKS.get(search_strategy)
        if fallback_strategy and fallback_strategy != search_strategy:
            state["search_strategy"] = fallback_strategy
            state["retry_pending"] = True
            state["first_route"] = route or state.get("first_route", "")
            if not state.get("first_search_strategy"):
                state["first_search_strategy"] = search_strategy
            state["retry_count"] = 1
            logger.info("[RouteCheck] action=retry switch_to=%s", fallback_strategy)
            return state

    state["retry_pending"] = False
    if retry_count == 0:
        state["retry_count"] = retry_count
    else:
        state["retry_count"] = 1
    logger.info("[RouteCheck] action=continue")

    return state


def check_result_decision(state: GraphState) -> Literal["retry", "generate", "end"]:
    """根据验证结果决定下一步"""
    if state.get("retry_pending", False):
        logger.info(
            "[RouteCheckDecision] decision=retry strategy=%s",
            state.get("search_strategy", ""),
        )
        return "retry"

    if state.get("qdrant_records"):
        logger.info("[RouteCheckDecision] decision=end reason=records_ready")
        return "end"

    if state.get("final_answer"):
        logger.info("[RouteCheckDecision] decision=end reason=answer_ready")
        return "end"

    logger.info("[RouteCheckDecision] decision=generate")
    return "generate"


# ===================== Build LangGraph ===================== #

def create_graph():
    """
    创建统一主路由工作流：
    history / search / diagnosis
    其中 search 内部再按 search_strategy 分派到 qdrant / neo4j / hybrid。
    """
    workflow = StateGraph(GraphState)

    # 添加节点
    workflow.add_node("router", route_query)
    workflow.add_node("search", run_search_strategy)
    workflow.add_node("diagnosis", query_diagnosis)
    workflow.add_node("check", check_result)
    workflow.add_node("generate", generate_answer)

    workflow.set_entry_point("router")

    # 路由决策
    def route_decision(state: GraphState) -> Literal["search", "diagnosis", "generate"]:
        route = state.get("route", "search")
        if route == "diagnosis":
            return "diagnosis"
        if route == "search":
            return "search"
        return "generate"

    workflow.add_conditional_edges(
        "router",
        route_decision,
        {"search": "search", "diagnosis": "diagnosis", "generate": "generate"},
    )

    workflow.add_edge("search", "check")
    workflow.add_edge("diagnosis", END)

    workflow.add_conditional_edges("check", check_result_decision, {
        "retry": "search",
        "generate": "generate",
        "end": END,
    })

    workflow.add_edge("generate", END)

    return workflow.compile()

graph = create_graph()

# ===================== Pydantic Models ===================== #

class ChatRequest(BaseModel):
    message: str
    conversation_id: Optional[str] = None
    top_k: int = 3
    stream: bool = False  # 是否流式输出
    query_mode: str = "auto"  # auto | new | followup
    followup_records: Optional[List[Dict]] = None  # 前端显式传入当前结果记录
    inline_followup: bool = False  # 内嵌追问（不保存到对话历史）

class QdrantRecordItem(BaseModel):
    id: str
    line: str
    station: str
    problem: str
    cause: str
    action: str
    plan: str
    date: str
    score: Optional[float] = None

class ChatResponse(BaseModel):
    response: str
    conversation_id: str
    is_followup: bool = False
    followup_confidence: float = 0.0
    followup_reason: str = ""
    route_used: str = ""
    qdrant_records: Optional[List[QdrantRecordItem]] = None  # Qdrant 检索记录

class Message(BaseModel):
    role: str
    content: str
    timestamp: str
    qdrant_records: Optional[List[QdrantRecordItem]] = None
    flow_plan: Optional[Dict] = None
    diagnosis_data: Optional[Dict] = None
    route_used: Optional[str] = None
    search_strategy: Optional[str] = None
    show_graph: Optional[bool] = None

class ConversationInfo(BaseModel):
    conversation_id: str
    title: Optional[str] = None
    message_count: int
    last_activity: str

class HealthResponse(BaseModel):
    status: str
    message: str

class GraphNode(BaseModel):
    id: str
    label: str
    type: str
    name: str
    sample_row_id: Optional[str] = None
    row_ids: Optional[List[str]] = None


def _build_assistant_extra_payload(
    route_used: str,
    state: Optional[Dict] = None,
    flow_plan_for_save: Optional[Dict] = None,
    show_graph: Optional[bool] = None,
) -> Dict:
    """构建助手消息扩展载荷，用于刷新后恢复前端可视化状态。"""
    state = state or {}
    payload: Dict = {"route_used": route_used or ""}

    effective_show_graph = show_graph
    if effective_show_graph is None and "show_graph" in state:
        effective_show_graph = state.get("show_graph")
    if effective_show_graph is not None:
        payload["show_graph"] = bool(effective_show_graph)

    if route_used == "search" and state.get("search_strategy"):
        payload["search_strategy"] = state.get("search_strategy")

    # 诊断路由：恢复完整三段式数据
    if route_used == "diagnosis":
        kg_data = state.get("diagnosis_kg", {})
        kg_summary = state.get("diagnosis_kg_summary", "")
        records = state.get("diagnosis_records", [])
        records_summary = state.get("diagnosis_records_summary", "")
        flowchart = state.get("diagnosis_flowchart", [])
        flowchart_summary = state.get("diagnosis_flowchart_summary", "")
        flowchart_plan = state.get("diagnosis_flow_plan", {})

        payload["diagnosis_data"] = {
            "kg": {"graph": kg_data, "summary": kg_summary},
            "records": {"records": records, "summary": records_summary},
            "flowchart": {"records": flowchart, "summary": flowchart_summary, "plan": flowchart_plan},
        }

    # search 路由：恢复统一 flowPlan
    if route_used == "search" and flow_plan_for_save:
        payload["flow_plan"] = flow_plan_for_save

    return payload

class GraphLink(BaseModel):
    id: Optional[str] = None
    source: str
    target: str
    type: str


class GraphPathDetail(BaseModel):
    text: str
    shared_row: Optional[str] = None
    source_year: Optional[str] = None
    source_csv_line: Optional[int] = None
    source_csv_row: Optional[int] = None
    source_csv_file: Optional[str] = None

class GraphData(BaseModel):
    nodes: List[GraphNode]
    links: List[GraphLink]
    executed_cypher: Optional[str] = None
    query_trace: Optional[str] = None
    paths: Optional[List[str]] = None
    path_details: Optional[List[GraphPathDetail]] = None
    total_paths: Optional[int] = None


class GraphNodeCreateRequest(BaseModel):
    type: str
    name: str
    description: Optional[str] = ""
    properties: Optional[Dict[str, Any]] = None


class GraphNodeUpdateRequest(BaseModel):
    type: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    properties: Optional[Dict[str, Any]] = None


class GraphEdgeCreateRequest(BaseModel):
    from_node_id: Optional[str] = None
    to_node_id: Optional[str] = None
    from_id: Optional[str] = None
    to_id: Optional[str] = None
    type: str
    properties: Optional[Dict[str, Any]] = None


class GraphMutationRollbackResponse(BaseModel):
    rolled_back: bool
    message: str
    mutation_id: str
    rollback_id: Optional[str] = None
    details: Optional[Dict[str, Any]] = None


class GraphMutationLogListResponse(BaseModel):
    total: int
    items: List[Dict[str, Any]]


_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_GRAPH_MUTATION_LOG_PATH = Path(
    os.getenv("GRAPH_MUTATION_LOG_PATH", str(_PROJECT_ROOT / "data" / "output" / "graph_mutations.jsonl"))
)

_ROW_HASH_SCHEMA_VERSION = "v2_area_equipment_component_problem"
_ROW_HASH_REQUIRED_COLUMNS = ["区域", "设备", "故障的现象描述", "解决对策", "预测故障原因", "日期"]
_ROW_SOURCE_LOOKUP: Optional[Dict[str, Dict[str, Any]]] = None
_ROW_SOURCE_LOOKUP_LOCK = threading.Lock()
_COMPONENT_ENTITY_DICT: Optional[List[str]] = None
_COMPONENT_ENTITY_DICT_LOCK = threading.Lock()
_COMPONENT_GENERIC_TERMS = {
    "报警", "故障", "异常", "问题", "检测", "信号", "原因", "处理", "维修", "更换", "调整",
}


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _row_hash_canonical_text(value: Any) -> str:
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value)).strip()
    return re.sub(r"\s+", "", text)


def _row_hash_v2_from_csv_row(row: Dict[str, Any]) -> str:
    payload = {
        "schema_version": _ROW_HASH_SCHEMA_VERSION,
        "row": {k: _row_hash_canonical_text(row.get(k, "")) for k in _ROW_HASH_REQUIRED_COLUMNS},
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _read_csv_with_fallback(csv_path: Path) -> List[Dict[str, Any]]:
    encodings = ("utf-8-sig", "utf-8", "gb18030", "gbk")
    last_exc: Optional[Exception] = None
    for enc in encodings:
        try:
            rows: List[Dict[str, Any]] = []
            with csv_path.open("r", encoding=enc, newline="") as f:
                reader = csv.DictReader(f)
                for idx, row in enumerate(reader, start=1):
                    rows.append({
                        "csv_line": idx + 1,
                        "csv_row": idx,
                        "row": row,
                    })
            return rows
        except UnicodeDecodeError as e:
            last_exc = e
            continue
        except Exception as e:
            last_exc = e
            break
    if last_exc:
        print(f"[row-source] 读取 CSV 失败: {csv_path} -> {last_exc}")
    return []


def _build_row_source_lookup() -> Dict[str, Dict[str, Any]]:
    mapping: Dict[str, Dict[str, Any]] = {}
    csv_candidates = [
        ("2023", _PROJECT_ROOT / "Version2" / "Machining 2023.csv"),
        ("2024", _PROJECT_ROOT / "Version2" / "Machining 2024.csv"),
        ("2025", _PROJECT_ROOT / "Version2" / "Machining 2025.csv"),
    ]

    total_rows = 0
    for year, csv_path in csv_candidates:
        if not csv_path.exists():
            continue
        rows = _read_csv_with_fallback(csv_path)
        for item in rows:
            raw_row = item.get("row") or {}
            row_hash = _row_hash_v2_from_csv_row(raw_row)
            if not row_hash:
                continue
            total_rows += 1
            if row_hash in mapping:
                continue
            mapping[row_hash] = {
                "year": year,
                "csv_line": int(item.get("csv_line") or 0) or None,
                "csv_row": int(item.get("csv_row") or 0) or None,
                "csv_file": csv_path.name,
            }

    print(f"[row-source] 构建映射完成: {len(mapping)} hashes / {total_rows} rows")
    return mapping


def _get_row_source_lookup() -> Dict[str, Dict[str, Any]]:
    global _ROW_SOURCE_LOOKUP
    if _ROW_SOURCE_LOOKUP is not None:
        return _ROW_SOURCE_LOOKUP
    with _ROW_SOURCE_LOOKUP_LOCK:
        if _ROW_SOURCE_LOOKUP is None:
            _ROW_SOURCE_LOOKUP = _build_row_source_lookup()
    return _ROW_SOURCE_LOOKUP


def _resolve_row_source(row_id: Optional[str]) -> Optional[Dict[str, Any]]:
    rid = str(row_id or "").strip()
    if not rid:
        return None
    try:
        return _get_row_source_lookup().get(rid)
    except Exception as e:
        print(f"[row-source] 映射查询失败: {e}")
        return None


def _normalize_component_text(text: Any) -> str:
    s = str(text or "").strip().lower()
    if not s:
        return ""
    s = re.sub(r"[\s\-_/|,，。;；:：()\[\]{}]+", "", s)
    return s


def _build_component_entity_dict_from_neo4j() -> List[str]:
    """从 Neo4j 导出 Component 唯一名称，构建本地白名单字典（仅 component）。"""
    driver = _neo4j_driver()
    out: List[str] = []
    try:
        _db = os.getenv("NEO4J_DATABASE", "machining")
        with driver.session(database=_db) as session:
            rows = session.run(
                """
MATCH (c:Component)
WHERE c.name IS NOT NULL AND trim(c.name) <> ''
RETURN DISTINCT trim(c.name) AS name
"""
            )
            for rec in rows:
                name = str(rec.get("name") or "").strip()
                if not name or len(name) < 2:
                    continue
                if name in _COMPONENT_GENERIC_TERMS:
                    continue
                out.append(name)
    except Exception as e:
        print(f"[component-dict] 构建失败: {e}")
    finally:
        try:
            driver.close()
        except Exception:
            pass

    # 最长优先，避免“声纳感应器”被“感应器”抢先命中
    uniq = sorted(set(out), key=lambda x: len(x), reverse=True)
    print(f"[component-dict] 加载完成: {len(uniq)} 项")
    return uniq


def _get_component_entity_dict() -> List[str]:
    global _COMPONENT_ENTITY_DICT
    if _COMPONENT_ENTITY_DICT is not None:
        return _COMPONENT_ENTITY_DICT
    with _COMPONENT_ENTITY_DICT_LOCK:
        if _COMPONENT_ENTITY_DICT is None:
            _COMPONENT_ENTITY_DICT = _build_component_entity_dict_from_neo4j()
    return _COMPONENT_ENTITY_DICT


def _resolve_component_by_dictionary(text: str, component_dict: Optional[List[str]] = None) -> str:
    """基于 component 白名单做最长匹配。"""
    raw = str(text or "").strip()
    if not raw:
        return ""
    normalized = _normalize_component_text(raw)
    if not normalized:
        return ""

    dictionary = component_dict if component_dict is not None else _get_component_entity_dict()
    for comp in dictionary:
        c = _normalize_component_text(comp)
        if not c:
            continue
        if c in normalized:
            return comp
    return ""


def _safe_label(raw: str) -> str:
    text = str(raw or "").strip()
    if not text:
        return "Generic"
    safe = re.sub(r"[^A-Za-z0-9_]", "", text)
    return safe or "Generic"


def _safe_rel_type(raw: str) -> str:
    text = str(raw or "").strip().upper()
    safe = re.sub(r"[^A-Z0-9_]", "_", text)
    return safe or "RELATED_TO"


def _ensure_log_parent() -> None:
    _GRAPH_MUTATION_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)


def _append_graph_mutation_log(entry: Dict[str, Any]) -> None:
    _ensure_log_parent()
    with _GRAPH_MUTATION_LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _load_graph_mutation_logs(limit: int = 200) -> List[Dict[str, Any]]:
    if not _GRAPH_MUTATION_LOG_PATH.exists():
        return []
    rows: List[Dict[str, Any]] = []
    with _GRAPH_MUTATION_LOG_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    rows = list(reversed(rows))
    return rows[: max(1, min(limit, 2000))]


def _find_graph_mutation(mutation_id: str) -> Optional[Dict[str, Any]]:
    if not _GRAPH_MUTATION_LOG_PATH.exists():
        return None
    with _GRAPH_MUTATION_LOG_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except Exception:
                continue
            if str(item.get("mutation_id")) == str(mutation_id):
                return item
    return None


def _neo4j_driver():
    from neo4j import GraphDatabase

    neo4j_uri = os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687")
    neo4j_user = os.getenv("NEO4J_USERNAME", "neo4j")
    neo4j_password = os.getenv("NEO4J_PASSWORD", "12345678")
    return GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))


UI_LAYOUT_VERSION = "layout_v2_graph_table_flow_followup"
RESULTS_LEAD_TEXT = "已生成图谱、表格和流程图，请先查看结果；如需解释请在下方继续追问。"


def _graph_path_to_text(path) -> str:
    """将 Neo4j path 转成可读字符串，如：A -[HAS_FAULT]-> B -[CAUSED_BY]-> C"""
    try:
        nodes = list(path.nodes)
        rels = list(path.relationships)
        if not nodes:
            return ""

        def _name(n):
            return str(n.get("name", "") or "")

        parts = [_name(nodes[0])]
        for idx, rel in enumerate(rels):
            parts.append(f"-[{rel.type}]->")
            nxt = nodes[idx + 1] if idx + 1 < len(nodes) else None
            parts.append(_name(nxt) if nxt else "")
        return " ".join([p for p in parts if p]).strip()
    except Exception:
        return ""


def _graph_collect_paths(
    result,
    nodes_map,
    links_set,
    links,
    path_texts: Optional[set] = None,
    path_details: Optional[List[GraphPathDetail]] = None,
    path_detail_keys: Optional[set] = None,
):
    def _rel_source_rows(rel) -> List[str]:
        try:
            vals = rel.get("source_rows", None)
        except Exception:
            vals = None
        if not vals:
            return []
        out: List[str] = []
        for x in vals:
            sx = str(x or "").strip()
            if sx:
                out.append(sx)
        return out

    def _path_shared_row_id(path) -> Optional[str]:
        """按 r2-r4（HAS_FAULT/CAUSED_BY/SOLVED_BY）交集求同源 row 锚点。"""
        try:
            rels = list(path.relationships)
            if len(rels) < 5:
                return None
            core = [rels[2], rels[3], rels[4]]
            sr_lists = [rows for rows in (_rel_source_rows(r) for r in core) if rows]
            if not sr_lists:
                return None
            base = sr_lists[0]
            for x in base:
                if all(x in lst for lst in sr_lists):
                    return x
            return None
        except Exception:
            return None

    def _attach_row(node: GraphNode, row_id: Optional[str]) -> None:
        if not row_id:
            return
        if node.row_ids is None:
            node.row_ids = [row_id]
            node.sample_row_id = row_id
            return
        if row_id not in node.row_ids:
            node.row_ids.append(row_id)
        if not node.sample_row_id:
            node.sample_row_id = row_id

    for record in result:
        path = record["path"]
        shared_row_id = _path_shared_row_id(path)
        text = _graph_path_to_text(path)
        if path_texts is not None and text:
            path_texts.add(text)
        if path_details is not None and text:
            src = _resolve_row_source(shared_row_id)
            key = (text, str(shared_row_id or ""))
            if path_detail_keys is None or key not in path_detail_keys:
                if path_detail_keys is not None:
                    path_detail_keys.add(key)
                path_details.append(
                    GraphPathDetail(
                        text=text,
                        shared_row=shared_row_id,
                        source_year=str(src.get("year") or "") if src else None,
                        source_csv_line=int(src.get("csv_line")) if src and src.get("csv_line") else None,
                        source_csv_row=int(src.get("csv_row")) if src and src.get("csv_row") else None,
                        source_csv_file=str(src.get("csv_file") or "") if src else None,
                    )
                )
        for rel in path.relationships:
            sid = str(rel.start_node.element_id)
            tid = str(rel.end_node.element_id)
            rtype = rel.type
            rel_id = str(getattr(rel, "element_id", "") or "")
            if sid not in nodes_map:
                sn = rel.start_node
                sname = sn.get("name", "") or ""
                nodes_map[sid] = GraphNode(
                    id=sid,
                    label=(sname[:20] + "...") if len(sname) > 20 else sname,
                    type=list(sn.labels)[0] if sn.labels else "Unknown",
                    name=sname,
                )
            _attach_row(nodes_map[sid], shared_row_id)
            if tid not in nodes_map:
                tn = rel.end_node
                tname = tn.get("name", "") or ""
                nodes_map[tid] = GraphNode(
                    id=tid,
                    label=(tname[:20] + "...") if len(tname) > 20 else tname,
                    type=list(tn.labels)[0] if tn.labels else "Unknown",
                    name=tname,
                )
            _attach_row(nodes_map[tid], shared_row_id)
            key = (rel_id or f"{sid}|{rtype}|{tid}")
            if key not in links_set:
                links_set.add(key)
                links.append(GraphLink(id=(rel_id or None), source=sid, target=tid, type=rtype))


def _build_graph_executed_cypher(where_parts: list, params: dict) -> str:
    where_block = "\n".join(where_parts) if where_parts else ""
    cypher_text = (
        "MATCH path = (a:Area)-[:INCLUDE]->(e:Equipment)-[:HAS_PART]->(c:Component)\n"
        "             -[:HAS_FAULT]->(p:Problem)-[:CAUSED_BY]->(ca:Cause)-[:SOLVED_BY]->(s:Solution)\n"
        "WHERE true\n"
        f"{where_block}\n"
        "WITH path,\n"
        "     r2, r3, r4,\n"
        "     [r IN [r2, r3, r4] WHERE r.source_rows IS NOT NULL AND size(r.source_rows) > 0 | r.source_rows] AS sr_lists\n"
        "WITH path, r2, r3, r4, sr_lists,\n"
        "     CASE WHEN size(sr_lists) = 0 THEN NULL\n"
        "          ELSE head([x IN sr_lists[0] WHERE ALL(lst IN sr_lists WHERE x IN lst)])\n"
        "     END AS shared_row\n"
        "WHERE (size(sr_lists) = 0 OR shared_row IS NOT NULL)\n"
        "RETURN path"
    )
    for k, v in params.items():
        cypher_text = cypher_text.replace(f"${k}", f"'{v}'")
    return cypher_text


def _run_structured_graph_search(session, filters: dict, limit: int, enforce_r1_row: bool = False):
    fixed_fields = {k: v for k, v in filters.items() if k not in ("component", "problem") and v}
    trial_pairs = _build_component_problem_trials(filters.get("component", ""), filters.get("problem", ""))

    nodes_map, links_set, links = {}, set(), []
    path_texts = set()
    path_details: List[GraphPathDetail] = []
    path_detail_keys = set()
    matched_trace = None
    matched_where_parts = []
    matched_params = {}

    for comp_item, prob_item in trial_pairs:
        where_parts, params = [], {}
        for field, value in fixed_fields.items():
            frag, p = _build_graph_condition(field, value, 'CONTAINS', field)
            where_parts.append(frag)
            params.update(p)

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
WITH path,
    r1, r2, r3, r4,
    [r IN [r2, r3, r4] WHERE r.source_rows IS NOT NULL AND size(r.source_rows) > 0 | r.source_rows] AS sr_lists
WITH path, r1, r2, r3, r4, sr_lists,
    CASE WHEN size(sr_lists) = 0 THEN NULL
        ELSE head([x IN sr_lists[0] WHERE ALL(lst IN sr_lists WHERE x IN lst)])
    END AS shared_row
WHERE (size(sr_lists) = 0 OR shared_row IS NOT NULL)
RETURN path
LIMIT toInteger($limit)
"""
        if enforce_r1_row:
            cypher = cypher.replace(
                "WHERE (size(sr_lists) = 0 OR shared_row IS NOT NULL)",
                "WHERE (size(sr_lists) = 0 OR shared_row IS NOT NULL)\n"
                "  AND (shared_row IS NULL OR shared_row IN coalesce(r1.row_ids, r1.source_rows, []))"
            )

        try:
            result = list(session.run(cypher, limit=max(1, limit), **params))
        except Exception:
            continue

        if result:
            parts_desc = []
            for f, v in fixed_fields.items():
                parts_desc.append(f"{f}='{v}'")
            if comp_item:
                parts_desc.append(f"component {comp_item[1]} '{comp_item[0]}'")
            if prob_item:
                parts_desc.append(f"problem {prob_item[1]} '{prob_item[0]}'")
            matched_trace = " + ".join(parts_desc)
            matched_where_parts = where_parts
            matched_params = params
            _graph_collect_paths(result, nodes_map, links_set, links, path_texts, path_details, path_detail_keys)
            break

    return {
        "nodes": list(nodes_map.values()),
        "links": links,
        "paths": list(path_texts),
        "path_details": path_details,
        "matched_trace": matched_trace,
        "executed_cypher": _build_graph_executed_cypher(matched_where_parts, matched_params) if matched_where_parts else None,
    }

# ===================== API Endpoints ===================== #

@app.get("/")
async def root():
    return {"message": "Agentic RAG API with LangGraph Routing", "version": "2.0.0"}


@app.get("/graph/node/{node_id}/neighbors")
async def graph_node_neighbors(node_id: str, limit: int = 50):
    """返回指定节点的邻居（nodes + relations），用于前端按需展开图谱。
    支持两种 node_id 格式：
    - 纯数字 ID（旧版 Neo4j）
    - elementId 格式如 "4:xxx:123"（Neo4j 5.x+），需要 URL 编码
    """
    try:
        # URL 解码，处理 elementId 中的冒号
        from urllib.parse import unquote
        decoded_node_id = unquote(node_id)
        
        tool = get_global_neo4j_tool()
        data = tool.get_neighbors(decoded_node_id, limit=limit)
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/graph/node")
async def create_graph_node(payload: GraphNodeCreateRequest):
    label = _safe_label(payload.type)
    name = str(payload.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name 不能为空")

    props = dict(payload.properties or {})
    props["name"] = name
    if payload.description is not None:
        props["description"] = str(payload.description)

    driver = _neo4j_driver()
    try:
        _db = os.getenv("NEO4J_DATABASE", "machining")
        with driver.session(database=_db) as session:
            cypher = f"""
MATCH (n:`{label}` {{name: $name}})
RETURN elementId(n) AS id
LIMIT 1
"""
            exists_row = session.run(cypher, name=name).single()
            if exists_row:
                raise HTTPException(status_code=409, detail=f"同类型同名节点已存在: {name}")

            create_cypher = f"""
CREATE (n:`{label}`)
SET n += $props
RETURN elementId(n) AS id, labels(n) AS labels, properties(n) AS props
"""
            rec = session.run(create_cypher, props=props).single()
            if not rec:
                raise HTTPException(status_code=500, detail="创建节点失败")

            node_id = str(rec["id"])
            mutation_id = str(uuid.uuid4())
            log_item = {
                "mutation_id": mutation_id,
                "timestamp": _now_iso(),
                "action": "create_node",
                "target": {"node_id": node_id},
                "request": payload.model_dump(),
                "inverse": {"action": "delete_node", "node_id": node_id, "detach": True},
            }
            _append_graph_mutation_log(log_item)

            node_props = dict(rec["props"] or {})
            return {
                "success": True,
                "id": node_id,
                "type": (rec["labels"] or [label])[0],
                "name": str(node_props.get("name", "")),
                "mutation_id": mutation_id,
            }
    finally:
        driver.close()


@app.put("/graph/node/{node_id}")
async def update_graph_node(node_id: str, payload: GraphNodeUpdateRequest):
    driver = _neo4j_driver()
    try:
        _db = os.getenv("NEO4J_DATABASE", "machining")
        with driver.session(database=_db) as session:
            old_row = session.run(
                """
MATCH (n)
WHERE elementId(n) = $node_id
RETURN elementId(n) AS id, labels(n) AS labels, properties(n) AS props
LIMIT 1
""",
                node_id=node_id,
            ).single()
            if not old_row:
                raise HTTPException(status_code=404, detail="节点不存在")

            old_labels = [str(x) for x in (old_row["labels"] or []) if str(x).strip()]
            old_props = dict(old_row["props"] or {})

            next_props = dict(old_props)
            if payload.name is not None:
                next_props["name"] = str(payload.name).strip()
            if payload.description is not None:
                next_props["description"] = str(payload.description)
            if payload.properties:
                next_props.update(dict(payload.properties))

            if not str(next_props.get("name", "")).strip():
                raise HTTPException(status_code=400, detail="name 不能为空")

            new_label = _safe_label(payload.type) if payload.type else (old_labels[0] if old_labels else "Generic")

            remove_clause = ""
            if old_labels:
                remove_clause = "REMOVE " + " ".join([f"n:`{_safe_label(lb)}`" for lb in old_labels])

            update_cypher = f"""
MATCH (n)
WHERE elementId(n) = $node_id
{remove_clause}
SET n:`{new_label}`
SET n = $next_props
RETURN elementId(n) AS id, labels(n) AS labels, properties(n) AS props
"""
            rec = session.run(update_cypher, node_id=node_id, next_props=next_props).single()
            if not rec:
                raise HTTPException(status_code=500, detail="更新节点失败")

            mutation_id = str(uuid.uuid4())
            log_item = {
                "mutation_id": mutation_id,
                "timestamp": _now_iso(),
                "action": "update_node",
                "target": {"node_id": node_id},
                "request": payload.model_dump(),
                "inverse": {
                    "action": "restore_node_state",
                    "node_id": node_id,
                    "labels": old_labels,
                    "properties": old_props,
                },
            }
            _append_graph_mutation_log(log_item)

            props = dict(rec["props"] or {})
            return {
                "success": True,
                "id": str(rec["id"]),
                "type": (rec["labels"] or [new_label])[0],
                "name": str(props.get("name", "")),
                "mutation_id": mutation_id,
            }
    finally:
        driver.close()


@app.delete("/graph/node/{node_id}")
async def delete_graph_node(node_id: str, detach: bool = True):
    driver = _neo4j_driver()
    try:
        _db = os.getenv("NEO4J_DATABASE", "machining")
        with driver.session(database=_db) as session:
            snapshot = session.run(
                """
MATCH (n)
WHERE elementId(n) = $node_id
OPTIONAL MATCH (n)-[r]-(m)
RETURN labels(n) AS labels,
       properties(n) AS props,
       collect({
         type: type(r),
         rel_props: properties(r),
         direction: CASE WHEN startNode(r) = n THEN 'out' ELSE 'in' END,
         other_id: CASE WHEN m IS NULL THEN NULL ELSE elementId(m) END
       }) AS rels
""",
                node_id=node_id,
            ).single()
            if not snapshot:
                raise HTTPException(status_code=404, detail="节点不存在")

            labels = [str(x) for x in (snapshot["labels"] or []) if str(x).strip()]
            props = dict(snapshot["props"] or {})
            rels = [dict(x) for x in (snapshot["rels"] or []) if x and x.get("type") and x.get("other_id")]

            if not detach and rels:
                raise HTTPException(status_code=409, detail="节点存在关联关系，请使用 detach=true")

            if detach:
                session.run(
                    """
MATCH (n)
WHERE elementId(n) = $node_id
DETACH DELETE n
""",
                    node_id=node_id,
                )
            else:
                session.run(
                    """
MATCH (n)
WHERE elementId(n) = $node_id
DELETE n
""",
                    node_id=node_id,
                )

            mutation_id = str(uuid.uuid4())
            log_item = {
                "mutation_id": mutation_id,
                "timestamp": _now_iso(),
                "action": "delete_node",
                "target": {"node_id": node_id},
                "request": {"detach": detach},
                "inverse": {
                    "action": "recreate_node",
                    "labels": labels,
                    "properties": props,
                    "relations": rels,
                },
            }
            _append_graph_mutation_log(log_item)

            return {
                "success": True,
                "id": node_id,
                "mutation_id": mutation_id,
            }
    finally:
        driver.close()


@app.post("/graph/edge")
async def create_graph_edge(payload: GraphEdgeCreateRequest):
    from_id = str(payload.from_node_id or payload.from_id or "").strip()
    to_id = str(payload.to_node_id or payload.to_id or "").strip()
    rel_type = _safe_rel_type(payload.type)
    if not from_id or not to_id:
        raise HTTPException(status_code=400, detail="from_id / to_id 不能为空")

    rel_props = dict(payload.properties or {})
    driver = _neo4j_driver()
    try:
        _db = os.getenv("NEO4J_DATABASE", "machining")
        with driver.session(database=_db) as session:
            rec = session.run(
                f"""
MATCH (a) WHERE elementId(a) = $from_id
MATCH (b) WHERE elementId(b) = $to_id
CREATE (a)-[r:`{rel_type}`]->(b)
SET r += $rel_props
RETURN elementId(r) AS rel_id
""",
                from_id=from_id,
                to_id=to_id,
                rel_props=rel_props,
            ).single()
            if not rec:
                raise HTTPException(status_code=404, detail="起点或终点节点不存在")

            rel_id = str(rec["rel_id"])
            mutation_id = str(uuid.uuid4())
            log_item = {
                "mutation_id": mutation_id,
                "timestamp": _now_iso(),
                "action": "create_edge",
                "target": {"rel_id": rel_id, "from_id": from_id, "to_id": to_id, "type": rel_type},
                "request": payload.model_dump(),
                "inverse": {"action": "delete_edge", "rel_id": rel_id},
            }
            _append_graph_mutation_log(log_item)

            return {
                "success": True,
                "id": rel_id,
                "from_id": from_id,
                "to_id": to_id,
                "type": rel_type,
                "mutation_id": mutation_id,
            }
    finally:
        driver.close()


@app.delete("/graph/edge/{rel_id}")
async def delete_graph_edge(rel_id: str):
    rel_id = str(rel_id or "").strip()
    if not rel_id:
        raise HTTPException(status_code=400, detail="rel_id 不能为空")

    driver = _neo4j_driver()
    try:
        _db = os.getenv("NEO4J_DATABASE", "machining")
        with driver.session(database=_db) as session:
            snapshot = session.run(
                """
MATCH (a)-[r]->(b)
WHERE elementId(r) = $rel_id
RETURN elementId(r) AS rel_id,
       elementId(a) AS from_id,
       elementId(b) AS to_id,
       type(r) AS rel_type,
       properties(r) AS rel_props
LIMIT 1
""",
                rel_id=rel_id,
            ).single()

            if not snapshot:
                raise HTTPException(status_code=404, detail="关系不存在")

            from_id = str(snapshot["from_id"])
            to_id = str(snapshot["to_id"])
            rel_type = _safe_rel_type(snapshot["rel_type"])
            rel_props = dict(snapshot["rel_props"] or {})

            session.run(
                """
MATCH ()-[r]->()
WHERE elementId(r) = $rel_id
DELETE r
""",
                rel_id=rel_id,
            )

            mutation_id = str(uuid.uuid4())
            log_item = {
                "mutation_id": mutation_id,
                "timestamp": _now_iso(),
                "action": "delete_edge",
                "target": {"rel_id": rel_id, "from_id": from_id, "to_id": to_id, "type": rel_type},
                "request": {"rel_id": rel_id},
                "inverse": {
                    "action": "recreate_edge",
                    "from_id": from_id,
                    "to_id": to_id,
                    "type": rel_type,
                    "properties": rel_props,
                },
            }
            _append_graph_mutation_log(log_item)

            return {
                "success": True,
                "id": rel_id,
                "from_id": from_id,
                "to_id": to_id,
                "type": rel_type,
                "mutation_id": mutation_id,
            }
    finally:
        driver.close()


@app.get("/graph/mutations", response_model=GraphMutationLogListResponse)
async def list_graph_mutations(limit: int = 50):
    items = _load_graph_mutation_logs(limit=limit)
    return GraphMutationLogListResponse(total=len(items), items=items)


@app.post("/graph/mutations/{mutation_id}/rollback", response_model=GraphMutationRollbackResponse)
async def rollback_graph_mutation(mutation_id: str):
    row = _find_graph_mutation(mutation_id)
    if not row:
        raise HTTPException(status_code=404, detail="mutation 记录不存在")

    inverse = dict(row.get("inverse") or {})
    action = str(inverse.get("action") or "").strip()
    if not action:
        raise HTTPException(status_code=400, detail="mutation 缺少 inverse 信息")

    driver = _neo4j_driver()
    rollback_id = str(uuid.uuid4())
    try:
        _db = os.getenv("NEO4J_DATABASE", "machining")
        details: Dict[str, Any] = {}
        with driver.session(database=_db) as session:
            if action == "delete_node":
                node_id = str(inverse.get("node_id") or "").strip()
                if node_id:
                    session.run("MATCH (n) WHERE elementId(n) = $id DETACH DELETE n", id=node_id)
                    details = {"deleted_node_id": node_id}

            elif action == "restore_node_state":
                node_id = str(inverse.get("node_id") or "").strip()
                labels = [str(x) for x in (inverse.get("labels") or []) if str(x).strip()]
                props = dict(inverse.get("properties") or {})
                if not node_id:
                    raise HTTPException(status_code=400, detail="inverse 缺少 node_id")
                remove_clause = ""
                if labels:
                    remove_clause = "REMOVE " + " ".join([f"n:`{_safe_label(lb)}`" for lb in labels])
                first_label = _safe_label(labels[0] if labels else "Generic")
                session.run(
                    f"""
MATCH (n) WHERE elementId(n) = $id
{remove_clause}
SET n:`{first_label}`
SET n = $props
""",
                    id=node_id,
                    props=props,
                )
                details = {"restored_node_id": node_id}

            elif action == "recreate_node":
                labels = [str(x) for x in (inverse.get("labels") or []) if str(x).strip()]
                props = dict(inverse.get("properties") or {})
                rels = [dict(x) for x in (inverse.get("relations") or []) if isinstance(x, dict)]
                label = _safe_label(labels[0] if labels else "Generic")

                rec = session.run(
                    f"""
CREATE (n:`{label}`)
SET n = $props
RETURN elementId(n) AS id
""",
                    props=props,
                ).single()
                if not rec:
                    raise HTTPException(status_code=500, detail="回滚失败：无法重建节点")
                new_node_id = str(rec["id"])

                rel_recovered = 0
                for rel in rels:
                    other_id = str(rel.get("other_id") or "").strip()
                    rtype = _safe_rel_type(rel.get("type") or "RELATED_TO")
                    rel_props = dict(rel.get("rel_props") or {})
                    direction = str(rel.get("direction") or "out")
                    if not other_id:
                        continue
                    if direction == "out":
                        session.run(
                            f"""
MATCH (a) WHERE elementId(a) = $a
MATCH (b) WHERE elementId(b) = $b
CREATE (a)-[r:`{rtype}`]->(b)
SET r += $rel_props
""",
                            a=new_node_id,
                            b=other_id,
                            rel_props=rel_props,
                        )
                    else:
                        session.run(
                            f"""
MATCH (a) WHERE elementId(a) = $a
MATCH (b) WHERE elementId(b) = $b
CREATE (a)-[r:`{rtype}`]->(b)
SET r += $rel_props
""",
                            a=other_id,
                            b=new_node_id,
                            rel_props=rel_props,
                        )
                    rel_recovered += 1

                details = {"recreated_node_id": new_node_id, "recreated_relations": rel_recovered}

            elif action == "delete_edge":
                rel_id = str(inverse.get("rel_id") or "").strip()
                if rel_id:
                    session.run("MATCH ()-[r]-() WHERE elementId(r) = $id DELETE r", id=rel_id)
                    details = {"deleted_rel_id": rel_id}

            elif action == "recreate_edge":
                from_id = str(inverse.get("from_id") or "").strip()
                to_id = str(inverse.get("to_id") or "").strip()
                rel_type = _safe_rel_type(inverse.get("type") or "RELATED_TO")
                rel_props = dict(inverse.get("properties") or {})
                if not from_id or not to_id:
                    raise HTTPException(status_code=400, detail="inverse 缺少 from_id/to_id")

                rec = session.run(
                    f"""
MATCH (a) WHERE elementId(a) = $from_id
MATCH (b) WHERE elementId(b) = $to_id
CREATE (a)-[r:`{rel_type}`]->(b)
SET r += $rel_props
RETURN elementId(r) AS rel_id
""",
                    from_id=from_id,
                    to_id=to_id,
                    rel_props=rel_props,
                ).single()
                recreated_rel_id = str(rec["rel_id"]) if rec and rec["rel_id"] is not None else None
                details = {
                    "recreated_rel_id": recreated_rel_id,
                    "from_id": from_id,
                    "to_id": to_id,
                    "type": rel_type,
                }

            else:
                raise HTTPException(status_code=400, detail=f"不支持的回滚动作: {action}")

        rollback_log = {
            "mutation_id": rollback_id,
            "timestamp": _now_iso(),
            "action": "rollback",
            "target": {"source_mutation_id": mutation_id},
            "request": {"inverse_action": action},
            "inverse": {},
            "details": details,
        }
        _append_graph_mutation_log(rollback_log)

        return GraphMutationRollbackResponse(
            rolled_back=True,
            message="回滚成功",
            mutation_id=mutation_id,
            rollback_id=rollback_id,
            details=details,
        )
    finally:
        driver.close()

@app.get("/health", response_model=HealthResponse)
async def health_check():
    return HealthResponse(status="ok", message="API running")

@app.post("/chat")
async def chat(payload: ChatRequest, fastapi_request: Request):
    """聊天端点 - 支持流式和非流式输出"""
    import time
    total_start = time.time()
    print(f"[QueryMode][backend][request] query_mode={getattr(payload, 'query_mode', 'auto')} stream={payload.stream} msg='{str(payload.message)[:60]}'")
    
    # 公共初始化逻辑
    conversation_id = payload.conversation_id or str(uuid.uuid4())
    
    # 检查是否是新会话（用于设置标题）
    is_new_conversation = not db.conversation_exists(conversation_id)
    
    if is_new_conversation:
        # 用第一条消息作为会话标题（截取前50个字符）
        title = payload.message[:50] + ("..." if len(payload.message) > 50 else "")
        db.create_conversation(conversation_id, title=title)
    
    chat_history = []
    messages_for_graph = []
    
    if db.conversation_exists(conversation_id):
        messages = db.get_messages(conversation_id)
        chat_history = [{"role": m["role"], "content": m["content"]} for m in messages]
        for m in messages:
            if m["role"] == "user":
                messages_for_graph.append(HumanMessage(content=m["content"]))
            else:
                messages_for_graph.append(AIMessage(content=m["content"]))
    recent_followup_records = _resolve_followup_records(payload.followup_records, messages if 'messages' in locals() else [])
    
    # Allow per-request model override via headers `X-OLLAMA-MODEL` and `X-OLLAMA-BASEURL`
    header_ollama_model = fastapi_request.headers.get("x-ollama-model")
    header_ollama_baseurl = fastapi_request.headers.get("x-ollama-baseurl")

    query_mode = (payload.query_mode or "auto").strip().lower()
    if query_mode not in {"auto", "new", "followup"}:
        query_mode = "auto"

    if query_mode == "new":
        is_followup, confidence, reason = False, 1.0, "前端强制新问题"
    elif query_mode == "followup":
        is_followup, confidence, reason = True, 1.0, "前端强制追问"
    else:
        is_followup, confidence, reason = followup_detector.is_followup(payload.message, chat_history)

    print(f"[QueryMode] mode={query_mode}, is_followup={is_followup}, reason={reason}")
    
    initial_state = GraphState(
        messages=messages_for_graph,
        query=payload.message,
        route="",
        search_strategy="",
        first_search_strategy="",
        context="",
        final_answer="",
        is_followup=is_followup,
        top_k=payload.top_k,
        qdrant_records=[],
        retry_count=0,
        retry_pending=False,
        first_route="",
        show_graph=False,
        show_table=False,
        diagnosis_kg={},
        diagnosis_records=[],
        diagnosis_flowchart=[],
        diagnosis_flow_plan={"likely_cause": "", "steps": [], "verify": "", "branch_mode": "single", "cause_branches": [], "diagram_spec": {"version": "dsl_v1", "problem": "当前问题", "likely_cause": "", "mode": "single", "steps": [], "branches": [], "verify": "处理后连续复测通过"}},
        diagnosis_kg_summary="",
        diagnosis_records_summary="",
        diagnosis_flowchart_summary="",
        followup_records=recent_followup_records or [],
    )
    initial_state["query_mode"] = query_mode

    # attach header overrides into state for per-request LLM selection
    if header_ollama_model:
        initial_state["ollama_model"] = header_ollama_model
    if header_ollama_baseurl:
        initial_state["ollama_base_url"] = header_ollama_baseurl
    
    # 非流式模式
    if not payload.stream:
        try:
            final_state = graph.invoke(initial_state)
            total_end = time.time()
            print(f"\n[总耗时] ⏱️ 请求总耗时: {total_end-total_start:.2f}s\n")
            
            route_used = final_state.get("route", "unknown")
            search_strategy = final_state.get("search_strategy", "")
            qdrant_records = final_state.get("qdrant_records", [])
            response_text = final_state["final_answer"]
            show_table = bool(final_state.get("show_table", False))
            if qdrant_records:
                response_text = RESULTS_LEAD_TEXT
            print(
                f"[UI-V2][non-stream] route={route_used}, strategy={search_strategy}, "
                f"records={len(qdrant_records)}, response='{str(response_text)[:80]}'"
            )
            
            # 保存消息（内嵌追问不写入对话历史）
            if not getattr(payload, 'inline_followup', False):
                now = datetime.now().isoformat()
                db.add_message(conversation_id, "user", payload.message, now)
                assistant_extra = _build_assistant_extra_payload(route_used=route_used, state=final_state)
                extra_payload_str = json.dumps(assistant_extra, ensure_ascii=False) if assistant_extra else None
                if qdrant_records:
                    records_text = build_context_snippets(qdrant_records)
                    records_json_str = json.dumps(qdrant_records, ensure_ascii=False)
                    db.add_message(
                        conversation_id,
                        "assistant",
                        response_text or records_text,
                        now,
                        qdrant_records=records_json_str,
                        extra_payload=extra_payload_str,
                    )
                else:
                    db.add_message(
                        conversation_id,
                        "assistant",
                        response_text or "无结果",
                        now,
                        extra_payload=extra_payload_str,
                    )
            
            return ChatResponse(
                response=response_text,
                conversation_id=conversation_id,
                is_followup=is_followup,
                followup_confidence=confidence,
                followup_reason=reason,
                route_used=route_used,
                qdrant_records=[QdrantRecordItem(**r) for r in qdrant_records] if (qdrant_records and show_table) else None
            )
        except Exception as e:
            import traceback
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=str(e))
    
    # 流式模式
    async def generate():
        try:
            flow_plan_for_save = None
            show_graph_for_save = None
            # 发送元数据
            yield f"data: {json.dumps({'type': 'meta', 'conversation_id': conversation_id, 'is_followup': is_followup, 'query_mode': query_mode, 'ui_layout_version': UI_LAYOUT_VERSION}, ensure_ascii=False)}\n\n"
            
            # 检测是否是基于"以上记录"的追问（用于图谱）
            graph_keywords = ["知识图谱", "图谱", "关系图", "节点", "可视化"]
            followup_keywords = ["以上", "上面", "这些", "刚才", "之前", "所有", "全部"]
            show_graph = any(kw in payload.message for kw in graph_keywords)
            is_followup_graph = show_graph and any(kw in payload.message for kw in followup_keywords)
            
            # 如果是追问要求图谱，从历史消息收集所有 records
            if is_followup_graph:
                previous_records = []
                messages = db.get_messages(conversation_id)
                seen_ids = set()
                for m in messages:
                    if m.get("qdrant_records"):
                        try:
                            records = json.loads(m["qdrant_records"])
                            for r in records:
                                record_key = f"{r.get('station', '')}_{r.get('date', '')}_{str(r.get('problem', ''))[:20]}"
                                if record_key not in seen_ids:
                                    seen_ids.add(record_key)
                                    previous_records.append(r)
                        except:
                            pass
                
                if previous_records:
                    print(f"[Stream] 使用历史记录生成图谱: {len(previous_records)} 条")
                    yield f"data: {json.dumps({'type': 'route', 'route': 'search', 'search_strategy': 'context_records'}, ensure_ascii=False)}\n\n"
                    records_json = json.dumps({'type': 'records', 'records': previous_records, 'show_graph': True}, ensure_ascii=False)
                    yield f"data: {records_json}\n\n"

                    followup_flow_plan = None
                    try:
                        _station_hint = _extract_station_from_query(payload.message)
                        followup_flow_plan = _build_flow_plan_with_llm(
                            query=payload.message,
                            flowchart_records=previous_records,
                            flowchart_summary="",
                            station_hint=_station_hint,
                        )
                        yield f"data: {json.dumps({'type': 'flow_plan', 'plan': followup_flow_plan}, ensure_ascii=False)}\n\n"
                    except Exception as e:
                        print(f"[Stream] followup_graph flow_plan 生成失败: {e}")
                    
                    response_text = f"已基于对话中的 {len(previous_records)} 条记录生成知识图谱（已去重），请查看上方图谱。"
                    yield f"data: {json.dumps({'type': 'content', 'content': response_text}, ensure_ascii=False)}\n\n"
                    
                    now = datetime.now().isoformat()
                    db.add_message(conversation_id, "user", payload.message, now)
                    _extra = {"route_used": "search", "search_strategy": "context_records", "show_graph": True}
                    if followup_flow_plan:
                        _extra["flow_plan"] = followup_flow_plan
                    extra_payload_str = json.dumps(_extra, ensure_ascii=False)
                    db.add_message(
                        conversation_id,
                        "assistant",
                        response_text,
                        now,
                        qdrant_records=json.dumps(previous_records, ensure_ascii=False),
                        extra_payload=extra_payload_str,
                    )
                    
                    yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"
                    return
            
            # 执行路由和检索
            state = initial_state.copy()

            # 1. 路由决策
            state = route_query(state)
            route_used = state.get("route", "unknown")
            search_strategy = state.get("search_strategy", "")
            print(
                f"[UI-V2][stream] route={route_used}, strategy={search_strategy}, "
                f"query_mode={query_mode}, is_followup={is_followup}, query='{payload.message[:60]}'"
            )

            yield f"data: {json.dumps({'type': 'route', 'route': route_used, 'search_strategy': search_strategy}, ensure_ascii=False)}\n\n"

            # 2. 根据主路由执行
            if route_used == "diagnosis":
                # ---------- 三段式智能诊断 ----------
                state = query_diagnosis(state)
                qdrant_records = state.get("qdrant_records", [])

                kg_data = state.get("diagnosis_kg", {})
                kg_summary = state.get("diagnosis_kg_summary", "")
                yield f"data: {json.dumps({'type': 'diagnosis_kg', 'graph': kg_data, 'summary': kg_summary}, ensure_ascii=False)}\n\n"

                records = state.get("diagnosis_records", [])
                records_summary = state.get("diagnosis_records_summary", "")
                yield f"data: {json.dumps({'type': 'diagnosis_records', 'records': records, 'summary': records_summary}, ensure_ascii=False)}\n\n"

                flowchart = state.get("diagnosis_flowchart", [])
                flowchart_summary = state.get("diagnosis_flowchart_summary", "")
                flowchart_plan = state.get("diagnosis_flow_plan", {"likely_cause": "", "steps": [], "verify": "", "branch_mode": "single", "cause_branches": [], "diagram_spec": {"version": "dsl_v1", "problem": "当前问题", "likely_cause": "", "mode": "single", "steps": [], "branches": [], "verify": "处理后连续复测通过"}})
                yield f"data: {json.dumps({'type': 'diagnosis_flowchart', 'records': flowchart, 'summary': flowchart_summary, 'plan': flowchart_plan}, ensure_ascii=False)}\n\n"

                response_text = state.get("final_answer", RESULTS_LEAD_TEXT) or RESULTS_LEAD_TEXT
                print(f"[UI-V2][diagnosis] records={len(qdrant_records)}, lead_text_sent=1")
                yield f"data: {json.dumps({'type': 'content', 'content': response_text}, ensure_ascii=False)}\n\n"

            elif route_used == "search":
                state = run_search_strategy(state)
                state = check_result(state)
                decision = check_result_decision(state)

                if decision == "retry":
                    print(f"[UI-V2][stream][retry] search_strategy={state.get('search_strategy', '')}")
                    yield f"data: {json.dumps({'type': 'route', 'route': 'search', 'search_strategy': state.get('search_strategy', '')}, ensure_ascii=False)}\n\n"
                    state = run_search_strategy(state)
                    state = check_result(state)
                    decision = check_result_decision(state)

                qdrant_records = state.get("qdrant_records", [])
                search_strategy = state.get("search_strategy", "")
                show_graph_for_save = bool(state.get("show_graph", False))

                if qdrant_records:
                    response_text = RESULTS_LEAD_TEXT
                    print(f"[UI-V2][search] strategy={search_strategy}, records={len(qdrant_records)}, lead_text_sent=1")
                    yield f"data: {json.dumps({'type': 'content', 'content': response_text}, ensure_ascii=False)}\n\n"

                    records_json = json.dumps(
                        {
                            'type': 'records',
                            'records': qdrant_records,
                            'show_graph': bool(state.get("show_graph", False)),
                            'search_strategy': search_strategy,
                        },
                        ensure_ascii=False,
                    )
                    yield f"data: {records_json}\n\n"

                    try:
                        _station_hint = _extract_station_from_query(state["query"])
                        flow_plan = _build_flow_plan_with_llm(
                            query=state["query"],
                            flowchart_records=qdrant_records,
                            flowchart_summary=state.get("final_answer", ""),
                            station_hint=_station_hint,
                        )
                        flow_plan_for_save = flow_plan
                        print(f"[Stream] search flow_plan: {len(flow_plan.get('steps', []))} steps")
                        yield f"data: {json.dumps({'type': 'flow_plan', 'plan': flow_plan}, ensure_ascii=False)}\n\n"
                    except Exception as e:
                        print(f"[Stream] search flow_plan 生成失败: {e}")
                else:
                    if decision == "generate":
                        state = generate_answer(state)

                    response_text = state.get("final_answer", "").strip()
                    if not response_text:
                        response_text = "检索到的记录中没有相关信息"

                    for i in range(0, len(response_text), 50):
                        chunk = response_text[i:i+50]
                        yield f"data: {json.dumps({'type': 'content', 'content': chunk}, ensure_ascii=False)}\n\n"
                        await asyncio.sleep(0.01)

            else:
                # history 路由 - 需要传递对话历史
                response_text = ""
                context = state.get("context", "")
                qdrant_records = state.get("qdrant_records", [])
                
                # 语言检测
                import re
                def detect_lang(text):
                    cn = len(re.findall(r'[\u4e00-\u9fff]', text))
                    en = len(re.findall(r'[a-zA-Z]', text))
                    return "english" if en > cn else "chinese"
                
                user_lang = detect_lang(state["query"])
                print(f"[Stream-History] 检测到用户语言: {user_lang}")
                
                # 构建包含历史的 prompt
                history_prompt = []
                for msg in messages_for_graph[-6:]:
                    history_prompt.append(msg)
                
                # 根据语言选择完全不同的提示模板
                if user_lang == "english":
                    system_msg = f"""You are a production fault support assistant. The user is asking a follow-up question in English.

**Conversation Context (may be in Chinese, translate to English when answering):**
{context}

Read the context above and answer in English. Translate Chinese content if needed.

Follow-up rules for current retrieved records ({len(qdrant_records)} records):
1. Answer primarily from the current retrieved records, then use conversation history only as supporting context.
2. If the user asks for counts, types, categories, or lists, count distinct matching items instead of just counting records.
3. Explicitly state the scope, such as "based on the current {len(qdrant_records)} retrieved records".
4. Do NOT confuse "number of records" with "number of components / issues / causes / stations" unless the user explicitly asks about records.
5. If the records are insufficient to determine an exact answer, say so clearly instead of guessing."""
                else:
                    prompts_config = get_prompts()
                    system_prompt_template = prompts_config.get("system_prompt_followup", """你是生产问题支持助手。用户正在追问，请基于对话历史回答。

**对话上下文：**
{context}""")
                    system_msg = system_prompt_template.replace("{context}", context)
                    system_msg += f"\n\n补充规则：如果用户在问“有哪些 / 列出 / 汇总 / 统计 / 分别是什么”，请优先完整归纳上下文中所有匹配记录，不要只挑一条最主要记录。\n\n**追问回答补充规则（当前有 {len(qdrant_records)} 条检索记录）：**\n1. 优先基于当前检索记录回答，对话历史仅作为辅助上下文。\n2. 如果用户问“多少个 / 多少种 / 有哪些 / 分别是什么 / 统计”，要按匹配对象去重统计，不能直接把记录条数当作答案。\n3. 必须明确统计范围，例如“基于当前检索到的 {len(qdrant_records)} 条记录”。\n4. 只有当用户明确在问“记录数”时，才能回答“共找到多少条记录”。\n5. 若现有记录不足以得出精确结论，要直接说明，不要猜测。"
                
                prompt_messages = [SystemMessage(content=system_msg)] + history_prompt + [HumanMessage(content=state["query"])]
                
                print(f"[生成] 开始流式生成答案（追问模式，历史消息数: {len(history_prompt)}）...")
                for chunk in llm.stream(prompt_messages):
                    if hasattr(chunk, 'content') and chunk.content:
                        response_text += chunk.content
                        yield f"data: {json.dumps({'type': 'content', 'content': chunk.content}, ensure_ascii=False)}\n\n"
                print(f"[生成] 流式生成完成 ({len(response_text)} 字符)")
                if not response_text.strip():
                    response_text = "No relevant information in conversation history" if user_lang == "english" else "对话历史中没有相关信息，请提供更多细节"
                    yield f"data: {json.dumps({'type': 'content', 'content': response_text}, ensure_ascii=False)}\n\n"
                    print(f"[生成] 回退答案已发送 ({len(response_text)} 字符)")
                qdrant_records = qdrant_records or []
            
            # 保存消息（内嵌追问不写入对话历史）
            if not getattr(payload, 'inline_followup', False):
                now = datetime.now().isoformat()
                db.add_message(conversation_id, "user", payload.message, now)
                records_json_str = json.dumps(qdrant_records, ensure_ascii=False) if qdrant_records else None
                assistant_extra = _build_assistant_extra_payload(
                    route_used=route_used,
                    state=state,
                    flow_plan_for_save=flow_plan_for_save,
                    show_graph=show_graph_for_save,
                )
                extra_payload_str = json.dumps(assistant_extra, ensure_ascii=False) if assistant_extra else None
                db.add_message(
                    conversation_id,
                    "assistant",
                    response_text or "无结果",
                    now,
                    qdrant_records=records_json_str,
                    extra_payload=extra_payload_str,
                )
            
            yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            yield f"data: {json.dumps({'type': 'error', 'error': str(e)}, ensure_ascii=False)}\n\n"
    
    return StreamingResponse(generate(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/conversations", response_model=List[ConversationInfo])
async def list_conversations():
    return [ConversationInfo(**c) for c in db.get_conversations()]

@app.get("/conversations/{conversation_id}/messages", response_model=List[Message])
async def get_messages(conversation_id: str):
    if not db.conversation_exists(conversation_id):
        raise HTTPException(status_code=404, detail="Conversation not found")
    messages = db.get_messages(conversation_id)
    result = []
    for m in messages:
        qdrant_records = None
        flow_plan = None
        diagnosis_data = None
        route_used = None
        search_strategy = None
        show_graph = None
        if m.get("qdrant_records"):
            try:
                qdrant_records = [QdrantRecordItem(**r) for r in json.loads(m["qdrant_records"])]
            except:
                pass
        if m.get("extra_payload"):
            try:
                extra = json.loads(m["extra_payload"])
                if isinstance(extra, dict):
                    flow_plan = extra.get("flow_plan")
                    diagnosis_data = extra.get("diagnosis_data")
                    route_used = extra.get("route_used")
                    search_strategy = extra.get("search_strategy")
                    show_graph = extra.get("show_graph")
            except:
                pass
        result.append(Message(
            role=m["role"],
            content=m["content"],
            timestamp=m["timestamp"],
            qdrant_records=qdrant_records,
            flow_plan=flow_plan,
            diagnosis_data=diagnosis_data,
            route_used=route_used,
            search_strategy=search_strategy,
            show_graph=show_graph,
        ))
    return result

@app.delete("/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str):
    if not db.delete_conversation(conversation_id):
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"message": f"Conversation {conversation_id} deleted"}

@app.get("/graph", response_model=GraphData)
async def get_graph(limit: int = 50):
    """获取Neo4j图谱数据用于可视化"""
    from neo4j import GraphDatabase
    
    neo4j_uri = os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687")
    neo4j_user = os.getenv("NEO4J_USERNAME", "neo4j")
    neo4j_password = os.getenv("NEO4J_PASSWORD", "12345678")
    
    driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))
    
    try:
        _db = os.getenv("NEO4J_DATABASE", "machining")
        with driver.session(database=_db) as session:
            # 查询节点和关系，Version2 统一用 name 属性
            result = session.run(f"""
                MATCH (n)
                WITH n LIMIT {limit}
                OPTIONAL MATCH (n)-[r]->(m)
                RETURN 
                    elementId(n) AS source_id,
                    labels(n)[0] AS source_type,
                    COALESCE(n.name, '') AS source_name,
                    elementId(r) AS rel_id,
                    type(r) AS rel_type,
                    elementId(m) AS target_id,
                    labels(m)[0] AS target_type,
                    COALESCE(m.name, '') AS target_name
            """)
            
            nodes_map = {}
            links = []
            
            for record in result:
                # 添加源节点
                source_id = record["source_id"]
                if source_id and source_id not in nodes_map:
                    source_name = record["source_name"] or ""
                    # 截取显示名称
                    display_name = source_name[:20] + "..." if len(source_name) > 20 else source_name
                    nodes_map[source_id] = GraphNode(
                        id=source_id,
                        label=display_name,
                        type=record["source_type"] or "Unknown",
                        name=source_name
                    )
                
                # 添加目标节点和关系
                if record["target_id"]:
                    target_id = record["target_id"]
                    if target_id not in nodes_map:
                        target_name = record["target_name"] or ""
                        display_name = target_name[:20] + "..." if len(target_name) > 20 else target_name
                        nodes_map[target_id] = GraphNode(
                            id=target_id,
                            label=display_name,
                            type=record["target_type"] or "Unknown",
                            name=target_name
                        )
                    
                    if record["rel_type"]:
                        links.append(GraphLink(
                            id=record["rel_id"],
                            source=source_id,
                            target=target_id,
                            type=record["rel_type"]
                        ))
            
            return GraphData(
                nodes=list(nodes_map.values()),
                links=links,
                paths=[],
                path_details=[],
            )
    finally:
        driver.close()

@app.get("/graph/search", response_model=GraphData)
async def search_graph(
    keyword: str = "",
    limit: int = 30,
    target_labels: Optional[str] = None,
    single_path: bool = False,
    strict_only: bool = False,
    area: str = "",
    equipment: str = "",
    component: str = "",
    problem: str = "",
    cause: str = "",
    solution: str = "",
):
    """搜索完整六节点链路。

    逻辑和 Neo4j Browser 手写查询完全一致：
    1. MATCH 完整 path
    2. WHERE 按字段过滤（精确 → CONTAINS 子串 → 丢弃）
    3. source_rows 同源过滤
    4. RETURN path LIMIT
    """
    import re as _re, time as _time
    from neo4j import GraphDatabase

    _t0 = _time.time()
    neo4j_uri = os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687")
    neo4j_user = os.getenv("NEO4J_USERNAME", "neo4j")
    neo4j_password = os.getenv("NEO4J_PASSWORD", "12345678")
    driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))

    # ── 清洗字段值 ──
    def _clean(v: str) -> str:
        v = v.strip()
        if not v:
            return v
        v = _re.sub(r'(怎么办|怎么解决|怎么处理|怎么修|如何解决|如何处理|原因是什么|为什么|是什么|有哪些)\s*[?？]*$', '', v)
        v = _re.sub(r'(怎么|如何|什么|吗|呢|啊|呀|吧|嘛)\s*[?？]*$', '', v)
        v = _re.sub(r'[?？!！。.,，]+$', '', v)
        return v.strip()

    filters = {
        "area": _clean(area),
        "equipment": _clean(equipment),
        "component": _clean(component),
        "problem": _clean(problem),
        "cause": _clean(cause),
        "solution": _clean(solution),
    }
    has_filters = any(filters.values())

    # ── 复用公共图谱工具函数 ──
    _collect_paths = _graph_collect_paths

    # ── 关键词模式：无结构化条件时，用 keyword 搜索 ──
    if not has_filters:
        cleaned_kw = _re.sub(
            r'(怎么办|怎么解决|怎么处理|怎么修|如何解决|如何处理|是什么|有哪些)\s*[?？]*$',
            '', keyword.strip()
        ).strip() or keyword.strip()

        if not cleaned_kw:
            driver.close()
            return GraphData(nodes=[], links=[], paths=[], path_details=[])

        _KW_VARS = [("c", "Component"), ("p", "Problem"), ("e", "Equipment"),
                     ("ca", "Cause"), ("s", "Solution"), ("a", "Area")]

        try:
            _db = os.getenv("NEO4J_DATABASE", "machining")
            with driver.session(database=_db) as session:
                nodes_map, links_set, links = {}, set(), []
                path_texts = set()
                path_details: List[GraphPathDetail] = []
                path_detail_keys = set()
                matched_var = None
                for var, _label in _KW_VARS:
                    if nodes_map:
                        break
                    cypher = f"""
MATCH path = (a:Area)-[r0:INCLUDE]->(e:Equipment)-[r1:HAS_PART]->(c:Component)
             -[r2:HAS_FAULT]->(p:Problem)-[r3:CAUSED_BY]->(ca:Cause)-[r4:SOLVED_BY]->(s:Solution)
WHERE toLower({var}.name) CONTAINS toLower($kw)
WITH path, r2, r3, r4,
    r1,
     [r IN [r2, r3, r4] WHERE r.source_rows IS NOT NULL AND size(r.source_rows) > 0 | r.source_rows] AS sr_lists
WITH path, r1, r2, r3, r4, sr_lists,
     CASE WHEN size(sr_lists) = 0 THEN NULL
          ELSE head([x IN sr_lists[0] WHERE ALL(lst IN sr_lists WHERE x IN lst)])
     END AS shared_row
WHERE (size(sr_lists) = 0 OR shared_row IS NOT NULL)
RETURN path
LIMIT toInteger($limit)
"""
                    try:
                        if strict_only:
                            cypher = cypher.replace(
                                "WHERE (size(sr_lists) = 0 OR shared_row IS NOT NULL)",
                                "WHERE (size(sr_lists) = 0 OR shared_row IS NOT NULL)\n"
                                "  AND (shared_row IS NULL OR shared_row IN coalesce(r1.row_ids, r1.source_rows, []))"
                            )
                        result = list(session.run(cypher, kw=cleaned_kw, limit=max(1, limit)))
                        if result:
                            matched_var = var
                            _collect_paths(result, nodes_map, links_set, links, path_texts, path_details, path_detail_keys)
                    except Exception as exc:
                        print(f"[graph/search] kw={cleaned_kw} var={var} failed: {exc}")

                # 构建 executed_cypher
                exec_cypher = None
                if matched_var:
                    strict_clause = (
                        "\nAND (shared_row IS NULL OR shared_row IN coalesce(r1.row_ids, r1.source_rows, []))"
                        if strict_only else ""
                    )
                    exec_cypher = (
                        f"MATCH path = (a:Area)-[:INCLUDE]->(e:Equipment)-[:HAS_PART]->(c:Component)\n"
                        f"             -[:HAS_FAULT]->(p:Problem)-[:CAUSED_BY]->(ca:Cause)-[:SOLVED_BY]->(s:Solution)\n"
                        f"WHERE toLower({matched_var}.name) CONTAINS toLower('{cleaned_kw}')\n"
                        f"WITH path, r1, r2, r3, r4, [r IN [r2,r3,r4] WHERE r.source_rows IS NOT NULL AND size(r.source_rows) > 0 | r.source_rows] AS sr_lists\n"
                        f"WITH path, r1, CASE WHEN size(sr_lists)=0 THEN NULL ELSE head([x IN sr_lists[0] WHERE ALL(lst IN sr_lists WHERE x IN lst)]) END AS shared_row, sr_lists\n"
                        f"WHERE (size(sr_lists)=0 OR shared_row IS NOT NULL){strict_clause}\n"
                        f"RETURN path LIMIT {limit}"
                    )

                print(f"[graph/search] keyword='{keyword}' → {len(nodes_map)} nodes, {len(links)} links, {_time.time()-_t0:.2f}s")
                return GraphData(
                    nodes=list(nodes_map.values()), links=links,
                    executed_cypher=exec_cypher,
                    query_trace=f"关键词搜索: '{cleaned_kw}' → 命中字段: {matched_var or '无'}" if cleaned_kw else None,
                    paths=list(path_texts),
                    path_details=path_details,
                )
        finally:
            driver.close()

    try:
        _db = os.getenv("NEO4J_DATABASE", "machining")
        with driver.session(database=_db) as session:
            search_result = _run_structured_graph_search(
                session,
                filters=filters,
                limit=limit,
                enforce_r1_row=bool(strict_only),
            )
            nodes = search_result["nodes"]
            links = search_result["links"]
            matched_trace = search_result["matched_trace"]
            exec_cypher = search_result["executed_cypher"]

            print(
                f"[graph/search] structured={filters}, matched=[{matched_trace or 'NONE'}] "
                f"→ {len(nodes)} nodes, {len(links)} links, {_time.time()-_t0:.2f}s"
            )
            return GraphData(
                nodes=nodes, links=links,
                executed_cypher=exec_cypher,
                query_trace=f"结构化搜索: {matched_trace}" if matched_trace else "结构化搜索: 无匹配",
                paths=search_result.get("paths", []),
                path_details=search_result.get("path_details", []),
            )
    finally:
        driver.close()


# ── Qdrant 记录 → Neo4j 六节点链路 反查 ──────────────────────
class RecordSearchRequest(BaseModel):
    records: List[Dict]
    limit: int = 30
    single_path: bool = False
    strict_only: bool = True
    question: Optional[str] = None
    query_mode: Optional[str] = None
    include_total: bool = False


@app.post("/graph/search-by-records", response_model=GraphData)
async def search_graph_by_records(req: RecordSearchRequest):
    """根据 Qdrant 检索记录反查 Neo4j 六节点链路。"""
    import re as _re, time as _time
    from neo4j import GraphDatabase

    _t0 = _time.time()
    neo4j_uri = os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687")
    neo4j_user = os.getenv("NEO4J_USERNAME", "neo4j")
    neo4j_password = os.getenv("NEO4J_PASSWORD", "12345678")
    driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))

    _collect_paths = _graph_collect_paths

    # ── single_path 模式 ──
    if req.single_path:
        first_record = (req.records or [None])[0]
        if not first_record:
            driver.close()
            return GraphData(nodes=[], links=[], paths=[], path_details=[])

        area = str(first_record.get("line", "") or first_record.get("area", "")).strip()
        equipment = str(first_record.get("station", "") or first_record.get("equipment", "")).strip()
        component = str(first_record.get("component", "")).strip()
        problem = str(first_record.get("problem", "")).strip()
        cause = str(first_record.get("cause", "")).strip()
        solution = str(first_record.get("action", "") or first_record.get("solution", "") or first_record.get("plan", "")).strip()

        # 拆分混合字段
        _PROBLEM_KWS = ['报警', '故障', '异常', '无信号', '报错', '停机', '卡滞',
                        '失败', '不良', '超差', '偏差', '过电流', '高温', '温度',
                        '漏油', '漏气', '松动', '断裂', '磨损', '卡死', '抖动',
                        '噪音', '振动', '发热', '短路', '断路', '超时']

        def _split(value, keywords):
            if not value:
                return '', ''
            for kw in keywords:
                if kw in value:
                    return kw, value.replace(kw, '').strip()
            return value, ''

        if problem and len(problem) > 4:
            extracted, remainder = _split(problem, _PROBLEM_KWS)
            if extracted and remainder:
                problem = extracted
                if not component:
                    component = remainder
                print(f"[records] problem split → problem='{problem}', component='{component}'")

        filters = {
            "area": area, "equipment": equipment, "component": component,
            "problem": problem, "cause": cause, "solution": solution,
        }
        print(f"[records-single] filters={filters}")

        try:
            _db = os.getenv("NEO4J_DATABASE", "machining")
            with driver.session(database=_db) as session:
                # 保留 records 中的 area/equipment 约束，避免混入其他设备的同类故障链路
                search_filters = {
                    "area": area,
                    "equipment": equipment,
                    "component": component,
                    "problem": problem,
                    "cause": "",
                    "solution": "",
                }
                search_result = _run_structured_graph_search(
                    session,
                    filters=search_filters,
                    limit=max(1, req.limit or 30),
                    enforce_r1_row=bool(req.strict_only),
                )

                nodes = search_result["nodes"]
                links = search_result["links"]
                matched_trace = search_result["matched_trace"]
                exec_cypher = search_result["executed_cypher"]

                print(f"[records-single] → {len(nodes)} nodes, {len(links)} links, {_time.time()-_t0:.2f}s")
                return GraphData(
                    nodes=nodes,
                    links=links,
                    executed_cypher=exec_cypher,
                    query_trace=f"records-single(对齐/graph/search): {matched_trace}" if matched_trace else "records-single(对齐/graph/search): 无匹配",
                    paths=search_result.get("paths", []),
                    path_details=search_result.get("path_details", []),
                    total_paths=len(search_result.get("paths", []) or []),
                )
        finally:
            driver.close()

    # ── 非 single_path：逐条记录查图谱（拆解 component / problem + 去掉 source_rows 约束） ──

    # 与 single_path 共用的 problem 关键词拆分列表
    # 扩展问题关键词：覆盖“尺寸椭圆/尺寸不稳定/加工孔偏”等现场常见表述
    # 说明：按“长词优先”顺序，避免“偏差”被“偏”提前截断。
    _PROB_KWS = [
        '尺寸不稳定', '加工尺寸不稳定', '产品尺寸不稳定',
        '尺寸椭圆', '加工椭圆', '产品尺寸椭圆', '螺纹孔椭圆',
        '孔偏', '加工孔偏', '偏差', '超差', '不良', '失败', 'NOK',
        '报警', '故障', '异常', '无信号', '报错', '停机', '卡滞',
        '过电流', '高温', '温度', '漏油', '漏气', '松动', '断裂',
        '磨损', '卡死', '抖动', '噪音', '振动', '发热', '短路', '断路',
        '超时', '椭圆', '不稳定', '偏'
    ]

    def _split_prob(value, keywords):
        """从 '刀库门报警' 中拆出 component='刀库门', problem='报警'"""
        if not value:
            return '', ''
        sorted_keywords = sorted(keywords, key=len, reverse=True)
        for kw in sorted_keywords:
            if kw in value:
                remainder = value.replace(kw, '', 1).strip()
                if kw.startswith('加工') and remainder and not remainder.endswith('加工'):
                    remainder = f"{remainder}加工"
                return kw, remainder
        return value, ''

    def _extract_question_problem_keyword(question):
        text = str(question or "").strip()
        if not text:
            return ""
        sorted_keywords = sorted(_PROB_KWS, key=len, reverse=True)
        for kw in sorted_keywords:
            if kw and kw in text:
                return kw
        return ""

    component_dict = _get_component_entity_dict()
    question_text = str(req.question or "").strip()
    question_component = _resolve_component_by_dictionary(question_text, component_dict) if question_text else ""
    question_problem = _extract_question_problem_keyword(question_text)
    query_mode = str(req.query_mode or "exact").strip().lower()
    is_exact_mode = query_mode == "exact"
    strict_exact_mode = bool(req.strict_only and is_exact_mode)
    strict_component_mode = bool(strict_exact_mode and question_component)
    strict_problem_mode = bool(strict_exact_mode and question_problem)
    if question_component:
        print(f"[records-paths] question component 命中: {question_component} (mode={query_mode})")
    if question_problem:
        print(f"[records-paths] question problem 命中: {question_problem} (mode={query_mode})")

    def _component_match(a: str, b: str) -> bool:
        na = _normalize_component_text(a)
        nb = _normalize_component_text(b)
        if not na or not nb:
            return False
        if strict_component_mode:
            return na == nb
        return na == nb or na in nb or nb in na

    seen_rows, unique_rows = set(), []
    for rec in (req.records or []):
        raw_prob = (rec.get("problem") or "").strip()
        raw_comp = (rec.get("component") or "").strip()
        cau = (rec.get("cause") or "").strip()
        equip = str(rec.get("station", "") or rec.get("equipment", "")).strip()
        area_val = str(rec.get("line", "") or rec.get("area", "")).strip()
        sol = str(rec.get("action", "") or rec.get("solution", "") or rec.get("plan", "")).strip()

        if not raw_prob and not cau:
            continue

        # 从 Qdrant problem 字段拆出 component + 纯 problem
        problem_sym, component = '', ''
        if raw_prob and len(raw_prob) > 1:
            problem_sym, component = _split_prob(raw_prob, _PROB_KWS)
            if not problem_sym:
                problem_sym = raw_prob
                component = ''

        # 若前端已携带 component，优先使用（避免仅依赖 problem 拆词导致丢失“螺纹加工”等部件）
        if raw_comp:
            component = raw_comp

        # 兜底1：component 字典白名单匹配（优先从 problem 文本中识别）
        if not component and raw_prob:
            component = _resolve_component_by_dictionary(raw_prob, component_dict)

        # 兜底2：从用户原始问题中识别到的 component（全局约束）
        if not component and question_component:
            component = question_component

        # 兜底3：未提取到 component 但问题文本含关键工艺词时，回填部件关键词
        if not component and raw_prob:
            if '螺纹' in raw_prob:
                component = '螺纹'
            elif '丝杠' in raw_prob:
                component = '丝杠'
            elif '轴承' in raw_prob:
                component = '轴承'

        # 精确模式下，若问题已高置信命中 component，仅保留同 component 的记录行
        if strict_component_mode and not _component_match(component, question_component):
            continue
        if strict_problem_mode and problem_sym and problem_sym != question_problem:
            continue

        key = (area_val, equip, component, problem_sym, cau, sol)
        if key not in seen_rows:
            seen_rows.add(key)
            unique_rows.append({
                "area": area_val, "equipment": equip,
                "component": component, "problem": problem_sym,
                "cause": cau, "solution": sol,
            })

    # 若精确模式下被过滤为空，构造一条锚定行，确保只围绕 question_component 检索
    if strict_component_mode and not unique_rows:
        first = (req.records or [None])[0] or {}
        unique_rows = [{
            "area": str(first.get("line", "") or first.get("area", "")).strip(),
            "equipment": str(first.get("station", "") or first.get("equipment", "")).strip(),
            "component": question_component,
            "problem": question_problem or str(first.get("problem", "")).strip(),
            "cause": "",
            "solution": "",
        }]

    if not unique_rows:
        driver.close()
        return GraphData(nodes=[], links=[], paths=[], path_details=[])

    try:
        _db = os.getenv("NEO4J_DATABASE", "machining")
        with driver.session(database=_db) as session:
            nodes_map, links_set, links = {}, set(), []
            path_texts = set()
            path_details: List[GraphPathDetail] = []
            path_detail_keys = set()
            total_path_signatures = set()
            per_row_limit = max(1, (req.limit or 30) // max(len(unique_rows), 1))

            def _run_path_query(_where_parts: List[str], _params: Dict[str, Any]):
                """执行统一 path 查询，返回 record 列表。"""
                if not _where_parts:
                    return []
                cypher = f"""
MATCH path = (a:Area)-[r0:INCLUDE]->(e:Equipment)-[r1:HAS_PART]->(c:Component)
             -[r2:HAS_FAULT]->(p:Problem)-[r3:CAUSED_BY]->(ca:Cause)-[r4:SOLVED_BY]->(s:Solution)
WHERE true
{chr(10).join(_where_parts)}
WITH path,
    r2, r3, r4,
    coalesce(r1.row_ids, r1.source_rows, []) AS r1_rows,
    [r IN [r2, r3, r4] WHERE r.source_rows IS NOT NULL AND size(r.source_rows) > 0 | r.source_rows] AS sr_lists
WITH path, r2, r3, r4, r1_rows, sr_lists,
    CASE WHEN size(sr_lists) = 0 THEN NULL
         ELSE head([x IN sr_lists[0] WHERE ALL(lst IN sr_lists WHERE x IN lst)])
    END AS shared_row
WHERE (size(sr_lists) = 0 OR shared_row IS NOT NULL)
  AND (
      NOT toBoolean($enforce_r1_row)
      OR shared_row IS NULL
      OR shared_row IN r1_rows
  )
RETURN path
LIMIT toInteger($limit)
"""
                return list(session.run(cypher, **_params))

            def _fetch_path_signatures(_where_parts: List[str], _params: Dict[str, Any]) -> set:
                """获取当前条件下的全量路径签名（不受 limit 影响），用于 total_paths 统计。"""
                if not _where_parts:
                    return set()
                cypher = f"""
MATCH path = (a:Area)-[r0:INCLUDE]->(e:Equipment)-[r1:HAS_PART]->(c:Component)
             -[r2:HAS_FAULT]->(p:Problem)-[r3:CAUSED_BY]->(ca:Cause)-[r4:SOLVED_BY]->(s:Solution)
WHERE true
{chr(10).join(_where_parts)}
WITH path,
    r2, r3, r4,
    coalesce(r1.row_ids, r1.source_rows, []) AS r1_rows,
    [r IN [r2, r3, r4] WHERE r.source_rows IS NOT NULL AND size(r.source_rows) > 0 | r.source_rows] AS sr_lists
WITH path, r2, r3, r4, r1_rows, sr_lists,
    CASE WHEN size(sr_lists) = 0 THEN NULL
         ELSE head([x IN sr_lists[0] WHERE ALL(lst IN sr_lists WHERE x IN lst)])
    END AS shared_row
WHERE (size(sr_lists) = 0 OR shared_row IS NOT NULL)
  AND (
      NOT toBoolean($enforce_r1_row)
      OR shared_row IS NULL
      OR shared_row IN r1_rows
  )
WITH
    reduce(ns = '', n IN nodes(path) | ns + '|' + coalesce(n.name, '')) AS node_sig,
    reduce(rs = '', r IN relationships(path) | rs + '|' + type(r)) AS rel_sig
RETURN DISTINCT (node_sig + '#' + rel_sig) AS sig
"""
                params = dict(_params)
                params.pop("limit", None)
                rows = list(session.run(cypher, **params))
                out = set()
                for rec in rows:
                    sig = str(rec.get("sig") or "").strip()
                    if sig:
                        out.add(sig)
                return out

            for row_item in unique_rows:
                # ── 构建固定约束：area + equipment ──
                equip_val = row_item.get("equipment", "")
                area_val = row_item.get("area", "")
                fixed_parts: list = []
                fixed_params: dict = {}
                if equip_val:
                    _ev_list = _graph_field_variants(equip_val)
                    if _ev_list:
                        _ev, _eop = _ev_list[0]
                        frag, p = _build_graph_condition("equipment", _ev, _eop, "equip")
                        fixed_parts.append(frag)
                        fixed_params.update(p)
                if area_val:
                    _av_list = _graph_field_variants(area_val)
                    if _av_list:
                        _av, _aop = _av_list[0]
                        frag, p = _build_graph_condition("area", _av, _aop, "area_v")
                        fixed_parts.append(frag)
                        fixed_params.update(p)

                # ── 构建渐进回退 trial 列表：component + problem + cause ──
                comp_val = row_item.get("component", "")
                prob_val = row_item.get("problem", "")
                cau_val = row_item.get("cause", "")
                sol_val = row_item.get("solution", "")

                comp_variants = _graph_field_variants(comp_val) if comp_val else []
                prob_variants = _graph_field_variants(prob_val) if prob_val else []
                cause_variants = _graph_field_variants(cau_val) if cau_val else []

                # 精确模式：优先等值匹配 component，避免退化到 contains 扩散
                if strict_exact_mode:
                    exact_component = question_component or comp_val
                    comp_variants = [(exact_component, '=')] if exact_component else []
                    if strict_problem_mode:
                        prob_variants = [(question_problem, '=')] if question_problem else []

                def _tune_component_variants(raw_comp_text: str, base: List[tuple]) -> List[tuple]:
                    """对“螺纹”类部件收紧匹配，避免泛词（如“加工”）把路径拉偏。"""
                    if not raw_comp_text or not base:
                        return base
                    if '螺纹' not in raw_comp_text:
                        return base

                    out: List[tuple] = []
                    seen = set()

                    prefer = [
                        (raw_comp_text, '='),
                        (raw_comp_text, 'CONTAINS'),
                    ]
                    for it in prefer:
                        if it not in seen:
                            seen.add(it)
                            out.append(it)

                    for it in base:
                        try:
                            val = str(it[0])
                        except Exception:
                            continue
                        if '螺纹' in val and it not in seen:
                            seen.add(it)
                            out.append(it)

                    return out or base

                if not strict_exact_mode:
                    comp_variants = _tune_component_variants(comp_val, comp_variants)

                def _augment_problem_variants(raw_prob_text: str, base: List[tuple]) -> List[tuple]:
                    """扩展问题检索词，处理现场描述与图谱问题节点词面不一致（如“椭圆”→“超差”）。"""
                    if not raw_prob_text:
                        return base
                    extra: List[tuple[str, str]] = []
                    if '椭圆' in raw_prob_text:
                        extra.extend([
                            ('椭圆', 'CONTAINS'),
                            ('超差', 'CONTAINS'),
                            ('偏差', 'CONTAINS'),
                            ('不良', 'CONTAINS'),
                            ('尺寸超差', 'CONTAINS'),
                        ])
                    if '不稳定' in raw_prob_text:
                        extra.extend([
                            ('不稳定', 'CONTAINS'),
                            ('超差', 'CONTAINS'),
                            ('偏差', 'CONTAINS'),
                        ])
                    if '孔偏' in raw_prob_text or '偏' in raw_prob_text:
                        extra.extend([
                            ('孔偏', 'CONTAINS'),
                            ('偏差', 'CONTAINS'),
                            ('超差', 'CONTAINS'),
                        ])

                    out: List[tuple] = []
                    seen = set()
                    for it in list(base) + extra:
                        if it not in seen:
                            seen.add(it)
                            out.append(it)
                    return out

                if not strict_exact_mode:
                    prob_variants = _augment_problem_variants(prob_val, prob_variants)

                def _pick_variants(vs: List[tuple], head: int = 4, tail: int = 3) -> List[tuple]:
                    """保留前置高精度变体，同时补充尾部短词变体，避免关键短词被切片丢失。"""
                    if not vs:
                        return []
                    out: List[tuple] = []
                    seen = set()
                    for it in (list(vs[:head]) + list(vs[-tail:])):
                        if it not in seen:
                            seen.add(it)
                            out.append(it)
                    return out

                comp_pick = _pick_variants(comp_variants, head=4, tail=4)
                prob_pick = _pick_variants(prob_variants, head=4, tail=4)
                cause_pick = _pick_variants(cause_variants, head=3, tail=3)

                # 精确模式：禁止无 component 的 trial，避免扩散到无关路径
                if strict_exact_mode:
                    if not comp_pick:
                        continue
                    if prob_pick and cause_pick:
                        trial_list = []
                        for cv, cop in comp_pick[:4]:
                            for pv, pop in prob_pick[:4]:
                                for cav, caop in cause_pick[:3]:
                                    trial_list.append((cv, cop, pv, pop, cav, caop))
                        for cv, cop in comp_pick:
                            for pv, pop in prob_pick:
                                trial_list.append((cv, cop, pv, pop, None, None))
                        for cv, cop in comp_pick:
                            trial_list.append((cv, cop, None, None, None, None))
                    elif prob_pick:
                        trial_list = []
                        for cv, cop in comp_pick:
                            for pv, pop in prob_pick:
                                trial_list.append((cv, cop, pv, pop, None, None))
                        for cv, cop in comp_pick:
                            trial_list.append((cv, cop, None, None, None, None))
                    else:
                        trial_list = [(cv, cop, None, None, None, None) for cv, cop in comp_pick]
                else:
                    # trial 优先级：comp+prob+cause > comp+prob > comp+cause > comp > prob+cause > prob > cause
                    trial_list = []
                    if comp_pick and prob_pick and cause_pick:
                        for cv, cop in comp_pick[:4]:
                            for pv, pop in prob_pick[:4]:
                                for cav, caop in cause_pick[:3]:
                                    trial_list.append((cv, cop, pv, pop, cav, caop))
                        for cv, cop in comp_pick:
                            for pv, pop in prob_pick:
                                trial_list.append((cv, cop, pv, pop, None, None))
                        for cv, cop in comp_pick:
                            for cav, caop in cause_pick:
                                trial_list.append((cv, cop, None, None, cav, caop))
                        for cv, cop in comp_pick:
                            trial_list.append((cv, cop, None, None, None, None))
                    elif comp_pick and prob_pick:
                        for cv, cop in comp_pick:
                            for pv, pop in prob_pick:
                                trial_list.append((cv, cop, pv, pop, None, None))
                        for cv, cop in comp_pick:
                            trial_list.append((cv, cop, None, None, None, None))
                    elif comp_pick and cause_pick:
                        for cv, cop in comp_pick:
                            for cav, caop in cause_pick:
                                trial_list.append((cv, cop, None, None, cav, caop))
                        for cv, cop in comp_pick:
                            trial_list.append((cv, cop, None, None, None, None))
                    elif prob_pick and cause_pick:
                        for pv, pop in prob_pick:
                            for cav, caop in cause_pick:
                                trial_list.append((None, None, pv, pop, cav, caop))
                        for pv, pop in prob_pick:
                            trial_list.append((None, None, pv, pop, None, None))
                    elif comp_pick:
                        for cv, cop in comp_pick:
                            trial_list.append((cv, cop, None, None, None, None))
                    elif prob_pick:
                        for pv, pop in prob_pick:
                            trial_list.append((None, None, pv, pop, None, None))
                    elif cause_pick:
                        for cav, caop in cause_pick:
                            trial_list.append((None, None, None, None, cav, caop))
                    else:
                        continue

                found = False
                hit_stage = ''
                for trial in trial_list:
                    cv, cop, pv, pop, cav, caop = trial
                    where_parts = list(fixed_parts)
                    params = {"limit": per_row_limit, "enforce_r1_row": bool(req.strict_only), **fixed_params}

                    if cv:
                        frag, p = _build_graph_condition("component", cv, cop, "comp")
                        where_parts.append(frag)
                        params.update(p)
                    if pv:
                        frag, p = _build_graph_condition("problem", pv, pop, "prob")
                        where_parts.append(frag)
                        params.update(p)
                    if cav:
                        frag, p = _build_graph_condition("cause", cav, caop, "cau")
                        where_parts.append(frag)
                        params.update(p)

                    if not where_parts:
                        continue

                    try:
                        result = _run_path_query(where_parts, params)
                    except Exception as exc:
                        print(f"[records-paths] row={row_item}, trial comp={cv} prob={pv} cau={cav} failed: {exc}")
                        continue

                    if result:
                        _collect_paths(result, nodes_map, links_set, links, path_texts, path_details, path_detail_keys)
                        if req.include_total:
                            try:
                                total_path_signatures.update(_fetch_path_signatures(where_parts, params))
                            except Exception as exc:
                                print(f"[records-paths] total_paths 统计失败: {exc}")
                        found = True
                        hit_stage = 'strict'
                        break

                # 回退1：仅 area + equipment（仅 strict_only=False 时启用）
                if not req.strict_only and (not found) and fixed_parts:
                    try:
                        result = _run_path_query(list(fixed_parts), {"limit": per_row_limit, "enforce_r1_row": False, **fixed_params})
                        if result:
                            _collect_paths(result, nodes_map, links_set, links, path_texts, path_details, path_detail_keys)
                            if req.include_total:
                                try:
                                    total_path_signatures.update(
                                        _fetch_path_signatures(list(fixed_parts), {"enforce_r1_row": False, **fixed_params})
                                    )
                                except Exception as exc:
                                    print(f"[records-paths] total_paths 统计失败(fallback area+equipment): {exc}")
                            found = True
                            hit_stage = 'fallback_area_equipment'
                    except Exception as exc:
                        print(f"[records-paths] row={row_item}, fallback area+equipment failed: {exc}")

                # 回退2：仅 problem（仅 strict_only=False 时启用，可能跨设备）
                if not req.strict_only and (not found) and prob_variants:
                    try:
                        pv, pop = prob_variants[0]
                        frag, p = _build_graph_condition("problem", pv, pop, "prob_only")
                        where_parts = [frag]
                        params = {"limit": per_row_limit, "enforce_r1_row": False, **p}
                        result = _run_path_query(where_parts, params)
                        if result:
                            _collect_paths(result, nodes_map, links_set, links, path_texts, path_details, path_detail_keys)
                            if req.include_total:
                                try:
                                    total_path_signatures.update(_fetch_path_signatures(where_parts, params))
                                except Exception as exc:
                                    print(f"[records-paths] total_paths 统计失败(fallback problem-only): {exc}")
                            found = True
                            hit_stage = 'fallback_problem_only'
                    except Exception as exc:
                        print(f"[records-paths] row={row_item}, fallback problem-only failed: {exc}")

                if not found:
                    print(
                        f"[records-paths] 未命中: area={area_val} equip={equip_val} "
                        f"comp={comp_val} prob={prob_val} cau={cau_val} "
                        f"(trials={len(trial_list)}, fixed={bool(fixed_parts)}, prob_variants={len(prob_variants)})"
                    )
                else:
                    print(
                        f"[records-paths] 命中阶段: {hit_stage} | "
                        f"area={area_val} equip={equip_val} comp={comp_val} prob={prob_val}"
                    )

            print(f"[records-paths] {len(unique_rows)} rows → {len(nodes_map)} nodes, {len(links)} links, {len(path_texts)} paths, {_time.time()-_t0:.2f}s")
            return GraphData(
                nodes=list(nodes_map.values()),
                links=links,
                paths=list(path_texts),
                path_details=path_details,
                total_paths=(len(total_path_signatures) if req.include_total else None),
            )
    finally:
        driver.close()


@app.get("/graph/neighbors", response_model=GraphData)
async def get_node_neighbors(node_id: str, limit: int = 20):
    """获取指定节点的邻居节点 - 用于图谱展开功能"""
    from neo4j import GraphDatabase
    
    neo4j_uri = os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687")
    neo4j_user = os.getenv("NEO4J_USERNAME", "neo4j")
    neo4j_password = os.getenv("NEO4J_PASSWORD", "12345678")
    
    driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))
    
    try:
        _db = os.getenv("NEO4J_DATABASE", "machining")
        with driver.session(database=_db) as session:
            # 根据节点 ID 获取其所有邻居
            result = session.run(f"""
                MATCH (n)
                WHERE elementId(n) = $node_id
                OPTIONAL MATCH (n)-[r]-(neighbor)
                WITH n, r, neighbor
                LIMIT {limit}
                RETURN 
                    elementId(n) AS source_id,
                    labels(n)[0] AS source_type,
                    COALESCE(n.name, '') AS source_name,
                    elementId(r) AS rel_id,
                    type(r) AS rel_type,
                    CASE WHEN startNode(r) = n THEN 'outgoing' ELSE 'incoming' END AS direction,
                    elementId(neighbor) AS neighbor_id,
                    labels(neighbor)[0] AS neighbor_type,
                    COALESCE(neighbor.name, '') AS neighbor_name
            """, node_id=node_id)
            
            nodes_map = {}
            links = []
            
            for record in result:
                # 添加源节点（被点击的节点）
                source_id = record["source_id"]
                if source_id and source_id not in nodes_map:
                    source_name = record["source_name"] or ""
                    display_name = source_name[:20] + "..." if len(source_name) > 20 else source_name
                    nodes_map[source_id] = GraphNode(
                        id=source_id,
                        label=display_name,
                        type=record["source_type"] or "Unknown",
                        name=source_name
                    )
                
                # 添加邻居节点
                if record["neighbor_id"]:
                    neighbor_id = record["neighbor_id"]
                    if neighbor_id not in nodes_map:
                        neighbor_name = record["neighbor_name"] or ""
                        display_name = neighbor_name[:20] + "..." if len(neighbor_name) > 20 else neighbor_name
                        nodes_map[neighbor_id] = GraphNode(
                            id=neighbor_id,
                            label=display_name,
                            type=record["neighbor_type"] or "Unknown",
                            name=neighbor_name
                        )
                    
                    # 根据方向添加关系
                    if record["rel_type"]:
                        if record["direction"] == "outgoing":
                            link_source = source_id
                            link_target = neighbor_id
                        else:
                            link_source = neighbor_id
                            link_target = source_id
                        
                        # 避免重复
                        link_exists = any(
                            l.source == link_source and l.target == link_target and l.type == record["rel_type"]
                            for l in links
                        )
                        if not link_exists:
                            links.append(GraphLink(
                                id=record["rel_id"],
                                source=link_source,
                                target=link_target,
                                type=record["rel_type"]
                            ))
            
            return GraphData(
                nodes=list(nodes_map.values()),
                links=links,
                paths=[],
                path_details=[],
            )
    finally:
        driver.close()

@app.on_event("shutdown")
async def shutdown_event():
    global _global_neo4j_tool
    if _global_neo4j_tool:
        try:
            _global_neo4j_tool.close()
        except:
            pass

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
