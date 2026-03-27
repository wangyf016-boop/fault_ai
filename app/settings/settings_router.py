"""
Settings API - LLM 配置管理
"""

import json
import os
from pathlib import Path
from typing import Dict, Optional

from dotenv import dotenv_values, set_key
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/settings", tags=["settings"])

# .env 文件路径
ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
# 提示词配置文件路径
PROMPTS_PATH = Path(__file__).resolve().parents[2] / "prompts_config.json"

# 默认提示词模板
DEFAULT_PROMPTS = {
    "system_prompt_new": """# 角色
你是生产故障查询助手，只能基于检索记录回答。

# 检索记录
{context}

# 严格规则（必须100%遵守）
1. **只能转述上方检索记录的内容**，绝对禁止添加任何外部知识
2. 每个观点必须标注来源："根据记录1..."、"记录2显示..."
3. 如果记录中没有相关信息，直接说"检索记录中未找到相关信息"
4. 禁止编造日期、数据、解决方案
5. 禁止给出通用建议或操作步骤
6. 只根据最相关的记录回答，严格根据问题回答，问什么答什么
7. **语言规则（最高优先级）**：English question → English answer. 中文问题 → 中文回答
8. 当用户明确询问“怎么处理”或“如何处置”时：
- 可以基于检索记录提出可执行的验证步骤、临时处置措施和优先级建议。
- 若某项建议包含推断，需要在建议后注明“（基于记录推断，需现场验证）”。
- 仍要求引用记录作为依据（如有），并区分“事实/证据”与“建议/推断”。
输出要简洁、分点、优先级清晰。

# 输出格式
- 简洁、专业
- 按记录逐条总结

{table_hint}""",
    "system_prompt_followup": """你是一个生产问题查询助手。用户正在追问。

**核心规则（违反将被视为错误）：**
1. 你只能使用下方【对话历史/检索记录】中的内容回答
2. 如果历史中没有相关信息，必须回答"对话历史中没有相关信息，请提供更多细节"
3. 禁止编造、推测或使用外部知识
4. **语言规则（最高优先级）**：English question → English answer. 中文问题 → 中文回答

【对话历史/检索记录】：
{context}

请仅根据上述内容回答，不要添加任何未提及的信息。
{table_hint}""",
    "system_prompt_history": """你是生产问题支持助手。用户正在追问，请基于对话历史回答。

**对话上下文：**
{context}""",
    "neo4j_rag_prompt": """You are a production problem analyst. Answer in the SAME LANGUAGE as the user's question.
你是生产问题分析助手。使用与用户问题相同的语言回答。

【User Question / 用户问题】：
{question}

【Query Results / 查询结果】：
{context}

【CRITICAL RULES / 核心规则】：
1. Do NOT fabricate dates / 禁止编造日期
2. Do NOT add information not in the results / 禁止添加结果中没有的信息
3. Must reference specific data / 必须引用具体数据
4. **LANGUAGE RULE (HIGHEST PRIORITY)**: If user asks in English → respond ONLY in English. If user asks in Chinese → respond ONLY in Chinese.
   **语言规则（最高优先级）**：英文问题用英文答，中文问题用中文答

【Answer / 回答】：""",
}


class LLMConfig(BaseModel):
    llm_type: str = "glm"  # glm, ollama, openai
    api_base_url: Optional[str] = ""
    api_key: Optional[str] = ""
    model_name: Optional[str] = ""
    ollama_base_url: Optional[str] = ""
    ollama_model: Optional[str] = ""


class PromptsConfig(BaseModel):
    system_prompt_new: str = DEFAULT_PROMPTS["system_prompt_new"]
    system_prompt_followup: str = DEFAULT_PROMPTS["system_prompt_followup"]
    system_prompt_history: str = DEFAULT_PROMPTS["system_prompt_history"]
    neo4j_rag_prompt: str = DEFAULT_PROMPTS["neo4j_rag_prompt"]


class TestResult(BaseModel):
    success: bool
    response: Optional[str] = None
    error: Optional[str] = None


def load_prompts() -> Dict[str, str]:
    """加载提示词配置。"""
    if PROMPTS_PATH.exists():
        try:
            with open(PROMPTS_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return DEFAULT_PROMPTS.copy()


def save_prompts(prompts: Dict[str, str]):
    """保存提示词配置。"""
    with open(PROMPTS_PATH, "w", encoding="utf-8") as f:
        json.dump(prompts, f, ensure_ascii=False, indent=2)


_prompts_cache: Optional[Dict[str, str]] = None


def get_prompts() -> Dict[str, str]:
    """获取提示词配置（带缓存）。"""
    global _prompts_cache
    if _prompts_cache is None:
        _prompts_cache = load_prompts()
    return _prompts_cache


def reload_prompts():
    """重新加载提示词配置。"""
    global _prompts_cache
    _prompts_cache = load_prompts()
    return _prompts_cache


@router.get("/prompts", response_model=PromptsConfig)
async def get_prompts_config():
    """获取提示词配置。"""
    prompts = get_prompts()
    return PromptsConfig(**prompts)


@router.post("/prompts")
async def save_prompts_config(config: PromptsConfig):
    """保存提示词配置。"""
    try:
        prompts = config.dict()
        save_prompts(prompts)
        reload_prompts()
        return {"message": "提示词配置已保存"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/prompts/reset")
async def reset_prompts_config():
    """重置提示词为默认值。"""
    try:
        save_prompts(DEFAULT_PROMPTS.copy())
        reload_prompts()
        return {"message": "提示词已重置为默认值"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/llm", response_model=LLMConfig)
async def get_llm_config():
    """获取当前 LLM 配置。"""
    env_values = dotenv_values(ENV_PATH)
    return LLMConfig(
        llm_type=env_values.get("LLM_TYPE", "ollama"),
        api_base_url=env_values.get("API_BASE_URL", ""),
        api_key=env_values.get("GLM_API_KEY", ""),
        model_name=env_values.get("GLM_MODEL", ""),
        ollama_base_url=env_values.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
        ollama_model=env_values.get(
            "OLLAMA_MODEL",
            "Qwen3-30B-A3B-Instruct-2507-IQ4_NL.gguf",
        ),
    )


@router.post("/llm")
async def save_llm_config(config: LLMConfig):
    """保存 LLM 配置到 .env 文件。"""
    try:
        set_key(str(ENV_PATH), "LLM_TYPE", config.llm_type)
        set_key(str(ENV_PATH), "API_BASE_URL", config.api_base_url or "")
        set_key(str(ENV_PATH), "GLM_API_KEY", config.api_key or "")
        set_key(str(ENV_PATH), "ZHIPUAI_API_KEY", config.api_key or "")
        set_key(str(ENV_PATH), "GLM_MODEL", config.model_name or "")
        set_key(str(ENV_PATH), "MODEL_NAME", config.model_name or "")
        set_key(str(ENV_PATH), "OLLAMA_BASE_URL", config.ollama_base_url or "")
        set_key(str(ENV_PATH), "OLLAMA_MODEL", config.ollama_model or "")
        return {"message": "配置已保存"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/llm/test", response_model=TestResult)
async def test_llm_connection(config: LLMConfig):
    """测试 LLM 连接。"""
    try:
        if config.llm_type == "glm":
            return await _test_glm(config)
        if config.llm_type == "ollama":
            return await _test_ollama(config)
        if config.llm_type == "openai":
            return await _test_openai(config)
        return TestResult(success=False, error=f"未知的 LLM 类型: {config.llm_type}")
    except Exception as e:
        return TestResult(success=False, error=str(e))


async def _test_glm(config: LLMConfig) -> TestResult:
    """测试智谱 GLM 连接。"""
    try:
        from langchain_community.chat_models import ChatZhipuAI

        os.environ["ZHIPUAI_API_KEY"] = config.api_key or ""
        llm = ChatZhipuAI(
            model=config.model_name or "glm-4-flash",
            temperature=0.1,
        )
        response = llm.invoke("你好，请用一句话介绍自己")
        return TestResult(success=True, response=response.content[:100])
    except Exception as e:
        return TestResult(success=False, error=str(e))


async def _test_ollama(config: LLMConfig) -> TestResult:
    """测试 Ollama / llama.cpp 连接。"""
    import httpx

    base_url = (config.ollama_base_url or "http://127.0.0.1:11434").rstrip("/")
    target_model = (config.ollama_model or "").strip()

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{base_url}/api/tags")
            if resp.status_code == 200:
                data = resp.json()
                models = data.get("models", [])
                model_names = [m.get("name", "") for m in models if m.get("name")]
            else:
                resp = await client.get(f"{base_url}/v1/models")
                if resp.status_code == 200:
                    data = resp.json()
                    models = data.get("models", []) or data.get("data", [])
                    model_names = [
                        m.get("name") or m.get("id", "")
                        for m in models
                        if m
                    ]
                else:
                    return TestResult(success=False, error=f"服务返回状态码 {resp.status_code}")

            if target_model:
                found = any(name.lower() == target_model.lower() for name in model_names)
                if found:
                    return TestResult(success=True, response=f"模型 {target_model} 连接成功")
                available = ", ".join(model_names[:5]) if model_names else "无"
                return TestResult(
                    success=False,
                    error=f"未找到模型 {target_model}，可用模型: {available}",
                )
            return TestResult(success=True, response=f"服务连接成功，有 {len(model_names)} 个模型")
    except httpx.TimeoutException:
        return TestResult(success=False, error="连接超时，请检查服务是否运行")
    except Exception as e:
        return TestResult(success=False, error=f"连接失败: {str(e)}")


async def _test_openai(config: LLMConfig) -> TestResult:
    """测试 OpenAI 兼容接口。"""
    try:
        from langchain_openai import ChatOpenAI

        llm = ChatOpenAI(
            base_url=config.api_base_url,
            api_key=config.api_key,
            model=config.model_name,
            temperature=0.1,
        )
        response = llm.invoke("你好，请用一句话介绍自己")
        return TestResult(success=True, response=response.content[:100])
    except Exception as e:
        return TestResult(success=False, error=str(e))
