"""语义切块（langchain_experimental SemanticChunker）。"""
from langchain_experimental.text_splitter import SemanticChunker as LCSemanticChunker

from app.services.chunking.base import Chunker


class SemanticChunker(Chunker):
    """基于 embedding 相似度的语义切块。

    依赖：langchain-experimental + 当前 KB 的 embedding provider。
    """

    def __init__(self, embeddings, breakpoint_threshold_type: str = "percentile"):
        self._splitter = LCSemanticChunker(
            embeddings=embeddings,
            breakpoint_threshold_type=breakpoint_threshold_type,
        )

    @property
    def strategy_name(self) -> str:
        return "semantic"

    def split(self, text: str) -> list[str]:
        return [doc.page_content for doc in self._splitter.create_documents([text])]
