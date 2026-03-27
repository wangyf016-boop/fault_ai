"""
数据集嵌入路由 - 支持将 CSV 数据导入 Qdrant 和 Neo4j
"""

import os
import sys
import csv
import uuid
import json
import hashlib
import re
import unicodedata
import tempfile
import logging
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime
from enum import Enum

from fastapi import APIRouter, HTTPException, UploadFile, File, Form, BackgroundTasks
from pydantic import BaseModel

# 添加项目路径
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from app.retrievers.embedding import EmbeddingModel
from app.retrievers.qdrant_store import QdrantVectorStore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/datasets", tags=["datasets"])

# ── Collection 注册表（活跃/停用） ─────────────────────────────
import json
import threading

REGISTRY_FILE = ROOT / "collection_registry.json"
_registry_lock = threading.Lock()


def _load_registry() -> list:
    """读取活跃 collection 列表，注册表不存在时返回空列表。"""
    with _registry_lock:
        if REGISTRY_FILE.exists():
            try:
                data = json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
                return data.get("active", [])
            except Exception:
                pass
    return []


def _save_registry(active: list) -> None:
    """持久化活跃 collection 列表。"""
    with _registry_lock:
        REGISTRY_FILE.write_text(
            json.dumps({"active": active}, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
    # 刷新 Qdrant 缓存
    try:
        from app.retrievers.qdrant_search import invalidate_qdrant_cache
        invalidate_qdrant_cache()
    except Exception:
        pass
# ────────────────────────────────────────────────────────────────

# 存储嵌入任务状态
embedding_tasks: Dict[str, Dict] = {}


class EmbeddingTarget(str, Enum):
    QDRANT = "qdrant"
    NEO4J = "neo4j"
    BOTH = "both"


class EmbeddingTaskStatus(BaseModel):
    task_id: str
    status: str
    progress: int
    total: int
    message: str
    result: Optional[Dict] = None


class DatasetEmbeddingService:
    """数据集嵌入服务"""
    
    # 列名映射：支持多种 CSV 格式
    # NOTE: 优先级由列表顺序决定，_get_field 返回第一个匹配列的值
    COLUMN_ALIASES = {
        'line': ['Line', '区域', '产线', 'line', '设备'],
        'station': ['Station', '站位', '工位', 'station', '设备'],  # 加 '设备' → 当 '区域' 已占 line 时，设备名落到 station
        'problem': ['Problem Description', '故障现象', '故障的现象描述', '问题描述', '问题', 'problem'],  # 加 '故障的现象描述'
        # 优先使用“预测故障原因”，若为空再回退到“根本原因种类”等列
        'cause': ['预测故障原因', 'Cause Analysis', '故障原因', '根本原因种类', '原因分析', '原因', 'cause'],
        'action': ['Containment Action', '解决对策', '应对措施', '措施', 'action'],
        'plan': ['Action plan', '行动计划', '计划', 'plan', '行动状态'],
        'date': ['Started DateTime', '日期', 'date', '预计关闭日期', '实际关闭日期'],
        'year': ['年', 'year', 'Year'],
        'month': ['月', 'month', 'Month'],
        'day': ['日', 'day', 'Day'],
    }
    
    def __init__(self):
        self.embedder = EmbeddingModel()
        self.vector_size = 1024
        self._neo4j_driver = None
    
    def _get_field(self, row: Dict, field_key: str) -> str:
        """从 row 中获取字段值，支持多种列名"""
        aliases = self.COLUMN_ALIASES.get(field_key, [field_key])
        for alias in aliases:
            if alias in row and row[alias]:
                return str(row[alias]).strip()
        return ''
    
    def _get_date(self, row: Dict) -> str:
        """获取日期字段，优先使用年/月/日分开的格式"""
        # 优先尝试合并年月日字段（更准确）
        year = self._get_field(row, 'year')
        month = self._get_field(row, 'month')
        day = self._get_field(row, 'day')
        
        if year and month and day:
            return f"{year}-{month.zfill(2)}-{day.zfill(2)}"
        elif year and month:
            return f"{year}-{month.zfill(2)}"
        elif year:
            return year
        
        # 如果没有年月日字段，尝试直接获取日期字段
        date_val = self._get_field(row, 'date')
        if date_val:
            # 检查是否是有效日期格式（而不是时间格式如"7:00"）
            if ':' not in date_val and len(date_val) >= 6:
                return date_val
        
        return ''

    @staticmethod
    def _hash_norm(value: str) -> str:
        text = unicodedata.normalize("NFKC", str(value or "")).strip()
        return re.sub(r"\s+", "", text)

    def _build_source_row_hash(self, row: Dict) -> str:
        payload = {
            "schema_version": "v2_area_equipment_component_problem",
            "row": {
                "区域": self._hash_norm(self._get_field(row, "line")),
                "设备": self._hash_norm(self._get_field(row, "station")),
                "故障的现象描述": self._hash_norm(self._get_field(row, "problem")),
                "解决对策": self._hash_norm(self._get_field(row, "action")),
                "预测故障原因": self._hash_norm(self._get_field(row, "cause")),
                "日期": self._hash_norm(self._get_date(row)),
            },
        }
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @staticmethod
    def _extract_year_from_text(text: str) -> str:
        m = re.search(r"(19|20)\d{2}", str(text or ""))
        return m.group(0) if m else ""
    
    @property
    def neo4j_driver(self):
        if self._neo4j_driver is None:
            try:
                from neo4j import GraphDatabase
                uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
                user = os.getenv("NEO4J_USERNAME", "neo4j")
                password = os.getenv("NEO4J_PASSWORD", "password")
                self._neo4j_driver = GraphDatabase.driver(uri, auth=(user, password))
            except Exception as e:
                logger.error(f"Neo4j 连接失败: {e}")
                raise
        return self._neo4j_driver
    
    def parse_csv(self, file_path: str) -> List[Dict]:
        data = []
        source_name = Path(file_path).name
        source_year = self._extract_year_from_text(source_name)
        # 尝试多种编码
        encodings = ['utf-8-sig', 'utf-8', 'gbk', 'gb2312', 'gb18030', 'latin-1']
        content = None
        
        for encoding in encodings:
            try:
                with open(file_path, 'r', encoding=encoding) as f:
                    content = f.read()
                logger.info(f"CSV 文件使用 {encoding} 编码成功读取")
                break
            except UnicodeDecodeError:
                continue
        
        if content is None:
            raise ValueError("无法识别 CSV 文件编码，请确保文件是 UTF-8 或 GBK 编码")
        
        import io
        reader = csv.DictReader(io.StringIO(content))
        for idx, row in enumerate(reader, start=2):
            cleaned = {k.strip(): (v.strip() if v else '') for k, v in row.items()}
            if not cleaned.get('id'):
                cleaned['id'] = str(idx - 1)
            cleaned['_source_file'] = source_name
            cleaned['_source_year'] = source_year
            cleaned['_source_row'] = str(idx)
            data.append(cleaned)
        logger.info(f"解析 CSV 完成，共 {len(data)} 条记录")
        return data
    
    def prepare_text(self, row: Dict) -> str:
        parts = []
        field_labels = {
            'problem': '问题',
            'cause': '原因',
            'action': '措施',
            'plan': '计划',
            'station': '工位',
            'line': '产线',
        }
        for field_key, label in field_labels.items():
            value = self._get_field(row, field_key)
            if value:
                parts.append(f"{label}: {value}")
        return " | ".join(parts) if parts else "无有效信息"

    def embed_to_qdrant(self, data: List[Dict], collection_name: str, 
                        batch_size: int = 50, progress_callback=None) -> Dict:
        import uuid as _uuid
        store = QdrantVectorStore(collection_name=collection_name)
        store.ensure_collection(self.vector_size)
        
        texts = [self.prepare_text(row) for row in data]
        total = len(texts)
        success_count = 0
        
        for i in range(0, total, batch_size):
            batch_texts = texts[i:i+batch_size]
            batch_data = data[i:i+batch_size]
            
            try:
                embeddings = self.embedder.embed_documents(batch_texts)
                items = []
                for idx, (row, emb) in enumerate(zip(batch_data, embeddings)):
                    source_year = str(
                        row.get('_source_year')
                        or self._get_field(row, 'year')
                        or self._extract_year_from_text(str(row.get('_source', '') or row.get('_source_file', '')))
                        or ''
                    ).strip()
                    source_row = str(row.get('_source_row') or row.get('source_row') or row.get('row') or row.get('row_no') or '').strip()
                    source_row_hash = self._build_source_row_hash(row)
                    items.append({
                        'id': str(_uuid.uuid4()),  # UUID 防止覆盖
                        'vector': emb.tolist(),
                        'record_id': str(row.get('id', i + idx)),
                        'line': self._get_field(row, 'line'),
                        'station': self._get_field(row, 'station'),
                        'problem': self._get_field(row, 'problem')[:500],
                        'cause': self._get_field(row, 'cause')[:500],
                        'action': self._get_field(row, 'action')[:500],
                        'plan': self._get_field(row, 'plan')[:500],
                        'date': self._get_date(row),
                        'source_year': source_year,
                        'source_row': source_row,
                        'source_row_hash': source_row_hash,
                        'source_file': str(row.get('_source_file', '') or row.get('_source', '') or ''),
                    })
                store.upsert(items)
                success_count += len(batch_texts)
                if progress_callback:
                    progress_callback(min(i + batch_size, total), total)
            except Exception as e:
                logger.error(f"Qdrant 批次失败: {e}")
        
        return {'target': 'qdrant', 'collection': collection_name, 'total': total, 'success': success_count}
    
    def _get_embedding_safe(self, text: str) -> Optional[List[float]]:
        import math
        if not text or text.strip().lower() in ['', 'nan', 'none']:
            return None
        try:
            emb = self.embedder.embed_query(text).tolist()
            if any(math.isnan(x) or math.isinf(x) for x in emb):
                return None
            return emb
        except:
            return None
    
    def embed_to_neo4j(self, data: List[Dict], clear_existing: bool = False, 
                       progress_callback=None) -> Dict:
        driver = self.neo4j_driver
        total = len(data)
        success_count = 0
        
        with driver.session() as session:
            if clear_existing:
                session.run("MATCH (n) DETACH DELETE n")
                logger.info("已清空 Neo4j 数据库")
            
            # 创建约束
            for c in [
                "CREATE CONSTRAINT line_name IF NOT EXISTS FOR (l:Line) REQUIRE l.name IS UNIQUE",
                "CREATE CONSTRAINT station_name IF NOT EXISTS FOR (s:Station) REQUIRE s.name IS UNIQUE",
            ]:
                try:
                    session.run(c)
                except:
                    pass
        
        for i, row in enumerate(data):
            try:
                self._import_neo4j_record(row)
                success_count += 1
                if progress_callback and (i + 1) % 10 == 0:
                    progress_callback(i + 1, total)
            except Exception as e:
                logger.error(f"Neo4j 记录失败: {e}")
        
        if progress_callback:
            progress_callback(total, total)
        
        return {'target': 'neo4j', 'total': total, 'success': success_count}
    
    def _import_neo4j_record(self, row: Dict):
        record_id = row.get('id', '')
        line = self._get_field(row, 'line') or 'Unknown'
        station = self._get_field(row, 'station') or 'Unknown'
        problem_desc = self._get_field(row, 'problem')
        cause_analysis = self._get_field(row, 'cause')
        containment_action = self._get_field(row, 'action')
        action_plan = self._get_field(row, 'plan')
        
        problem_emb = self._get_embedding_safe(problem_desc)
        
        with self.neo4j_driver.session() as session:
            session.run("""
                MERGE (l:Line {name: $line})
                MERGE (s:Station {name: $station})
                MERGE (s)-[:ON_LINE]->(l)
            """, line=line, station=station)
            
            session.run("""
                MERGE (p:Problem {id: $id})
                SET p.record_id = $record_id,
                    p.description = $description,
                    p.embedding = $embedding
            """, id=f"{record_id}_problem", record_id=record_id,
                description=problem_desc, embedding=problem_emb)
            
            session.run("""
                MATCH (p:Problem {id: $problem_id})
                MATCH (s:Station {name: $station})
                MERGE (p)-[:OCCURRED_AT_STATION]->(s)
            """, problem_id=f"{record_id}_problem", station=station)
            
            if cause_analysis:
                cause_emb = self._get_embedding_safe(cause_analysis)
                session.run("""
                    MERGE (c:Cause {id: $id})
                    SET c.description = $description,
                        c.embedding = $embedding
                """, id=f"{record_id}_cause", description=cause_analysis, embedding=cause_emb)
                session.run("""
                    MATCH (p:Problem {id: $problem_id})
                    MATCH (c:Cause {id: $cause_id})
                    MERGE (p)-[:CAUSED_BY]->(c)
                """, problem_id=f"{record_id}_problem", cause_id=f"{record_id}_cause")
            
            if containment_action:
                action_emb = self._get_embedding_safe(containment_action)
                session.run("""
                    MERGE (ca:ContainmentAction {id: $id})
                    SET ca.description = $description,
                        ca.embedding = $embedding
                """, id=f"{record_id}_containment", description=containment_action, embedding=action_emb)
                session.run("""
                    MATCH (p:Problem {id: $problem_id})
                    MATCH (ca:ContainmentAction {id: $containment_id})
                    MERGE (p)-[:CONTAINED_BY]->(ca)
                """, problem_id=f"{record_id}_problem", containment_id=f"{record_id}_containment")
    
    def close(self):
        if self._neo4j_driver:
            self._neo4j_driver.close()


# 单例服务
_service_instance = None

def get_embedding_service() -> DatasetEmbeddingService:
    global _service_instance
    if _service_instance is None:
        _service_instance = DatasetEmbeddingService()
    return _service_instance


# ===================== API 端点 ===================== #

def run_embedding_task(task_id: str, file_path: str, target: str, collection_name: str, clear_neo4j: bool):
    """后台执行嵌入任务"""
    try:
        embedding_tasks[task_id]['status'] = 'processing'
        service = get_embedding_service()
        
        data = service.parse_csv(file_path)
        embedding_tasks[task_id]['total'] = len(data)
        
        def progress_callback(current, total):
            embedding_tasks[task_id]['progress'] = current
            embedding_tasks[task_id]['total'] = total
        
        results = []
        
        if target in ['qdrant', 'both']:
            result = service.embed_to_qdrant(data, collection_name, progress_callback=progress_callback)
            results.append(result)
        
        if target in ['neo4j', 'both']:
            result = service.embed_to_neo4j(data, clear_existing=clear_neo4j, progress_callback=progress_callback)
            results.append(result)
        
        embedding_tasks[task_id]['status'] = 'completed'
        embedding_tasks[task_id]['result'] = {'targets': results, 'records': len(data)}
        embedding_tasks[task_id]['message'] = '嵌入完成'
        
    except Exception as e:
        embedding_tasks[task_id]['status'] = 'failed'
        embedding_tasks[task_id]['message'] = str(e)
        logger.error(f"嵌入任务失败: {e}")
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)


@router.post("/embed")
async def embed_dataset(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    target: str = Form("qdrant"),
    collection_name: Optional[str] = Form(None),
    clear_neo4j: bool = Form(False)
):
    """上传并嵌入数据集"""
    if not file.filename.endswith('.csv'):
        raise HTTPException(status_code=400, detail="仅支持 CSV 文件")
    
    temp_dir = tempfile.mkdtemp()
    file_path = os.path.join(temp_dir, file.filename)
    
    with open(file_path, 'wb') as f:
        content = await file.read()
        f.write(content)
    
    task_id = str(uuid.uuid4())
    embedding_tasks[task_id] = {
        'task_id': task_id,
        'status': 'pending',
        'progress': 0,
        'total': 0,
        'message': '任务已创建',
        'result': None
    }
    
    # 未填集合名时，用文件名（去掉 .csv，空格换下划线）作为默认 collection 名
    default_name = Path(file.filename).stem.replace(' ', '_').replace('-', '_')
    coll = collection_name or default_name or os.getenv("QDRANT_COLLECTION", "production_issues")
    background_tasks.add_task(run_embedding_task, task_id, file_path, target, coll, clear_neo4j)
    
    return {"task_id": task_id, "message": "嵌入任务已启动"}


@router.get("/embed/{task_id}", response_model=EmbeddingTaskStatus)
async def get_embedding_status(task_id: str):
    """获取嵌入任务状态"""
    if task_id not in embedding_tasks:
        raise HTTPException(status_code=404, detail="任务不存在")
    return embedding_tasks[task_id]


@router.get("/collections/active")
async def get_active_collections():
    """获取当前活跃（参与搜索）的 collection 列表"""
    return {"active": _load_registry()}


@router.post("/collections/{name}/toggle")
async def toggle_collection(name: str):
    """切换一个 collection 的启用/停用状态"""
    try:
        from qdrant_client import QdrantClient
        host = os.getenv("QDRANT_HOST", "localhost")
        port = int(os.getenv("QDRANT_PORT", "6333"))
        client = QdrantClient(host=host, port=port)
        all_names = [c.name for c in client.get_collections().collections]
        if name not in all_names:
            raise HTTPException(status_code=404, detail=f"集合 '{name}' 不存在")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    active = _load_registry()
    if name in active:
        active.remove(name)
        is_active = False
    else:
        active.append(name)
        is_active = True
    _save_registry(active)
    logger.info(f"Collection '{name}' 状态切换为: {'启用' if is_active else '停用'}")
    return {"name": name, "active": is_active}


@router.get("/collections")
async def list_collections():
    """列出 Qdrant 集合（含 active 状态）"""
    try:
        from qdrant_client import QdrantClient
        host = os.getenv("QDRANT_HOST", "localhost")
        port = int(os.getenv("QDRANT_PORT", "6333"))
        client = QdrantClient(host=host, port=port)
        collections = client.get_collections().collections
        active_set = set(_load_registry())
        return {"collections": [{"name": c.name, "active": c.name in active_set} for c in collections]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/collections/{name}/info")
async def get_collection_info(name: str):
    """获取集合详情"""
    try:
        store = QdrantVectorStore(collection_name=name)
        info = store.info()
        return info
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/collections/{name}/chunks")
async def get_collection_chunks(name: str, limit: int = 6, offset: int = 0):
    """获取集合中部分切片内容，用于预览"""
    limit = max(1, min(limit, 20))
    offset = max(0, offset)
    try:
        store = QdrantVectorStore(collection_name=name)
        chunks = store.list_chunks(limit=limit, offset=offset)
        return {"chunks": chunks, "count": len(chunks)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/collections/{name}")
async def delete_collection(name: str):
    """删除 Qdrant 集合"""
    try:
        from qdrant_client import QdrantClient
        host = os.getenv("QDRANT_HOST", "localhost")
        port = int(os.getenv("QDRANT_PORT", "6333"))
        client = QdrantClient(host=host, port=port)
        
        # 检查集合是否存在
        collections = [c.name for c in client.get_collections().collections]
        if name not in collections:
            raise HTTPException(status_code=404, detail=f"集合 '{name}' 不存在")
        
        # 删除集合
        client.delete_collection(collection_name=name)

        # 同步清理 active 注册表
        active = _load_registry()
        if name in active:
            active.remove(name)
            _save_registry(active)

        logger.info(f"已删除集合: {name}")
        
        return {"message": f"集合 '{name}' 已删除", "name": name}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除集合失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
