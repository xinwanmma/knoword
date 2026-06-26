"""知识库管理路由。"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.models.models import KnowledgeBase, Document, User
from app.schemas.schemas import (
    KnowledgeBaseCreate, KnowledgeBaseUpdate, KnowledgeBaseOut,
)
from app.core.security import get_current_user, require_admin
from app.services.vectorstore import delete_by_kb_id

router = APIRouter(prefix="/kb", tags=["知识库"])


def _to_out(kb: KnowledgeBase, doc_count: int = 0) -> KnowledgeBaseOut:
    return KnowledgeBaseOut(
        id=kb.id,
        name=kb.name,
        description=kb.description,
        owner_id=kb.owner_id,
        created_at=kb.created_at,
        document_count=doc_count,
        embedding_model=kb.embedding_model or "qwen3-embedding:0.6b",
        chunking_strategy=kb.chunking_strategy or "recursive",
        chunk_size=kb.chunk_size or 500,
        chunk_overlap=kb.chunk_overlap or 50,
        retrieval_strategy=kb.retrieval_strategy or "vector",
        rerank_model=kb.rerank_model or "BAAI/bge-reranker-base",
        rerank_top_n=kb.rerank_top_n or 20,
    )


@router.post("", response_model=KnowledgeBaseOut, status_code=status.HTTP_201_CREATED)
async def create_kb(
    data: KnowledgeBaseCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建知识库（仅管理员）。"""
    # Phase 3：仅管理员可创建 KB
    require_admin(current_user)

    kb = KnowledgeBase(
        name=data.name,
        description=data.description,
        owner_id=current_user.id,
        embedding_model=data.embedding_model,
        chunking_strategy=data.chunking_strategy,
        chunk_size=data.chunk_size,
        chunk_overlap=data.chunk_overlap,
        retrieval_strategy=data.retrieval_strategy,
        rerank_model=data.rerank_model,
        rerank_top_n=data.rerank_top_n,
    )
    db.add(kb)
    await db.commit()
    await db.refresh(kb)
    return _to_out(kb, 0)


@router.get("", response_model=list[KnowledgeBaseOut])
async def list_kbs(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """列出当前用户的知识库。"""
    result = await db.execute(
        select(KnowledgeBase)
        .where(KnowledgeBase.owner_id == current_user.id)
        .order_by(KnowledgeBase.created_at.desc())
    )
    kbs = result.scalars().all()

    kb_ids = [kb.id for kb in kbs]
    count_map: dict[int, int] = {}
    if kb_ids:
        count_result = await db.execute(
            select(Document.kb_id, func.count(Document.id))
            .where(Document.kb_id.in_(kb_ids))
            .group_by(Document.kb_id)
        )
        count_map = {row[0]: row[1] for row in count_result.all()}

    return [_to_out(kb, count_map.get(kb.id, 0)) for kb in kbs]


@router.get("/{kb_id}", response_model=KnowledgeBaseOut)
async def get_kb(
    kb_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取知识库详情。"""
    kb = await db.get(KnowledgeBase, kb_id)
    if kb is None:
        raise HTTPException(status_code=404, detail="知识库不存在")
    if kb.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权访问此知识库")

    count_result = await db.execute(
        select(func.count(Document.id)).where(Document.kb_id == kb_id)
    )
    doc_count = count_result.scalar() or 0

    return _to_out(kb, doc_count)


@router.put("/{kb_id}", response_model=KnowledgeBaseOut)
async def update_kb(
    kb_id: int,
    data: KnowledgeBaseUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """更新知识库信息。"""
    kb = await db.get(KnowledgeBase, kb_id)
    if kb is None:
        raise HTTPException(status_code=404, detail="知识库不存在")
    if kb.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权修改此知识库")

    if data.name is not None:
        kb.name = data.name
    if data.description is not None:
        kb.description = data.description
    if data.embedding_model is not None:
        kb.embedding_model = data.embedding_model
    if data.chunking_strategy is not None:
        kb.chunking_strategy = data.chunking_strategy
    if data.chunk_size is not None:
        kb.chunk_size = data.chunk_size
    if data.chunk_overlap is not None:
        kb.chunk_overlap = data.chunk_overlap
    if data.retrieval_strategy is not None:
        kb.retrieval_strategy = data.retrieval_strategy
    if data.rerank_model is not None:
        kb.rerank_model = data.rerank_model
    if data.rerank_top_n is not None:
        kb.rerank_top_n = data.rerank_top_n

    await db.commit()
    await db.refresh(kb)

    count_result = await db.execute(
        select(func.count(Document.id)).where(Document.kb_id == kb_id)
    )
    doc_count = count_result.scalar() or 0

    return _to_out(kb, doc_count)


@router.delete("/{kb_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_kb(
    kb_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除知识库（级联删除文档 + ChromaDB 向量）。"""
    kb = await db.get(KnowledgeBase, kb_id)
    if kb is None:
        raise HTTPException(status_code=404, detail="知识库不存在")
    if kb.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权删除此知识库")

    delete_by_kb_id(kb_id)
    await db.delete(kb)
    await db.commit()
