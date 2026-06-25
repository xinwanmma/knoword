"""固定大小切块。"""
from langchain_text_splitters import CharacterTextSplitter

from app.services.chunking.base import Chunker


class FixedSizeChunker(Chunker):
    """按固定字符大小切分（简单粗暴）。"""

    def __init__(self, chunk_size: int = 500, chunk_overlap: int = 50):
        self._splitter = CharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separator="",
        )

    @property
    def strategy_name(self) -> str:
        return "fixed_size"

    def split(self, text: str) -> list[str]:
        return [doc.page_content for doc in self._splitter.create_documents([text])]
