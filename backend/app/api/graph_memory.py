"""Memary 知识图谱记忆路由 — 实体关系搜索、时间线、管理。"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from app.core.security import get_current_user
from app.models.models import User
from app.services.graph_memory import (
    search_graph, get_entities, get_timeline, clear_graph,
)

router = APIRouter(prefix="/graph", tags=["Memary 知识图谱"])


@router.get("/search")
async def graph_search(
    q: str,
    max_depth: int = 2,
    current_user: User = Depends(get_current_user),
):
    """知识图谱搜索。"""
    result = await search_graph(str(current_user.id), q, max_depth)
    return result


@router.get("/entities")
async def graph_entities(
    limit: int = 20,
    current_user: User = Depends(get_current_user),
):
    """获取用户高频实体列表。"""
    entities = await get_entities(str(current_user.id), limit)
    return {"entities": entities}


@router.get("/timeline")
async def graph_timeline(
    current_user: User = Depends(get_current_user),
):
    """获取实体时间线（话题演化）。"""
    timeline = await get_timeline(str(current_user.id))
    return {"timeline": timeline}


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def clear_user_graph(
    current_user: User = Depends(get_current_user),
):
    """清空用户知识图谱。"""
    await clear_graph(str(current_user.id))
