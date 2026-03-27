"""Embedding model wrapper - 支持 Ollama 和智谱 AI"""
from __future__ import annotations

import os
from typing import List, Sequence
import numpy as np
import requests


def resolve_ollama_base_url() -> str:
    base_url = os.getenv("OLLAMA_BASE_URL")
    if base_url:
        return base_url.rstrip("/")
    host = os.getenv("OLLAMA_HOST", "127.0.0.1")
    port = os.getenv("OLLAMA_PORT", "11434")
    return f"http://{host}:{port}"


def resolve_embedding_base_url() -> str:
    base_url = os.getenv("EMBEDDING_BASE_URL")
    if base_url:
        return base_url.rstrip("/")
    return resolve_ollama_base_url()


class EmbeddingModel:
    _instance = None
    _embed_cache: dict = {}
    _CACHE_MAX = 512

    def __new__(cls, *args, **kwargs):
        """单例模式，避免重复初始化"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, model: str | None = None, base_url: str | None = None, timeout: int = 300):
        if self._initialized:
            return
        self._initialized = True
        self.provider = os.getenv("EMBEDDING_PROVIDER", "ollama")
        self.model = model or os.getenv("EMBEDDING_MODEL", "bge-m3:latest")
        self.base_url = (base_url or resolve_embedding_base_url()).rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.output_dim: int | None = None
        
        # 智谱 AI 配置
        if self.provider == "zhipu":
            self.api_key = os.getenv("ZHIPUAI_API_KEY")
            if not self.api_key:
                raise ValueError("使用智谱 AI embedding 需要设置 ZHIPUAI_API_KEY")
            print(f"[Embedding] 使用智谱 AI Embedding-3 (1024维)")
        else:
            print(f"[Embedding] 使用 Ollama {self.model}")

    def embed_documents(self, texts: Sequence[str]) -> List[np.ndarray]:
        if self.provider == "zhipu":
            return self._embed_zhipu_batch(texts)
        return [self._embed_single(text) for text in texts]

    def embed_query(self, text: str) -> np.ndarray:
        # 缓存命中则直接返回
        cached = self._embed_cache.get(text)
        if cached is not None:
            return cached
        if self.provider == "zhipu":
            vec = self._embed_zhipu_single(text)
        else:
            vec = self._embed_single(text)
        # 超出上限时清空（简单策略）
        if len(self._embed_cache) >= self._CACHE_MAX:
            self._embed_cache.clear()
        self._embed_cache[text] = vec
        return vec

    def _embed_single(self, text: str) -> np.ndarray:
        """Ollama embedding"""
        payload = {"model": self.model, "prompt": text}
        url = f"{self.base_url}/api/embeddings"
        try:
            response = self.session.post(url, json=payload, timeout=self.timeout)
            response.raise_for_status()
            embedding = response.json().get("embedding")
            if not embedding:
                raise RuntimeError("Ollama 返回的 embedding 为空")
            vector = np.array(embedding, dtype=float)
            if self.output_dim is None:
                self.output_dim = vector.shape[0]
            return vector
        except requests.exceptions.Timeout:
            raise TimeoutError(
                f"Ollama embedding 超时（{self.timeout}秒）\n"
                f"AMD 显卡建议切换到智谱 AI:\n"
                f"在 .env 中设置: EMBEDDING_PROVIDER=zhipu"
            )
        except Exception as e:
            raise RuntimeError(f"Ollama embedding 失败: {str(e)}")

    def _embed_zhipu_single(self, text: str) -> np.ndarray:
        """智谱 AI embedding"""
        url = "https://open.bigmodel.cn/api/paas/v4/embeddings"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "embedding-3",
            "input": text
        }
        
        response = self.session.post(url, json=payload, headers=headers, timeout=30)
        response.raise_for_status()
        
        data = response.json()
        embedding = data["data"][0]["embedding"]
        vector = np.array(embedding, dtype=float)
        
        if self.output_dim is None:
            self.output_dim = len(embedding)
        
        return vector

    def _embed_zhipu_batch(self, texts: Sequence[str]) -> List[np.ndarray]:
        """智谱 AI 批量 embedding（最多 25 条/批）"""
        url = "https://open.bigmodel.cn/api/paas/v4/embeddings"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        # 分批处理
        batch_size = 25
        all_embeddings = []
        
        for i in range(0, len(texts), batch_size):
            batch = list(texts[i:i+batch_size])
            payload = {
                "model": "embedding-3",
                "input": batch
            }
            
            response = self.session.post(url, json=payload, headers=headers, timeout=60)
            response.raise_for_status()
            
            data = response.json()
            for item in data["data"]:
                embedding = np.array(item["embedding"], dtype=float)
                all_embeddings.append(embedding)
        
        return all_embeddings
