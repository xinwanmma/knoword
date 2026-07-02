"""SiliconFlow Embedding Provider — 云端 API（OpenAI 兼容）。"""
import logging

import httpx

from app.config import settings
from app.services.embedding.base import EmbeddingProvider

logger = logging.getLogger(__name__)


class SiliconFlowProvider(EmbeddingProvider):
    """通过 SiliconFlow 云端 API 调用 Qwen3-Embedding 系列。

    支持模型：
    - Qwen/Qwen3-Embedding-8B（默认，4096 维）
    - Qwen/Qwen3-Embedding-4B（4096 维）

    维度策略：默认 4096 维全量输出（不压缩）。
    不同 embedding 物理隔离（vectorstore.py 按 embedding_model 分 collection）。
    0.6b 走 Ollama（天然 1024 维），不在本 provider。
    """

    # Qwen3-Embedding 4B/8B 默认维度
    DEFAULT_DIMENSION = 4096

    def __init__(self, model: str | None = None):
        # 默认用 8B
        self._model = model or settings.SILICONFLOW_EMBED_8B
        self._api_key = settings.SILICONFLOW_API_KEY
        self._base_url = settings.SILICONFLOW_BASE_URL
        self._client: httpx.AsyncClient | None = None
        # 默认 4096 维（不传 dimensions 参数，让模型输出默认维度）
        self._dimension = self.DEFAULT_DIMENSION

        if not self._api_key:
            raise RuntimeError(
                "SILICONFLOW_API_KEY 未配置！请在 backend/.env 中设置。"
            )

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def dimension(self) -> int:
        return self._dimension

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=httpx.Timeout(60.0, connect=10.0),
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
            )
        return self._client

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        client = await self._get_client()
        # 不传 dimensions，让模型输出默认维度（4B/8B = 4096 维）
        response = await client.post(
            "/embeddings",
            json={"model": self._model, "input": texts},
        )
        response.raise_for_status()
        data = response.json()
        # 按 index 排序
        items = sorted(data["data"], key=lambda x: x["index"])
        return [item["embedding"] for item in items]

    async def embed_query(self, text: str) -> list[float]:
        results = await self.embed_documents([text])
        return results[0]

    async def aclose(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
