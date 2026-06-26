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
        self._hub_dir = self._hf_cache_dir / f"models--{safe_id}"
        # 实际传给 CrossEncoder 的是 snapshots/<hash>/ 目录（不是 hub 根）
        self._local_dir = self._hub_dir  # 懒解析，_ensure_model 里会修正

        self._model = None  # CrossEncoder 实例（懒加载）

    @property
    def model_name(self) -> str:
        return self._model_id

    def _resolve_local_dir(self) -> Path:
        """解析出真正的模型目录（snapshots/<hash>/），而不是 hub 根。

        HF 缓存标准结构:
          hub/models--org--name/
            blobs/  refs/main  snapshots/<hash>/config.json + *.safetensors
        CrossEncoder 需要 snapshots/<hash>/ 路径才能找到 config.json。
        """
        # 优先：读 refs/main 拿 hash
        ref_file = self._hub_dir / "refs" / "main"
        if ref_file.exists():
            snapshot_hash = ref_file.read_text().strip()
            snap = self._hub_dir / "snapshots" / snapshot_hash
            if snap.exists() and (snap / "config.json").exists():
                return snap
        # 兜底：扫 snapshots/ 取第一个有 config.json 的
        snapshots_dir = self._hub_dir / "snapshots"
        if snapshots_dir.exists():
            for d in snapshots_dir.iterdir():
                if d.is_dir() and (d / "config.json").exists():
                    return d
        # 旧布局（直接是文件）—— 兜底返回 hub_dir
        return self._hub_dir

    def _ensure_model(self):
        if self._model is not None:
            return self._model

        # 1. 本地不存在 → 下载
        if not self._hub_dir.exists():
            self._download_model()

        # 2. 解析真正的 snapshot 目录
        local_dir = self._resolve_local_dir()
        self._local_dir = local_dir

        # 3. 强制离线
        os.environ["HF_HOME"] = str(self._hf_cache_dir.parent)
        if settings.HF_OFFLINE:
            os.environ["TRANSFORMERS_OFFLINE"] = "1"
            os.environ["HF_HUB_OFFLINE"] = "1"

        # 4. 加载 CrossEncoder
        from sentence_transformers import CrossEncoder
        logger.info(f"从本地加载 rerank 模型: {local_dir}")
        self._model = CrossEncoder(str(local_dir))
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
