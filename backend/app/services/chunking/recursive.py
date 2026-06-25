"""递归字符切块（LangChain RecursiveCharacterTextSplitter，推荐默认）。"""
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.services.chunking.base import Chunker


class RecursiveChunker(Chunker):
    """递归按字符切分（按段落、句子、词逐级回退）。"""

    def __init__(self, chunk_size: int = 500, chunk_overlap: int = 50):
        self._splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=["\n\n", "\n", "。", "！", "？", ".", "!", "?", " ", ""],
        )

    @property
    def strategy_name(self) -> str:
        return "recursive"

    def split(self, text: str) -> list[str]:
        return [doc.page_content for doc in self._splitter.create_documents([text])]
