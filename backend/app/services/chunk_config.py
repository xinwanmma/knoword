"""分块策略配置管理 — 允许动态调整分块参数并预览效果。"""

import logging
from dataclasses import dataclass

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class ChunkConfig:
    """分块配置。"""
    target_tokens: int = 300
    max_tokens: int = 512
    overlap_sentences: int = 2
    strategy: str = "sentence"  # sentence / fixed / paragraph


# 默认配置
DEFAULT_CONFIG = ChunkConfig()


def get_chunk_config() -> ChunkConfig:
    """获取当前分块配置。"""
    return ChunkConfig(
        target_tokens=settings.CHUNK_TARGET_TOKENS,
        max_tokens=settings.CHUNK_MAX_TOKENS,
        overlap_sentences=settings.CHUNK_OVERLAP_SENTENCES,
    )


def preview_chunks(text: str, config: ChunkConfig | None = None) -> list[dict]:
    """预览分块效果（不写入数据库）。

    Args:
        text: 输入文本
        config: 分块配置，None 使用当前配置

    Returns:
        [{"chunk_index": 0, "text": "...", "token_count": 150, "char_count": 450}, ...]
    """
    from app.services.chunker import chunk_text

    cfg = config or get_chunk_config()

    # 将文本包装成 pages 格式
    pages = [{"page": 1, "text": text}]

    chunks = chunk_text(
        pages,
        target_tokens=cfg.target_tokens,
        max_tokens=cfg.max_tokens,
        overlap_sentences=cfg.overlap_sentences,
    )

    import tiktoken
    enc = tiktoken.get_encoding("cl100k_base")

    results = []
    for chunk in chunks:
        token_count = len(enc.encode(chunk.text))
        results.append({
            "chunk_index": chunk.chunk_index,
            "text": chunk.text[:200] + "..." if len(chunk.text) > 200 else chunk.text,
            "full_text": chunk.text,
            "token_count": token_count,
            "char_count": len(chunk.text),
            "page": chunk.page,
        })

    return results


def compare_strategies(text: str) -> dict:
    """对比不同分块策略的效果。

    Returns:
        {
            "small_chunks": {...},
            "medium_chunks": {...},
            "large_chunks": {...},
        }
    """
    strategies = {
        "small_chunks (target=150, max=256)": ChunkConfig(target_tokens=150, max_tokens=256, overlap_sentences=1),
        "medium_chunks (target=300, max=512)": ChunkConfig(target_tokens=300, max_tokens=512, overlap_sentences=2),
        "large_chunks (target=600, max=1024)": ChunkConfig(target_tokens=600, max_tokens=1024, overlap_sentences=3),
    }

    results = {}
    for name, cfg in strategies.items():
        chunks = preview_chunks(text, cfg)
        results[name] = {
            "total_chunks": len(chunks),
            "avg_tokens": round(sum(c["token_count"] for c in chunks) / max(len(chunks), 1)),
            "avg_chars": round(sum(c["char_count"] for c in chunks) / max(len(chunks), 1)),
            "chunks": [{"index": c["chunk_index"], "tokens": c["token_count"], "preview": c["text"][:80]} for c in chunks],
        }

    return results
