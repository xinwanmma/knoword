"""SiliconFlow Rerank Provider — 调用 https://api.siliconflow.cn/v1/rerank。"""
import logging
from typing import List, Tuple

import httpx

from app.config import settings
from app.services.rerank.base import RerankProvider

logger = logging.getLogger(__name__)


class SiliconFlowRerankProvider(RerankProvider):
    """调用 SiliconFlow 官方 rerank 接口（OpenAI 兼容）。"""

    def __init__(self, model_id: str | None = None):
        self._model_id = model_id or settings.SILICONFLOW_RERANK_MODEL
        self._url = settings.SILICONFLOW_RERANK_URL
        self._api_key = settings.SILICONFLOW_API_KEY
        if not self._api_key:
            raise RuntimeError("SILICONFLOW_API_KEY 未配置！")

    @property
    def model_name(self) -> str:
        return self._model_id

    async def rerank(
        self, query: str, documents: List[str], top_k: int = 5
    ) -> List[Tuple[int, float]]:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                self._url,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self._model_id,
                    "query": query,
                    "documents": documents,
                    "top_n": top_k,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            # data["results"] = [{"index": 0, "relevance_score": 0.95}, ...]
            return [
                (r["index"], float(r["relevance_score"]))
                for r in data["results"]
            ]
