"""HuggingFace Rerank Provider — 本地离线加载。"""
import asyncio
import logging
import os
from pathlib import Path
from typing import List, Tuple

from app.config import settings
from app.services.rerank.base import RerankProvider

logger = logging.getLogger(__name__)


class HuggingFaceRerankProvider(RerankProvider):
    """使用 sentence-transformers CrossEncoder 本地离线 rerank。"""

    def __init__(self, model_id: str | None = None):
        self._model_id = model_id or settings.HF_RERANK_MODEL
        self._hf_cache_dir = Path(settings.HF_CACHE_DIR)
        safe_id = self._model_id.replace("/", "--")
        self._local_dir = self._hf_cache_dir / f"models--{safe_id}"

        self._model = None  # CrossEncoder 实例（懒加载）

    @property
    def model_name(self) -> str:
        return self._model_id

    def _ensure_model(self):
        if self._model is not None:
            return self._model

        # 1. 本地不存在 → 下载
        if not self._local_dir.exists():
            self._download_model()

        # 2. 强制离线
        os.environ["HF_HOME"] = str(self._hf_cache_dir.parent)
        if settings.HF_OFFLINE:
            os.environ["TRANSFORMERS_OFFLINE"] = "1"
            os.environ["HF_HUB_OFFLINE"] = "1"

        # 3. 加载 CrossEncoder
        from sentence_transformers import CrossEncoder
        logger.info(f"从本地加载 rerank 模型: {self._local_dir}")
        self._model = CrossEncoder(str(self._local_dir))
        return self._model

    def _download_model(self):
        logger.info(f"首次下载 rerank 模型 {self._model_id}")
        os.environ.pop("TRANSFORMERS_OFFLINE", None)
        os.environ.pop("HF_HUB_OFFLINE", None)
        from huggingface_hub import snapshot_download
        snapshot_download(
            repo_id=self._model_id,
            cache_dir=str(self._hf_cache_dir),
        )

    async def rerank(
        self, query: str, documents: List[str], top_k: int = 5
    ) -> List[Tuple[int, float]]:
        model = self._ensure_model()
        pairs = [[query, d] for d in documents]

        # 同步阻塞 → 丢到线程池
        scores = await asyncio.to_thread(model.predict, pairs)

        ranked = sorted(
            enumerate(scores),
            key=lambda x: float(x[1]),
            reverse=True,
        )[:top_k]
        return [(idx, float(score)) for idx, score in ranked]
