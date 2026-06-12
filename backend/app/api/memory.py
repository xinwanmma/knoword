"""Mem0 记忆管理路由 — 用户事实记忆的查看与管理。"""

from fastapi import APIRouter, Depends, HTTPException, status
from app.db.database import get_db
from app.core.security import get_current_user
from app.models.models import User
from app.services.memory_service import (
    search_memories, get_all_memories, delete_memory,
    delete_all_memories, get_memory_stats,
)

router = APIRouter(prefix="/memory", tags=["Mem0 记忆"])


@router.get("")
async def list_memories(
    current_user: User = Depends(get_current_user),
):
    """获取当前用户所有事实记忆。"""
    memories = await get_all_memories(str(current_user.id))
    return {"memories": memories, "total": len(memories)}


@router.get("/search")
async def search_memory(
    q: str,
    top_k: int = 5,
    current_user: User = Depends(get_current_user),
):
    """搜索用户相关记忆。"""
    results = await search_memories(str(current_user.id), q, top_k)
    return {"results": results}


@router.get("/stats")
async def memory_stats(
    current_user: User = Depends(get_current_user),
):
    """获取记忆统计。"""
    stats = await get_memory_stats(str(current_user.id))
    return stats


@router.delete("/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_memory(
    memory_id: str,
    current_user: User = Depends(get_current_user),
):
    """删除单条记忆。"""
    deleted = await delete_memory(memory_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="记忆不存在或删除失败")


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def clear_memories(
    current_user: User = Depends(get_current_user),
):
    """清空当前用户所有记忆。"""
    await delete_all_memories(str(current_user.id))
