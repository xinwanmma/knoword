"""健康检查路由。"""

import logging

import httpx
from fastapi import APIRouter

from app.config import settings
from app.db.database import async_session_factory
from app.services.vectorstore import check_chromadb

logger = logging.getLogger(__name__)

router = APIRouter(tags=["系统"])


async def _check_ollama_running() -> bool:
    """检查 Ollama 服务是否在运行。"""
    try:
        async with httpx.AsyncClient(base_url=settings.OLLAMA_BASE_URL, timeout=5.0) as client:
            resp = await client.get("/api/tags")
            return resp.status_code == 200
    except Exception:
        return False


async def _check_model_installed(model_name: str) -> bool:
    """通过 /api/tags 检查指定模型是否已安装。"""
    try:
        async with httpx.AsyncClient(base_url=settings.OLLAMA_BASE_URL, timeout=10.0) as client:
            resp = await client.get("/api/tags")
            resp.raise_for_status()
            data = resp.json()
            installed_models = [m.get("name", "") for m in data.get("models", [])]
            # 模型名可能带 :latest 后缀，也可能是精确匹配
            return any(
                model_name == m or model_name + ":latest" == m
                for m in installed_models
            )
    except Exception as e:
        logger.warning(f"检查模型 {model_name} 安装状态失败: {e}")
        return False


async def _check_embedding_model() -> bool:
    """通过实际 embedding 调用检查 embedding 模型是否可用。"""
    try:
        async with httpx.AsyncClient(base_url=settings.OLLAMA_BASE_URL, timeout=15.0) as client:
            resp = await client.post(
                "/api/embeddings",
                json={"model": settings.OLLAMA_EMBED_MODEL, "prompt": "test"},
            )
            return resp.status_code == 200
    except Exception:
        return False


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

    # 检查 Ollama 服务是否在运行
    ollama_running = await _check_ollama_running()

    if ollama_running:
        # 检查 LLM 模型是否已安装（用 /api/tags 检查）
        checks["ollama_llm"] = await _check_model_installed(settings.OLLAMA_LLM_MODEL)
        # 检查 Embedding 模型是否可用（用 /api/embeddings 实际调用）
        checks["ollama_embed"] = await _check_embedding_model()
    else:
        checks["ollama_llm"] = False
        checks["ollama_embed"] = False

    all_ok = all(checks.values())
    return {
        "status": "ok" if all_ok else "degraded",
        "services": checks,
    }
