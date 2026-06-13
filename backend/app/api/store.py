"""Store 记忆管理路由 — 用户偏好、进度、上下文快照。"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.core.security import get_current_user
from app.models.models import User
from app.services.store_service import (
    store_put, store_get, store_get_all, store_delete, store_delete_all,
)

router = APIRouter(prefix="/store", tags=["Store 记忆"])


class StorePutRequest(BaseModel):
    key: str
    value: dict | list | str | int | float
    namespace: str = "default"


class StoreEntryResponse(BaseModel):
    key: str
    namespace: str
    value: dict | list
    updated_at: str


@router.get("", response_model=list[StoreEntryResponse])
async def list_store(
    namespace: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取当前用户所有 Store 数据。"""
    entries = await store_get_all(db, str(current_user.id), namespace)
    return entries


@router.get("/{key}", response_model=StoreEntryResponse)
async def get_store(
    key: str,
    namespace: str = "default",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取指定键的值。"""
    entry = await store_get(db, str(current_user.id), key, namespace)
    if entry is None:
        raise HTTPException(status_code=404, detail="键不存在")
    return entry


@router.put("", status_code=status.HTTP_204_NO_CONTENT)
async def put_store(
    data: StorePutRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """存储或更新键值对。"""
    await store_put(db, str(current_user.id), data.key, data.value, data.namespace)
    from app.services.agent_graph import invalidate_store_cache
    invalidate_store_cache(str(current_user.id))


@router.delete("/{key}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_store(
    key: str,
    namespace: str = "default",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除指定键。"""
    deleted = await store_delete(db, str(current_user.id), key, namespace)
    if not deleted:
        raise HTTPException(status_code=404, detail="键不存在")
    from app.services.agent_graph import invalidate_store_cache
    invalidate_store_cache(str(current_user.id))


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def clear_store(
    namespace: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """清空当前用户所有 Store 数据。"""
    await store_delete_all(db, str(current_user.id), namespace)
    from app.services.agent_graph import invalidate_store_cache
    invalidate_store_cache(str(current_user.id))
