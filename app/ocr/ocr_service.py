"""
OCR Service - PDF 文档 OCR 处理服务
基于 MinerU VLM 和 PaddleOCR
- 处理任务：内存存储（刷新清除）
- 成功结果：数据库持久化
"""

import os
import re
import shutil
import sqlite3
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from enum import Enum
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import cv2
import numpy as np


# ============ 配置区域 ============
UPLOAD_FOLDER = Path("./ocr_uploads")
OUTPUT_FOLDER = Path("./ocr_output")
DB_PATH = Path("./app/db/ocr_results.db")
MAX_PARALLEL_TASKS = 2  # CPU 模式下同时处理的任务数
# =================================

UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
OUTPUT_FOLDER.mkdir(parents=True, exist_ok=True)


class TaskStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class OcrTask:
    """OCR 处理任务 - 内存存储"""
    id: str
    filename: str
    status: TaskStatus = TaskStatus.PENDING
    progress: int = 0
    stage: str = ""
    created_at: str = ""
    error: str = ""

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "filename": self.filename,
            "status": self.status.value,
            "progress": self.progress,
            "stage": self.stage,
            "createdAt": self.created_at,
            "error": self.error
        }


@dataclass
class OcrResult:
    """OCR 结果数据类 - 数据库持久化"""
    id: int
    filename: str
    package_id: Optional[str]
    uch_codes: List[str]
    status: str
    created_at: str

class OcrService:
    """OCR 服务管理类"""

    def __init__(self):
        self._ocr_engine = None
        self._lock = threading.Lock()
        # 任务在内存中
        self._tasks: Dict[str, OcrTask] = {}
        self._task_counter = 0
        # 任务处理线程池（CPU 模式下并行处理多个任务）
        self._task_executor = ThreadPoolExecutor(max_workers=MAX_PARALLEL_TASKS)
        # 初始化数据库
        self._init_database()

    def _get_ocr_engine(self):
        """懒加载 OCR 引擎"""
        if self._ocr_engine is None:
            try:
                from mineru.model.ocr.pytorch_paddle import PytorchPaddleOCR

                self._ocr_engine = PytorchPaddleOCR(lang="ch")
                print("[OCR] PytorchPaddleOCR 初始化成功")
            except ImportError as e:
                print(f"[OCR] PytorchPaddleOCR 未安装: {e}")
            except Exception as e:
                print(f"[OCR] PytorchPaddleOCR 初始化失败: {e}")
        return self._ocr_engine

    def _init_database(self):
        """初始化数据库"""
        conn = sqlite3.connect(str(DB_PATH))
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ocr_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL,
                package_id TEXT,
                uch_codes TEXT,
                status TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        conn.close()

    def _save_result_to_db(
        self, filename: str, package_id: str, uch_codes: list, status: str
    ) -> int:
        """保存结果到数据库"""
        conn = sqlite3.connect(str(DB_PATH))
        cursor = conn.cursor()
        uch_codes_str = ",".join(uch_codes) if uch_codes else ""
        cursor.execute(
            """
            INSERT INTO ocr_results (filename, package_id, uch_codes, status, created_at)
            VALUES (?, ?, ?, ?, ?)
        """,
            (filename, package_id, uch_codes_str, status, datetime.now()),
        )
        conn.commit()
        result_id = cursor.lastrowid
        conn.close()
        return result_id

    # ============ 任务管理（内存） ============

    def create_task(self, filename: str, pdf_bytes: bytes) -> OcrTask:
        """创建新的 OCR 任务"""
        with self._lock:
            self._task_counter += 1
            task_id = f"task-{self._task_counter}"

        task = OcrTask(
            id=task_id,
            filename=filename,
            created_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
        )

        # 保存 PDF 文件
        pdf_path = UPLOAD_FOLDER / f"{task_id}_{filename}"
        pdf_path.write_bytes(pdf_bytes)

        with self._lock:
            self._tasks[task_id] = task

        return task

    def submit_task(self, task_id: str):
        """提交任务到线程池执行"""
        self._task_executor.submit(self.process_task, task_id)

    def get_task(self, task_id: str) -> Optional[OcrTask]:
        """获取任务"""
        return self._tasks.get(task_id)

    def get_all_tasks(self) -> List[OcrTask]:
        """获取所有任务"""
        return list(self._tasks.values())

    def delete_task(self, task_id: str) -> bool:
        """删除任务"""
        with self._lock:
            if task_id in self._tasks:
                del self._tasks[task_id]
                return True
            return False

    # ============ 任务处理 ============

    def _extract_images_from_pdf(self, pdf_path: Path, image_dir: Path) -> List[Path]:
        """快速从 PDF 提取嵌入图片（不经过 VLM）"""
        try:
            import fitz  # PyMuPDF
            doc = fitz.open(str(pdf_path))
            image_paths = []
            for page_num in range(len(doc)):
                page = doc[page_num]
                images = page.get_images(full=True)
                for img_idx, img in enumerate(images):
                    xref = img[0]
                    pix = fitz.Pixmap(doc, xref)
                    if pix.n - pix.alpha > 3:  # CMYK
                        pix = fitz.Pixmap(fitz.csRGB, pix)
                    img_path = image_dir / f"page{page_num}_img{img_idx}.png"
                    pix.save(str(img_path))
                    image_paths.append(img_path)
            doc.close()
            return image_paths
        except Exception as e:
            print(f"[OCR] PyMuPDF 提取图片失败: {e}")
            return []

    def process_task(self, task_id: str):
        """处理 OCR 任务 - 优化版：VLM 和图片 OCR 并行"""
        task = self._tasks.get(task_id)
        if not task:
            return

        task.status = TaskStatus.PROCESSING
        task.progress = 0
        task.stage = "初始化..."

        pdf_path = UPLOAD_FOLDER / f"{task_id}_{task.filename}"
        if not pdf_path.exists():
            task.status = TaskStatus.FAILED
            task.error = "PDF 文件不存在"
            return

        pdf_output_dir = OUTPUT_FOLDER / task_id
        pdf_output_dir.mkdir(parents=True, exist_ok=True)
        image_dir = pdf_output_dir / "images"
        image_dir.mkdir(parents=True, exist_ok=True)
        
        # 用于快速图片提取的目录
        quick_image_dir = pdf_output_dir / "quick_images"
        quick_image_dir.mkdir(parents=True, exist_ok=True)

        try:
            from mineru.backend.vlm.vlm_analyze import doc_analyze
            from mineru.backend.vlm.vlm_middle_json_mkcontent import union_make
            from mineru.data.data_reader_writer import FileBasedDataWriter
            from mineru.utils.enum_class import MakeMode
        except ImportError as e:
            task.status = TaskStatus.FAILED
            task.error = f"MinerU 未安装: {e}"
            self._save_result_to_db(task.filename, None, [], f"失败: {task.error}")
            return

        try:
            pdf_bytes = pdf_path.read_bytes()
            
            # 并行执行：VLM 解析 + 图片 OCR
            task.stage = "并行处理: VLM解析 + 图片OCR..."
            task.progress = 10
            
            vlm_result = {}
            ocr_uch_codes = []
            
            def run_vlm():
                """VLM 解析任务"""
                nonlocal vlm_result
                image_writer = FileBasedDataWriter(str(image_dir))
                middle_json, _ = doc_analyze(
                    pdf_bytes=pdf_bytes,
                    image_writer=image_writer,
                    backend="transformers",
                    model_path=None,
                )
                pdf_info = middle_json["pdf_info"]
                md_content = union_make(pdf_info, MakeMode.MM_MD, "images")
                vlm_result = {
                    "md_content": md_content,
                    "package_id": self._extract_package_id(md_content),
                    "uch_codes": self._extract_uch_from_text(md_content),
                }
            
            def run_ocr():
                """快速图片 OCR 任务"""
                nonlocal ocr_uch_codes
                # 先快速提取 PDF 中的嵌入图片
                extracted_images = self._extract_images_from_pdf(pdf_path, quick_image_dir)
                if extracted_images:
                    ocr_uch_codes = self._extract_uch_codes_from_images(quick_image_dir)
            
            # 并行执行
            with ThreadPoolExecutor(max_workers=2) as executor:
                vlm_future = executor.submit(run_vlm)
                ocr_future = executor.submit(run_ocr)
                
                # 等待完成
                vlm_future.result()
                task.progress = 70
                ocr_future.result()
                task.progress = 90

            # 合并结果：优先用 VLM 提取的，OCR 作为补充
            task.stage = "合并结果..."
            package_id = vlm_result.get("package_id")
            uch_codes = vlm_result.get("uch_codes", [])
            
            # 如果 VLM 没提取到 UCH，用 OCR 结果
            if not uch_codes:
                uch_codes = ocr_uch_codes
            else:
                # 合并去重
                uch_codes = list(set(uch_codes + ocr_uch_codes))

            # 保存到数据库
            self._save_result_to_db(task.filename, package_id, uch_codes, "成功")

            task.status = TaskStatus.COMPLETED
            task.progress = 100
            task.stage = "完成"

            # 清理临时文件
            shutil.rmtree(pdf_output_dir)
            pdf_path.unlink()

        except Exception as e:
            import traceback

            traceback.print_exc()
            task.status = TaskStatus.FAILED
            task.error = str(e)
            self._save_result_to_db(task.filename, None, [], f"失败: {e}")
            if pdf_output_dir.exists():
                shutil.rmtree(pdf_output_dir)
            if pdf_path.exists():
                pdf_path.unlink()

    def _extract_uch_from_text(self, text: str) -> list:
        """从文本中提取 UCH 编码"""
        return list(set(re.findall(r"UCH[A-Z]?\d+", text)))

    def _extract_package_id(self, md_content: str) -> str:
        """从 Markdown 内容中提取 Package-ID"""
        match = re.search(r"Package-ID:?\s*(S\d+)", md_content)
        return match.group(1) if match else None

    def _should_process_image(self, img_path: Path) -> bool:
        """过滤不需要 OCR 的图片"""
        try:
            img = cv2.imread(str(img_path))
            if img is None:
                return False
            h, w = img.shape[:2]
            # 过滤太小的图（图标、装饰等）
            if w < 150 or h < 80:
                return False
            # 过滤太大的图（可能是整页扫描，VLM 已处理）
            if w > 2000 or h > 2000:
                return False
            # 过滤纯色图片（背景、空白等）
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            if np.std(gray) < 10:  # 标准差太小说明是纯色
                return False
            return True
        except:
            return False

    def _ocr_single_image(self, img_path: Path) -> List[str]:
        """OCR 单张图片，返回找到的 UCH 编码"""
        if not self._should_process_image(img_path):
            return []
        
        engine = self._get_ocr_engine()
        if engine is None:
            return []
        
        codes = []
        try:
            bgr_image = cv2.imread(str(img_path))
            if bgr_image is None:
                return []
            result = engine.ocr(bgr_image)
            if result and result[0]:
                for line in result[0]:
                    text = line[1][0]
                    uch_match = re.search(r"(UCH[A-Z]?\d+)", text)
                    if uch_match:
                        codes.append(uch_match.group(1))
        except Exception as e:
            print(f"[OCR] 处理图片失败 {img_path.name}: {e}")
        return codes

    def _extract_uch_codes_from_images(self, image_dir: Path) -> list:
        """从图片中并行提取 UCH 编码"""
        engine = self._get_ocr_engine()
        if engine is None:
            return []

        # 收集所有需要处理的图片
        image_paths = []
        for ext in ["*.jpg", "*.png", "*.jpeg"]:
            image_paths.extend(image_dir.glob(ext))
        
        if not image_paths:
            return []

        uch_codes = []
        # 使用线程池并行处理图片（OCR 主要是 I/O 和 GPU 操作）
        max_workers = min(4, len(image_paths))  # 最多 4 个并行
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(self._ocr_single_image, p): p for p in image_paths}
            for future in as_completed(futures):
                try:
                    codes = future.result()
                    uch_codes.extend(codes)
                except Exception as e:
                    print(f"[OCR] 并行处理异常: {e}")

        return list(set(uch_codes))

    # ============ 结果管理（数据库） ============

    def get_all_results(self) -> List[OcrResult]:
        """获取所有结果"""
        conn = sqlite3.connect(str(DB_PATH))
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, filename, package_id, uch_codes, status, created_at
            FROM ocr_results ORDER BY created_at DESC
        """)
        rows = cursor.fetchall()
        conn.close()

        return [
            OcrResult(
                id=r[0],
                filename=r[1],
                package_id=r[2],
                uch_codes=r[3].split(",") if r[3] else [],
                status=r[4],
                created_at=str(r[5]),
            )
            for r in rows
        ]

    def get_result(self, result_id: int) -> Optional[OcrResult]:
        """获取单个结果"""
        conn = sqlite3.connect(str(DB_PATH))
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM ocr_results WHERE id = ?", (result_id,))
        row = cursor.fetchone()
        conn.close()

        if not row:
            return None

        return OcrResult(
            id=row[0],
            filename=row[1],
            package_id=row[2],
            uch_codes=row[3].split(",") if row[3] else [],
            status=row[4],
            created_at=str(row[5]),
        )

    def delete_result(self, result_id: int) -> bool:
        """删除结果"""
        conn = sqlite3.connect(str(DB_PATH))
        cursor = conn.cursor()
        cursor.execute("DELETE FROM ocr_results WHERE id = ?", (result_id,))
        deleted = cursor.rowcount > 0
        conn.commit()
        conn.close()
        return deleted

    def clear_all_results(self):
        """清空所有结果"""
        conn = sqlite3.connect(str(DB_PATH))
        cursor = conn.cursor()
        cursor.execute("DELETE FROM ocr_results")
        conn.commit()
        conn.close()


# 全局服务实例
_ocr_service: Optional[OcrService] = None


def get_ocr_service() -> OcrService:
    global _ocr_service
    if _ocr_service is None:
        _ocr_service = OcrService()
    return _ocr_service
