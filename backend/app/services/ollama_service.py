"""Ollama 服务调用封装 — embedding 和 chat 生成。"""

import logging
from typing import AsyncGenerator

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


async def chat_stream(
    messages: list[dict],
    model: str | None = None,
) -> AsyncGenerator[str, None]:
    """流式调用 Ollama chat API，逐 token 返回。

    Args:
        messages: [{"role": "user", "content": "..."}, ...]
        model: 模型名称，默认使用配置中的 LLM 模型

    Yields:
        每次生成的 token 字符串
    """
    client = await _get_client()
    model = model or settings.OLLAMA_LLM_MODEL

    try:
        async with client.stream(
            "POST",
            "/api/chat",
            json={
                "model": model,
                "messages": messages,
                "stream": True,
            },
            timeout=120.0,
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if line.strip():
                    import json
                    try:
                        data = json.loads(line)
                        if "message" in data:
                            token = data["message"].get("content", "")
                            if token:
                                yield token
                        if data.get("done", False):
                            break
                    except json.JSONDecodeError:
                        continue
    except httpx.TimeoutException:
        logger.error("Chat 请求超时 (120s)")
        raise RuntimeError("LLM 生成超时，请稍后重试")
    except Exception as e:
        logger.error(f"Chat 请求异常: {e}")
        raise RuntimeError(f"LLM 生成失败: {e}")


async def check_ollama_model(model: str) -> bool:
    """检查 Ollama 模型是否可用。"""
    client = await _get_client()
    try:
        response = await client.post(
            "/api/embeddings",
            json={"model": model, "prompt": "test"},
            timeout=10.0,
        )
        return response.status_code == 200
    except Exception:
        return False
