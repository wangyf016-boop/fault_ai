"""
OCR API Router - FastAPI 路由
- 任务管理：内存存储
- 结果管理：数据库持久化
"""

import re
import asyncio
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, UploadFile, File, HTTPException
from pydantic import BaseModel

from .ocr_service import get_ocr_service, UPLOAD_FOLDER, TaskStatus

router = APIRouter(prefix="/api/ocr", tags=["OCR"])


def secure_filename(filename: str) -> str:
    """安全处理文件名"""
    filename = re.sub(r"[^\w\u4e00-\u9fff.-]", "_", filename)
    filename = filename.lstrip(".")
    return filename or "unnamed"


# ============ Pydantic Models ============


class TaskResponse(BaseModel):
    id: str
    filename: str
    status: str
    progress: int
    stage: str
    createdAt: str
    error: str = ""


class TaskListResponse(BaseModel):
    tasks: List[TaskResponse]


class OcrResultResponse(BaseModel):
    id: int
    filename: str
    package_id: str
    uch_codes: List[str]
    status: str
    created_at: str


class OcrResultsListResponse(BaseModel):
    results: List[OcrResultResponse]


class UploadResponse(BaseModel):
    tasks: List[TaskResponse]
    message: str


# ============ 任务 API（内存） ============


@router.post("/upload", response_model=UploadResponse)
async def upload_pdfs(
    files: List[UploadFile] = File(...),
):
    """上传 PDF 文件进行 OCR 处理"""
    service = get_ocr_service()
    created_tasks = []

    for file in files:
        if not file.filename or not file.filename.lower().endswith(".pdf"):
            continue

        pdf_bytes = await file.read()
        task = service.create_task(secure_filename(file.filename), pdf_bytes)
        created_tasks.append(TaskResponse(**task.to_dict()))

        # 提交到线程池并行处理
        service.submit_task(task.id)

    if not created_tasks:
        raise HTTPException(status_code=400, detail="没有有效的 PDF 文件")

    return UploadResponse(
        tasks=created_tasks, message=f"已创建 {len(created_tasks)} 个处理任务"
    )


@router.get("/tasks", response_model=TaskListResponse)
async def get_tasks():
    """获取所有 OCR 任务（内存中）"""
    service = get_ocr_service()
    tasks = service.get_all_tasks()
    tasks.sort(key=lambda t: t.created_at, reverse=True)
    return TaskListResponse(tasks=[TaskResponse(**t.to_dict()) for t in tasks])


@router.get("/status/{task_id}", response_model=TaskResponse)
async def get_task_status(task_id: str):
    """获取任务状态"""
    service = get_ocr_service()
    task = service.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return TaskResponse(**task.to_dict())


@router.delete("/task/{task_id}")
async def delete_task(task_id: str):
    """删除任务"""
    service = get_ocr_service()
    if not service.delete_task(task_id):
        raise HTTPException(status_code=404, detail="任务不存在")
    return {"message": "任务已删除", "task_id": task_id}


# ============ 结果 API（数据库） ============


@router.get("/results", response_model=OcrResultsListResponse)
async def get_results():
    """查询所有 OCR 结果（数据库）"""
    service = get_ocr_service()
    results = service.get_all_results()

    return OcrResultsListResponse(
        results=[
            OcrResultResponse(
                id=r.id,
                filename=r.filename,
                package_id=r.package_id or "",
                uch_codes=r.uch_codes,
                status=r.status,
                created_at=r.created_at,
            )
            for r in results
        ]
    )


@router.get("/results/{result_id}", response_model=OcrResultResponse)
async def get_result(result_id: int):
    """查询单个 OCR 结果"""
    service = get_ocr_service()
    result = service.get_result(result_id)

    if not result:
        raise HTTPException(status_code=404, detail="记录不存在")

    return OcrResultResponse(
        id=result.id,
        filename=result.filename,
        package_id=result.package_id or "",
        uch_codes=result.uch_codes,
        status=result.status,
        created_at=result.created_at,
    )


@router.delete("/results/{result_id}")
async def delete_result(result_id: int):
    """删除 OCR 结果"""
    service = get_ocr_service()

    if not service.delete_result(result_id):
        raise HTTPException(status_code=404, detail="记录不存在")

    return {"message": "记录已删除", "id": result_id}


@router.delete("/results")
async def clear_results():
    """清空所有 OCR 结果"""
    service = get_ocr_service()
    service.clear_all_results()
    return {"message": "所有记录已清空"}
