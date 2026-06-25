"""Chunking Factory — 按 strategy 字符串自动选择。"""
import logging
from typing import Dict, Type

from app.services.chunking.base import Chunker
from app.services.chunking.fixed_size import FixedSizeChunker
from app.services.chunking.recursive import RecursiveChunker
from app.services.chunking.semantic import SemanticChunker

logger = logging.getLogger(__name__)

CHUNKING_REGISTRY: Dict[str, Type[Chunker]] = {
    "fixed_size": FixedSizeChunker,
    "recursive": RecursiveChunker,
    "semantic": SemanticChunker,
}


def get_chunker(
    strategy: str = "recursive",
    chunk_size: int = 500,
    chunk_overlap: int = 50,
    embeddings=None,  # 仅 semantic 需要
) -> Chunker:
    """获取切块器实例。

    Args:
        strategy: 切块策略 (fixed_size / recursive / semantic)
        chunk_size: 块大小
        chunk_overlap: 块重叠
        embeddings: 仅 semantic 策略需要传入 embedding 实例
    """
    if strategy not in CHUNKING_REGISTRY:
        available = ", ".join(CHUNKING_REGISTRY.keys())
        raise ValueError(f"未知的切块策略: {strategy}。可用: {available}")

    if strategy == "semantic":
        if embeddings is None:
            raise ValueError("semantic 切块需要传入 embeddings 实例")
        return SemanticChunker(embeddings=embeddings, breakpoint_threshold_type="percentile")
    elif strategy == "fixed_size":
        return FixedSizeChunker(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    else:
        return RecursiveChunker(chunk_size=chunk_size, chunk_overlap=chunk_overlap)


def list_available_strategies() -> list[str]:
    return list(CHUNKING_REGISTRY.keys())
