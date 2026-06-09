"""健康检查路由。"""

import httpx
from fastapi import APIRouter

from app.config import settings
from app.db.database import async_session_factory
from app.services.vectorstore import check_chromadb

router = APIRouter(tags=["系统"])


@router.get("/health")
async def health_check():
    """检查所有依赖服务是否可用。"""
    checks = {}

    # 检查 PostgreSQL
    try:
        async with async_session_factory() as session:
            await session.execute(__import__("sqlalchemy").text("SELECT 1"))
        checks["database"] = True
    except Exception:
        checks["database"] = False

    # 检查 ChromaDB
    checks["chromadb"] = check_chromadb()

    # 检查 Ollama LLM
    try:
        async with httpx.AsyncClient(base_url=settings.OLLAMA_BASE_URL, timeout=10.0) as client:
            resp = await client.post(
                "/api/embeddings",
                json={"model": settings.OLLAMA_LLM_MODEL, "prompt": "test"},
            )
            checks["ollama_llm"] = resp.status_code == 200
    except Exception:
        checks["ollama_llm"] = False

    # 检查 Ollama Embedding
    try:
        async with httpx.AsyncClient(base_url=settings.OLLAMA_BASE_URL, timeout=10.0) as client:
            resp = await client.post(
                "/api/embeddings",
                json={"model": settings.OLLAMA_EMBED_MODEL, "prompt": "test"},
            )
            checks["ollama_embed"] = resp.status_code == 200
    except Exception:
        checks["ollama_embed"] = False

    all_ok = all(checks.values())
    return {
        "status": "ok" if all_ok else "degraded",
        "services": checks,
    }
