"""Ollama Embedding Provider — 本地 Ollama 服务。"""
import logging

import httpx

from app.config import settings
from app.services.embedding.base import EmbeddingProvider

logger = logging.getLogger(__name__)


class OllamaProvider(EmbeddingProvider):
    """通过 Ollama HTTP API 调用本地 embedding 模型。

    默认模型：qwen3-embedding:0.6b
    """

    # Ollama embedding 维度（qwen3-embedding:0.6b = 1024）
    DEFAULT_DIMENSION = 1024

    def __init__(self, model: str | None = None):
        self._model = model or settings.OLLAMA_EMBED_MODEL
        self._client: httpx.AsyncClient | None = None
        self._dimension = self.DEFAULT_DIMENSION

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def dimension(self) -> int:
        return self._dimension

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=settings.OLLAMA_BASE_URL,
                timeout=httpx.Timeout(120.0, connect=10.0),
            )
        return self._client

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        client = await self._get_client()
        results: list[list[float]] = []
        for text in texts:
            response = await client.post(
                "/api/embeddings",
                json={"model": self._model, "prompt": text},
                timeout=30.0,
            )
            response.raise_for_status()
            data = response.json()
            emb = data["embedding"]
            results.append(emb)
        return results

    async def embed_query(self, text: str) -> list[float]:
        results = await self.embed_documents([text])
        return results[0]

    async def aclose(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
