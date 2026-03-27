"""Qdrant vector store wrapper"""
from __future__ import annotations

import logging
import os
from typing import Dict, Iterable, List, Optional, Sequence, Union
from urllib.parse import urljoin
import requests

from qdrant_client import QdrantClient
from qdrant_client.http.exceptions import UnexpectedResponse
from qdrant_client.models import Distance, PointStruct, VectorParams, Filter
from qdrant_client.http.models import SearchRequest
from math import sqrt

logger = logging.getLogger(__name__)


class QdrantVectorStore:
    def __init__(
        self,
        collection_name: str,
        host: Optional[str] = None,
        port: Optional[Union[str, int]] = None,
        prefer_grpc: bool = False,
        distance: Distance = Distance.COSINE,
    ):
        self.collection_name = collection_name
        self.host = host or os.getenv("QDRANT_HOST", "localhost")
        self.port = int(port or os.getenv("QDRANT_PORT", "6333"))
        self.distance = distance
        self.client = QdrantClient(host=self.host, port=self.port, prefer_grpc=prefer_grpc)

    def ensure_collection(self, vector_size: int) -> None:
        collections = self.client.get_collections().collections
        if any(c.name == self.collection_name for c in collections):
            return
        self.client.create_collection(
            collection_name=self.collection_name,
            vectors_config=VectorParams(size=vector_size, distance=self.distance),
        )

    def upsert(self, items: Sequence[Dict]) -> None:
        if not items:
            return
        points = []
        def _maybe_normalize(vec: List[float]) -> List[float]:
            # If collection uses COSINE distance, normalize vectors to unit length for reliable cosine similarity
            if self.distance == Distance.COSINE:
                norm = sqrt(sum(x * x for x in vec))
                if norm > 0:
                    return [x / norm for x in vec]
                return vec
            return vec

        for item in items:
            vec = item.get("vector")
            if vec is not None:
                vec = _maybe_normalize(vec)
            points.append(
            PointStruct(
                id=item["id"],
                vector=vec,
                payload={k: v for k, v in item.items() if k not in {"id", "vector"}}
            )
            )
        self.client.upsert(collection_name=self.collection_name, points=points)

    def search(
        self,
        query_vectors: Iterable[List[float]],
        *,
        limit: int = 5,
        score_threshold: Optional[float] = None,
        query_filter: Optional[Filter] = None,
    ) -> List[List[Dict]]:
        results: List[List[Dict]] = []
        for query_vector in query_vectors:
            # normalize query vector when using COSINE distance
            if self.distance == Distance.COSINE and query_vector is not None:
                norm = sqrt(sum(x * x for x in query_vector))
                if norm > 0:
                    query_vector = [x / norm for x in query_vector]
            # 使用新版 qdrant_client API (query_points)
            if hasattr(self.client, "query_points"):
                response = self.client.query_points(
                    collection_name=self.collection_name,
                    query=query_vector,
                    limit=limit,
                    score_threshold=score_threshold,
                    query_filter=query_filter,
                )
                hits = response.points
            elif hasattr(self.client, "search"):
                hits = self.client.search(
                    collection_name=self.collection_name,
                    query_vector=query_vector,
                    limit=limit,
                    score_threshold=score_threshold,
                    query_filter=query_filter,
                )
            else:
                hits = self._http_search(query_vector, limit=limit, score_threshold=score_threshold)
            results.append([self._format_hit(hit) for hit in hits])
        return results

    def _http_search(self, vector: List[float], *, limit: int, score_threshold: Optional[float]) -> List[Dict]:
        request = SearchRequest(vector=vector, limit=limit, with_payload=True, score_threshold=score_threshold)
        base_url = f"http://{self.host}:{self.port}"
        url = urljoin(base_url + '/', f"collections/{self.collection_name}/points/search")
        response = requests.post(url, json=request.dict(exclude_none=True), timeout=30)
        response.raise_for_status()
        return response.json().get("result", []) or []

    def _format_hit(self, hit: Union[Dict, object]) -> Dict:
        hit_id, payload = self._extract_payload(hit)
        score = hit.get("score") if isinstance(hit, dict) else getattr(hit, "score", None)
        # For COSINE distance qdrant typically returns similarity score (higher is better)
        # Provide distance only for COSINE as (1 - score). For other metrics leave distance as None
        distance_val = None
        try:
            if score is not None and self.distance == Distance.COSINE:
                distance_val = 1 - float(score)
        except Exception:
            distance_val = None
        return {"id": hit_id, "score": score, "distance": distance_val, **payload}

    @staticmethod
    def _extract_payload(point: Union[Dict, object]) -> tuple[Optional[Union[str, int]], Dict]:
        if isinstance(point, dict):
            payload = point.get("payload") or {}
            point_id = point.get("id")
        else:
            payload = getattr(point, "payload", {}) or {}
            point_id = getattr(point, "id", None)
        return point_id, payload

    def list_chunks(self, limit: int = 10, offset: int = 0, *, with_vector: bool = False) -> List[Dict]:
        """获取集合中的切片数据用于预览
        
        Args:
            limit: 返回的最大记录数
            offset: 跳过的记录数（通过多次 scroll 实现）
            with_vector: 是否返回向量数据
        """
        if limit < 1:
            limit = 1
        try:
            # Qdrant scroll 的 offset 参数是游标（point ID），不是整数偏移
            # 需要传 None 从头开始，然后通过返回的 next_page_offset 分页
            scroll_res = self.client.scroll(
                collection_name=self.collection_name,
                limit=limit + offset,  # 先获取足够多的数据
                offset=None,  # 从头开始
                with_payload=True,
                with_vectors=with_vector,
            )
            
            if scroll_res is None:
                points = []
            elif isinstance(scroll_res, tuple):
                # scroll 返回 (points, next_page_offset) 元组
                points = scroll_res[0] or []
            else:
                points = getattr(scroll_res, "points", None) or getattr(scroll_res, "result", None)
                if points is None:
                    try:
                        points = list(scroll_res)
                    except TypeError:
                        points = []
            
            # 手动实现 offset 跳过
            points = points[offset:offset + limit] if offset > 0 else points[:limit]
            
        except Exception as exc:
            logger.error(f"Failed to list chunks for {self.collection_name}: {exc}")
            return []

        formatted_chunks = []
        for point in points:
            point_id, payload = self._extract_payload(point)
            formatted_chunks.append({"id": point_id, **payload})
        return formatted_chunks

    def scroll_by_filter(
        self,
        query_filter: Optional[Filter] = None,
        limit: int = 200,
    ) -> List[Dict]:
        """使用 scroll 接口按过滤条件检索所有匹配记录（无向量排序）。

        适合枚举型查询（如「某设备出过哪些故障」），可取出所有匹配条目，
        而不受向量相似度排序的影响。
        """
        all_points: list = []
        offset = None
        per_page = min(100, limit)  # 每次 scroll 取的批量大小

        while len(all_points) < limit:
            try:
                # 优先使用 scroll_filter（旧版 qdrant_client），兼容新版 query_filter
                try:
                    scroll_res = self.client.scroll(
                        collection_name=self.collection_name,
                        limit=per_page,
                        offset=offset,
                        scroll_filter=query_filter,
                        with_payload=True,
                        with_vectors=False,
                    )
                except TypeError:
                    scroll_res = self.client.scroll(
                        collection_name=self.collection_name,
                        limit=per_page,
                        offset=offset,
                        query_filter=query_filter,
                        with_payload=True,
                        with_vectors=False,
                    )

                if isinstance(scroll_res, tuple):
                    points, next_offset = scroll_res
                else:
                    points = getattr(scroll_res, "points", None) or []
                    next_offset = getattr(scroll_res, "next_page_offset", None)

                if not points:
                    break

                all_points.extend(points)

                if next_offset is None or len(all_points) >= limit:
                    break
                offset = next_offset

            except Exception as exc:
                logger.error(f"scroll_by_filter failed for {self.collection_name}: {exc}")
                break

        results: List[Dict] = []
        for point in all_points[:limit]:
            point_id, payload = self._extract_payload(point)
            results.append({"id": point_id, "score": None, "distance": None, **payload})
        return results

    def info(self) -> Dict:
        """获取集合详细信息"""
        try:
            collection_info = self.client.get_collection(collection_name=self.collection_name)
            
            # 处理向量配置（兼容不同的 Qdrant 版本）
            vectors_config = collection_info.config.params.vectors
            if hasattr(vectors_config, 'size'):
                vector_size = vectors_config.size
                distance = vectors_config.distance.value if hasattr(vectors_config.distance, 'value') else str(vectors_config.distance)
            elif isinstance(vectors_config, dict):
                first_vector = next(iter(vectors_config.values()))
                vector_size = first_vector.size
                distance = first_vector.distance.value if hasattr(first_vector.distance, 'value') else str(first_vector.distance)
            else:
                vector_size = None
                distance = None
            
            points_count = collection_info.points_count or 0
            
            return {
                "name": self.collection_name,
                "points": points_count,
                "docs": points_count,
                "chunks": points_count,
                "status": collection_info.status.value if hasattr(collection_info.status, 'value') else str(collection_info.status),
                "distance": distance
            }
        except UnexpectedResponse as e:
            if "not found" in str(e).lower() or e.status_code == 404:
                return {"name": self.collection_name, "exists": False, "docs": 0, "chunks": 0, "error": "Collection not found"}
            raise
        except Exception as e:
            return {
                "name": self.collection_name,
                "points": 0,
                "docs": 0,
                "chunks": 0,
                "status": "ERROR",
                "error": str(e)
            }
