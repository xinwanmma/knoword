"""健康检查路由。"""

import logging

import httpx
from fastapi import APIRouter
from sqlalchemy import text

from app.config import settings
from app.db.database import async_session_factory
from app.services.vectorstore import check_chromadb

logger = logging.getLogger(__name__)

router = APIRouter(tags=["系统"])


@router.get("/health")
async def health_check():
    """检查所有依赖服务是否可用。"""
    checks = {}

    # 检查 PostgreSQL
    try:
        async with async_session_factory() as session:
            await session.execute(text("SELECT 1"))
        checks["database"] = True
    except Exception:
        checks["database"] = False

    # 检查 ChromaDB
    checks["chromadb"] = check_chromadb()

    # 检查 MiMo LLM（云端 API）
    try:
        async with httpx.AsyncClient(
            base_url=settings.MIMO_BASE_URL, timeout=10.0
        ) as client:
            headers = {"Authorization": f"Bearer {settings.MIMO_API_KEY}"}
            models_resp = await client.get("/models", headers=headers)
            if models_resp.status_code == 200:
                data = models_resp.json()
                installed = {m.get("id", "") for m in data.get("data", [])}
                checks["mimo_llm"] = any(
                    settings.MIMO_MODEL in m
                    for m in installed
                )
            else:
                checks["mimo_llm"] = False
    except Exception:
        checks["mimo_llm"] = False

    # 检查 Ollama（仅用于 embedding）
    try:
        async with httpx.AsyncClient(
            base_url=settings.OLLAMA_BASE_URL, timeout=10.0
        ) as client:
            tags_resp = await client.get("/api/tags")
            ollama_running = tags_resp.status_code == 200

            if ollama_running:
                data = tags_resp.json()
                installed = {m.get("name", "") for m in data.get("models", [])}
                try:
                    embed_resp = await client.post(
                        "/api/embeddings",
                        json={"model": settings.OLLAMA_EMBED_MODEL, "prompt": "test"},
                        timeout=15.0,
                    )
                    checks["ollama_embed"] = embed_resp.status_code == 200
                except Exception:
                    checks["ollama_embed"] = False
            else:
                checks["ollama_embed"] = False
    except Exception:
        checks["ollama_embed"] = False

    all_ok = all(checks.values())
    return {
        "status": "ok" if all_ok else "degraded",
        "services": checks,
    }
