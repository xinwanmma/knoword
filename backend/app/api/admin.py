"""管理员后台 API — 用户管理 / 全局知识库 / 统计。

所有路由均需管理员权限（require_admin 依赖）。
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import require_admin
from app.db.database import get_db
from app.models.models import (
    User, KnowledgeBase, Document, Conversation, Message,
)
from app.schemas.schemas import UserOut, KnowledgeBaseOut, DocumentOut
from app.services.vectorstore import delete_by_kb_id

router = APIRouter(prefix="/admin", tags=["管理后台"])


# ==================== 统计 ====================

@router.get("/stats")
async def get_stats(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """获取系统整体统计信息。"""
    user_count = (await db.execute(select(func.count(User.id)))).scalar() or 0
    admin_count = (await db.execute(
        select(func.count(User.id)).where(User.is_admin == True)
    )).scalar() or 0
    kb_count = (await db.execute(select(func.count(KnowledgeBase.id)))).scalar() or 0
    doc_count = (await db.execute(select(func.count(Document.id)))).scalar() or 0
    ready_docs = (await db.execute(
        select(func.count(Document.id)).where(Document.status == "ready")
    )).scalar() or 0
    conv_count = (await db.execute(select(func.count(Conversation.id)))).scalar() or 0
    msg_count = (await db.execute(select(func.count(Message.id)))).scalar() or 0

    return {
        "users": {
            "total": user_count,
            "admins": admin_count,
            "regular": user_count - admin_count,
        },
        "knowledge_bases": kb_count,
        "documents": {
            "total": doc_count,
            "ready": ready_docs,
            "processing": doc_count - ready_docs,
        },
        "conversations": conv_count,
        "messages": msg_count,
    }


# ==================== 用户管理 ====================

@router.get("/users", response_model=list[UserOut])
async def list_users(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
    limit: int = 100,
    offset: int = 0,
):
    """获取所有用户列表（按创建时间倒序）。"""
    result = await db.execute(
        select(User).order_by(desc(User.created_at)).offset(offset).limit(min(limit, 200))
    )
    users = result.scalars().all()
    return [UserOut.model_validate(u) for u in users]


@router.get("/users/{user_id}", response_model=UserOut)
async def get_user(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """获取用户详情。"""
    import uuid
    try:
        user_uuid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="无效的用户 ID")

    user = await db.get(User, user_uuid)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    return UserOut.model_validate(user)


@router.post("/users/{user_id}/toggle-admin", response_model=UserOut)
async def toggle_admin(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """切换用户的 admin 状态。

    保护：不允许管理员取消自己的 admin 权限（防止锁死）。
    """
    import uuid
    try:
        user_uuid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="无效的用户 ID")

    user = await db.get(User, user_uuid)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")

    if user.id == admin.id:
        raise HTTPException(
            status_code=400,
            detail="不能修改自己的管理员权限",
        )

    # 确保至少保留一个 admin
    if user.is_admin:
        result = await db.execute(
            select(func.count(User.id)).where(User.is_admin == True)
        )
        admin_total = result.scalar() or 0
        if admin_total <= 1:
            raise HTTPException(
                status_code=400,
                detail="系统必须保留至少一个管理员",
            )

    user.is_admin = not user.is_admin
    await db.commit()
    await db.refresh(user)
    return UserOut.model_validate(user)


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """删除用户（级联删除其 KB / 文档 / 对话 / ChromaDB 向量）。

    保护：不能删除自己；不能删除最后一个 admin。
    """
    import uuid
    try:
        user_uuid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="无效的用户 ID")

    user = await db.get(User, user_uuid)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")

    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="不能删除自己")

    if user.is_admin:
        result = await db.execute(
            select(func.count(User.id)).where(User.is_admin == True)
        )
        admin_total = result.scalar() or 0
        if admin_total <= 1:
            raise HTTPException(
                status_code=400,
                detail="系统必须保留至少一个管理员",
            )

    # 先删除该用户所有 KB 的 ChromaDB 向量
    kb_result = await db.execute(
        select(KnowledgeBase.id).where(KnowledgeBase.owner_id == user.id)
    )
    kb_ids = [row[0] for row in kb_result.all()]
    for kb_id in kb_ids:
        try:
            delete_by_kb_id(kb_id)
        except Exception:
            pass  # 即使向量删除失败也要继续

    # 删除用户（ORM 级联删除 KB / 文档 / 对话 / 消息）
    await db.delete(user)
    await db.commit()


# ==================== 全局知识库管理 ====================

@router.get("/kbs", response_model=list[dict])
async def list_all_kbs(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
    limit: int = 200,
    offset: int = 0,
):
    """获取所有用户的知识库（含 owner 信息）。"""
    result = await db.execute(
        select(KnowledgeBase, User.username, User.id)
        .join(User, KnowledgeBase.owner_id == User.id)
        .order_by(desc(KnowledgeBase.created_at))
        .offset(offset)
        .limit(min(limit, 500))
    )

    items = []
    for kb, owner_username, owner_id in result.all():
        doc_count = (await db.execute(
            select(func.count(Document.id)).where(Document.kb_id == kb.id)
        )).scalar() or 0
        items.append({
            "id": kb.id,
            "name": kb.name,
            "description": kb.description,
            "owner_id": str(owner_id),
            "owner_username": owner_username,
            "created_at": kb.created_at.isoformat() if kb.created_at else None,
            "document_count": doc_count,
        })
    return items


@router.get("/kbs/{kb_id}/documents", response_model=list[DocumentOut])
async def list_kb_documents(
    kb_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """管理员查看任意 KB 的文档列表。"""
    kb = await db.get(KnowledgeBase, kb_id)
    if kb is None:
        raise HTTPException(status_code=404, detail="知识库不存在")

    result = await db.execute(
        select(Document)
        .where(Document.kb_id == kb_id)
        .order_by(desc(Document.created_at))
    )
    docs = result.scalars().all()
    return [DocumentOut.model_validate(d) for d in docs]


@router.delete("/kbs/{kb_id}", status_code=status.HTTP_204_NO_CONTENT)
async def admin_delete_kb(
    kb_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """管理员删除任意 KB（级联清理 ChromaDB 向量 + 文档 + DB）。"""
    kb = await db.get(KnowledgeBase, kb_id)
    if kb is None:
        raise HTTPException(status_code=404, detail="知识库不存在")

    try:
        delete_by_kb_id(kb_id)
    except Exception:
        pass

    await db.delete(kb)
    await db.commit()
