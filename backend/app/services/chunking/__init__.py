"""Chunking 策略模块化。

按 strategy 字符串自动选择：
- "fixed_size"    → FixedSizeChunker
- "recursive"    → RecursiveChunker
- "semantic"     → SemanticChunker
"""
from app.services.chunking.factory import get_chunker

__all__ = ["get_chunker"]
