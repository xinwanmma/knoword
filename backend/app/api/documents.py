"""文档管理路由 — 上传、状态查询、删除、重新索引。"""

import os
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, BackgroundTasks, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.database import get_db
from app.models.models import Document, KnowledgeBase, User
from app.schemas.schemas import DocumentOut, DocumentStatusOut
from app.core.security import get_current_user
from app.services.document_processor import process_document, remove_document_vectors

router = APIRouter(prefix="/documents", tags=["文档"])

# 文件存储目录
UPLOAD_DIR = Path("data/uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def _validate_file(file: UploadFile) -> None:
    """校验上传文件。"""
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in settings.ALLOWED_FILE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件格式: {suffix}，允许: {settings.ALLOWED_FILE_TYPES}",
        )


async def _save_file(file: UploadFile, kb_id: int) -> tuple[str, str]:
    """保存上传文件到磁盘，返回 (saved_name, file_path)。"""
    suffix = Path(file.filename).suffix.lower()
    saved_name = f"{kb_id}_{uuid.uuid4().hex[:12]}{suffix}"
    file_path = str(UPLOAD_DIR / saved_name)

    content = await file.read()
    if len(content) > settings.MAX_UPLOAD_SIZE_BYTES:
        raise HTTPException(status_code=400, detail=f"文件不能超过 {settings.MAX_UPLOAD_SIZE_BYTES // 1024 // 1024}MB")

    with open(file_path, "wb") as f:
        f.write(content)

    return saved_name, file_path


@router.post("/upload", response_model=list[DocumentOut], status_code=status.HTTP_201_CREATED)
async def upload_documents(
    kb_id: int,
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """上传文档到指定知识库（支持多文件）。异步处理，上传后立即返回。"""
    # 校验知识库存在且有权限
    kb = await db.get(KnowledgeBase, kb_id)
    if kb is None:
        raise HTTPException(status_code=404, detail="知识库不存在")
    if not current_user.is_admin and kb.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权向此知识库上传文档")

    saved_docs = []
    for file in files:
        _validate_file(file)
        saved_name, file_path = await _save_file(file, kb_id)

        suffix = Path(file.filename).suffix.lower()
        doc = Document(
            kb_id=kb_id,
            filename=file.filename,
            file_path=file_path,
            file_type=suffix,
            status="processing",
        )
        db.add(doc)
        await db.flush()  # 获取 doc.id

        saved_docs.append(doc)

    await db.commit()

    # 为每个文档启动后台处理任务
    for doc in saved_docs:
        background_tasks.add_task(process_document, doc.id, doc.file_path)

    # 刷新获取最终状态
    for doc in saved_docs:
        await db.refresh(doc)

    return [DocumentOut.model_validate(d) for d in saved_docs]


@router.get("/{doc_id}/status", response_model=DocumentStatusOut)
async def get_document_status(
    doc_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """查询文档处理状态。"""
    doc = await db.get(Document, doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="文档不存在")

    return DocumentStatusOut(
        id=doc.id,
        status=doc.status,
        chunk_count=doc.chunk_count,
        error=doc.error,
    )


@router.delete("/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    doc_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除文档及其向量。"""
    doc = await db.get(Document, doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="文档不存在")

    kb = await db.get(KnowledgeBase, doc.kb_id)
    if not current_user.is_admin and (kb is None or kb.owner_id != current_user.id):
        raise HTTPException(status_code=403, detail="无权删除此文档")

    # 删除向量
    await remove_document_vectors(doc_id)

    # 删除磁盘文件
    if os.path.exists(doc.file_path):
        os.remove(doc.file_path)

    # 删除数据库记录
    await db.delete(doc)
    await db.commit()


@router.post("/{doc_id}/reindex", response_model=DocumentOut)
async def reindex_document(
    doc_id: int,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """重新向量化文档。"""
    doc = await db.get(Document, doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="文档不存在")

    kb = await db.get(KnowledgeBase, doc.kb_id)
    if not current_user.is_admin and (kb is None or kb.owner_id != current_user.id):
        raise HTTPException(status_code=403, detail="无权操作此文档")

    if not os.path.exists(doc.file_path):
        raise HTTPException(status_code=400, detail="原始文件已丢失，无法重新索引")

    # 先删除旧向量
    await remove_document_vectors(doc_id)

    # 更新状态并启动后台处理
    doc.status = "processing"
    doc.chunk_count = 0
    doc.error = None
    await db.commit()
    await db.refresh(doc)

    background_tasks.add_task(process_document, doc.id, doc.file_path)

    return DocumentOut.model_validate(doc)


@router.get("/kb/{kb_id}", response_model=list[DocumentOut])
async def list_documents(
    kb_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """列出指定知识库的文档。"""
    kb = await db.get(KnowledgeBase, kb_id)
    if kb is None:
        raise HTTPException(status_code=404, detail="知识库不存在")

    if not current_user.is_admin and kb.owner_id != current_user.id and not kb.is_global:
        raise HTTPException(status_code=403, detail="无权访问此知识库")

    result = await db.execute(
        select(Document).where(Document.kb_id == kb_id).order_by(Document.created_at.desc())
    )
    docs = result.scalars().all()
    return [DocumentOut.model_validate(d) for d in docs]
