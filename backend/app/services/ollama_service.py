"""Ollama 服务调用封装 — embedding 调用。"""

import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# HTTP 客户端复用
_client: httpx.AsyncClient | None = None


async def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            base_url=settings.OLLAMA_BASE_URL,
            timeout=httpx.Timeout(120.0, connect=10.0),
        )
    return _client


async def close_client():
    global _client
    if _client and not _client.is_closed:
        await _client.aclose()
        _client = None


async def get_embedding(text: str, retries: int = 1) -> list[float]:
    """获取文本的 embedding 向量。

    Args:
        text: 输入文本
        retries: 失败重试次数

    Returns:
        embedding 向量
    """
    client = await _get_client()

    for attempt in range(retries + 1):
        try:
            response = await client.post(
                "/api/embeddings",
                json={
                    "model": settings.OLLAMA_EMBED_MODEL,
                    "prompt": text,
                },
                timeout=30.0,
            )
            response.raise_for_status()
            data = response.json()
            return data["embedding"]
        except httpx.TimeoutException:
            logger.warning(f"Embedding 请求超时 (尝试 {attempt + 1}/{retries + 1})")
            if attempt < retries:
                import asyncio
                await asyncio.sleep(2)
        except httpx.HTTPStatusError as e:
            logger.error(f"Embedding 请求失败: {e.response.status_code} - {e.response.text}")
            raise RuntimeError(f"Ollama embedding 失败: {e.response.status_code}")
        except Exception as e:
            logger.error(f"Embedding 请求异常: {e}")
            if attempt < retries:
                import asyncio
                await asyncio.sleep(2)
            else:
                raise RuntimeError(f"Ollama embedding 异常: {e}")

    raise RuntimeError("Embedding 请求失败，已达最大重试次数")


async def check_ollama_model(model: str) -> bool:
    """通过 /api/tags 检查 Ollama 模型是否已安装。"""
    client = await _get_client()
    try:
        response = await client.get("/api/tags", timeout=10.0)
        response.raise_for_status()
        data = response.json()
        installed_models = [m.get("name", "") for m in data.get("models", [])]
        return any(
            model == m or model + ":latest" == m
            for m in installed_models
        )
    except Exception as e:
        logger.warning(f"检查模型 {model} 安装状态失败: {e}")
        return False
