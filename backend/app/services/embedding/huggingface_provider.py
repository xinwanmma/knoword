"""HuggingFace Embedding Provider — 本地离线加载。

模型统一缓存在 C:\\Users\\13596\\.cache\\huggingface\\hub\\
首次启动时若不存在自动下载（只下一次），之后强制离线。
"""
import logging
import os
from pathlib import Path

from app.config import settings
from app.services.embedding.base import EmbeddingProvider

logger = logging.getLogger(__name__)


class HuggingFaceProvider(EmbeddingProvider):
    """通过 sentence-transformers 从本地加载 embedding 模型（离线模式）。

    默认模型：shibing624/text2vec-base-chinese
    维度：768
    """

    DEFAULT_DIMENSION = 768

    def __init__(self, model_id: str | None = None):
        self._model_id = model_id or settings.HF_EMBED_MODEL
        # 解析 HF 缓存目录
        self._hf_cache_dir = Path(settings.HF_CACHE_DIR)
        # HF 缓存目录下的子目录名（models--作者--模型）
        safe_id = self._model_id.replace("/", "--")
        self._local_dir = self._hf_cache_dir / f"models--{safe_id}"

        self._model = None  # SentenceTransformer 实例（懒加载）
        self._dimension = self.DEFAULT_DIMENSION

    @property
    def model_name(self) -> str:
        return self._model_id

    @property
    def dimension(self) -> int:
        return self._dimension

    def _ensure_model(self):
        """懒加载：首次使用时下载 + 加载。"""
        if self._model is not None:
            return self._model

        # 1. 本地不存在 → 下载（一次性）
        if not self._local_dir.exists():
            self._download_model()

        # 2. 强制离线模式
        os.environ["HF_HOME"] = str(self._hf_cache_dir.parent)
        os.environ["TRANSFORMERS_CACHE"] = str(self._hf_cache_dir)
        if settings.HF_OFFLINE:
            os.environ["TRANSFORMERS_OFFLINE"] = "1"
            os.environ["HF_DATASETS_OFFLINE"] = "1"
            os.environ["HF_HUB_OFFLINE"] = "1"

        # 3. 从本地加载
        from sentence_transformers import SentenceTransformer
        logger.info(f"从本地加载 embedding 模型: {self._local_dir}")
        self._model = SentenceTransformer(str(self._local_dir))
        self._dimension = self._model.get_sentence_embedding_dimension()
        return self._model

    def _download_model(self):
        """首次下载到 HF 官方缓存目录（仅一次）。"""
        logger.info(f"首次下载 embedding 模型 {self._model_id} 到 {self._hf_cache_dir}")
        # 下载前先关闭离线模式
        os.environ.pop("TRANSFORMERS_OFFLINE", None)
        os.environ.pop("HF_HUB_OFFLINE", None)
        from huggingface_hub import snapshot_download
        snapshot_download(
            repo_id=self._model_id,
            cache_dir=str(self._hf_cache_dir),
        )

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        model = self._ensure_model()
        # sentence-transformers 是 CPU/GPU 同步阻塞，丢到线程池
        import asyncio
        vectors = await asyncio.to_thread(
            model.encode, texts, normalize_embeddings=True
        )
        return [v.tolist() for v in vectors]

    async def embed_query(self, text: str) -> list[float]:
        results = await self.embed_documents([text])
        return results[0]
