"""知识库管理路由。"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.models.models import KnowledgeBase, Document, Category, User
from app.schemas.schemas import (
    KnowledgeBaseCreate, KnowledgeBaseUpdate, KnowledgeBaseOut, CategoryCreate, CategoryOut,
)
from app.core.security import get_current_user, require_admin
from app.services.vectorstore import delete_by_kb_id

router = APIRouter(prefix="/kb", tags=["知识库"])


@router.post("", response_model=KnowledgeBaseOut, status_code=status.HTTP_201_CREATED)
async def create_kb(
    data: KnowledgeBaseCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建知识库。普通用户只能创建私有库，admin 可创建全局库。"""
    if data.is_global and not current_user.is_admin:
        raise HTTPException(status_code=403, detail="只有管理员可以创建全局知识库")

    kb = KnowledgeBase(
        name=data.name,
        description=data.description,
        category_id=data.category_id,
        owner_id=current_user.id if not data.is_global else None,
        is_global=data.is_global,
    )
    db.add(kb)
    await db.commit()
    await db.refresh(kb)

    category_name = None
    if kb.category_id:
        cat = await db.get(Category, kb.category_id)
        category_name = cat.name if cat else None

    return KnowledgeBaseOut(
        id=kb.id,
        name=kb.name,
        description=kb.description,
        category_id=kb.category_id,
        category_name=category_name,
        owner_id=kb.owner_id,
        is_global=kb.is_global,
        created_at=kb.created_at,
        document_count=0,
    )


@router.get("", response_model=list[KnowledgeBaseOut])
async def list_kbs(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """列出可访问的知识库。用户：自己的 + 全局的；admin：全部。"""
    query = select(KnowledgeBase)
    if not current_user.is_admin:
        query = query.where(
            (KnowledgeBase.owner_id == current_user.id) | (KnowledgeBase.is_global == True)
        )

    result = await db.execute(query.order_by(KnowledgeBase.created_at.desc()))
    kbs = result.scalars().all()

    # 批量获取文档计数
    kb_ids = [kb.id for kb in kbs]
    count_query = select(Document.kb_id, func.count(Document.id)).where(
        Document.kb_id.in_(kb_ids)
    ).group_by(Document.kb_id)
    count_result = await db.execute(count_query)
    count_map = {row[0]: row[1] for row in count_result.all()}

    # 获取分类名
    category_ids = list({kb.category_id for kb in kbs if kb.category_id})
    cat_map = {}
    if category_ids:
        cat_result = await db.execute(select(Category).where(Category.id.in_(category_ids)))
        cat_map = {c.id: c.name for c in cat_result.scalars().all()}

    return [
        KnowledgeBaseOut(
            id=kb.id,
            name=kb.name,
            description=kb.description,
            category_id=kb.category_id,
            category_name=cat_map.get(kb.category_id),
            owner_id=kb.owner_id,
            is_global=kb.is_global,
            created_at=kb.created_at,
            document_count=count_map.get(kb.id, 0),
        )
        for kb in kbs
    ]


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

    # 权限检查
    if not current_user.is_admin and kb.owner_id != current_user.id and not kb.is_global:
        raise HTTPException(status_code=403, detail="无权访问此知识库")

    # 文档计数
    count_result = await db.execute(
        select(func.count(Document.id)).where(Document.kb_id == kb_id)
    )
    doc_count = count_result.scalar() or 0

    category_name = None
    if kb.category_id:
        cat = await db.get(Category, kb.category_id)
        category_name = cat.name if cat else None

    return KnowledgeBaseOut(
        id=kb.id,
        name=kb.name,
        description=kb.description,
        category_id=kb.category_id,
        category_name=category_name,
        owner_id=kb.owner_id,
        is_global=kb.is_global,
        created_at=kb.created_at,
        document_count=doc_count,
    )


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

    if not current_user.is_admin and kb.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权修改此知识库")

    if data.name is not None:
        kb.name = data.name
    if data.description is not None:
        kb.description = data.description
    if data.category_id is not None:
        kb.category_id = data.category_id

    await db.commit()
    await db.refresh(kb)

    category_name = None
    if kb.category_id:
        cat = await db.get(Category, kb.category_id)
        category_name = cat.name if cat else None

    return KnowledgeBaseOut(
        id=kb.id,
        name=kb.name,
        description=kb.description,
        category_id=kb.category_id,
        category_name=category_name,
        owner_id=kb.owner_id,
        is_global=kb.is_global,
        created_at=kb.created_at,
    )


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

    if not current_user.is_admin and kb.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权删除此知识库")

    # 删除 ChromaDB 向量
    delete_by_kb_id(kb_id)

    # 删除数据库记录（级联删除 documents）
    await db.delete(kb)
    await db.commit()


# ==================== 分类管理 ====================

category_router = APIRouter(prefix="/categories", tags=["分类"])


@category_router.get("", response_model=list[CategoryOut])
async def list_categories(db: AsyncSession = Depends(get_db)):
    """获取所有分类。"""
    result = await db.execute(select(Category).order_by(Category.name))
    return [CategoryOut.model_validate(c) for c in result.scalars().all()]


@category_router.post("", response_model=CategoryOut, status_code=status.HTTP_201_CREATED)
async def create_category(
    data: CategoryCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """admin 添加分类。"""
    existing = await db.execute(select(Category).where(Category.name == data.name))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="分类已存在")

    cat = Category(name=data.name)
    db.add(cat)
    await db.commit()
    await db.refresh(cat)
    return CategoryOut.model_validate(cat)
