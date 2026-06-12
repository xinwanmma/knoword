"""分块策略配置路由 — 预览分块效果、对比策略。"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from app.core.security import get_current_user, require_admin
from app.models.models import User
from app.services.chunk_config import preview_chunks, compare_strategies, get_chunk_config

router = APIRouter(prefix="/chunks", tags=["分块配置"])


class PreviewRequest(BaseModel):
    text: str
    target_tokens: int = 300
    max_tokens: int = 512
    overlap_sentences: int = 2


@router.get("/config")
async def get_config(current_user: User = Depends(get_current_user)):
    """获取当前分块配置。"""
    config = get_chunk_config()
    return {
        "target_tokens": config.target_tokens,
        "max_tokens": config.max_tokens,
        "overlap_sentences": config.overlap_sentences,
    }


@router.post("/preview")
async def preview(
    data: PreviewRequest,
    current_user: User = Depends(get_current_user),
):
    """预览分块效果。"""
    from app.services.chunk_config import ChunkConfig

    config = ChunkConfig(
        target_tokens=data.target_tokens,
        max_tokens=data.max_tokens,
        overlap_sentences=data.overlap_sentences,
    )
    chunks = preview_chunks(data.text, config)
    return {
        "total_chunks": len(chunks),
        "chunks": [{
            "index": c["chunk_index"],
            "text": c["text"],
            "token_count": c["token_count"],
            "char_count": c["char_count"],
        } for c in chunks],
    }


@router.post("/compare")
async def compare(
    data: PreviewRequest,
    current_user: User = Depends(get_current_user),
):
    """对比不同分块策略的效果。"""
    results = compare_strategies(data.text)
    return results
