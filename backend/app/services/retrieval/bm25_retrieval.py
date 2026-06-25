"""BM25 检索策略（使用 rank_bm25 库 + pickle 索引）。"""
import logging
import pickle
from pathlib import Path
from typing import List, Dict, Any

from app.config import settings
from app.services.retrieval.base import RetrievalStrategy
from app.services.vectorstore import get_collection

logger = logging.getLogger(__name__)

# BM25 索引目录
BM25_DIR = Path(settings.CHROMADB_PATH).parent / "bm25_index"
BM25_DIR.mkdir(parents=True, exist_ok=True)


class BM25Retrieval(RetrievalStrategy):
    """BM25 关键词检索（与向量检索互补）。

    索引按 KB 缓存到本地 pickle：
    - {kb_id}_chunks.pkl
    - {kb_id}_index.pkl
    """

    def __init__(self):
        self._indices: dict = {}  # kb_id -> (chunks, bm25_index)

    @property
    def strategy_name(self) -> str:
        return "bm25"

    def _load_index(self, kb_id: int):
        """加载或构建 BM25 索引。"""
        if kb_id in self._indices:
            return self._indices[kb_id]

        chunks_path = BM25_DIR / f"{kb_id}_chunks.pkl"
        index_path = BM25_DIR / f"{kb_id}_index.pkl"

        if chunks_path.exists() and index_path.exists():
            with chunks_path.open("rb") as f:
                chunks = pickle.load(f)
            with index_path.open("rb") as f:
                index = pickle.load(f)
            self._indices[kb_id] = (chunks, index)
            return chunks, index

        # 首次构建：从 ChromaDB 读出该 KB 的所有 chunk
        collection = get_collection()
        all_data = collection.get(where={"kb_id": kb_id})
        if not all_data.get("documents"):
            return [], None

        chunks = [
            {
                "chunk_id": meta.get("chunk_id", str(i)),
                "doc_id": meta.get("doc_id", 0),
                "filename": meta.get("filename", ""),
                "page": meta.get("page"),
                "content": doc,
            }
            for i, (doc, meta) in enumerate(zip(all_data["documents"], all_data["metadatas"]))
        ]

        try:
            from rank_bm25 import BM25Okapi
            import jieba
            tokenized_corpus = [list(jieba.cut(c["content"])) for c in chunks]
            index = BM25Okapi(tokenized_corpus)
        except ImportError:
            logger.error("BM25 需要 rank_bm25 和 jieba 库")
            return chunks, None

        # 缓存
        with chunks_path.open("wb") as f:
            pickle.dump(chunks, f)
        with index_path.open("wb") as f:
            pickle.dump(index, f)

        self._indices[kb_id] = (chunks, index)
        return chunks, index

    async def retrieve(
        self,
        query: str,
        kb_ids: List[int],
        top_k: int = 5,
        search_all: bool = False,
        **kwargs,
    ) -> List[Dict[str, Any]]:
        import jieba
        target_kbs = kb_ids if not search_all else list(self._indices.keys())
        if not target_kbs:
            return []

        all_scores: list[tuple[float, dict]] = []
        for kb_id in target_kbs:
            chunks, index = self._load_index(kb_id)
            if not chunks or index is None:
                continue
            tokenized_query = list(jieba.cut(query))
            scores = index.get_scores(tokenized_query)
            for i, score in enumerate(scores):
                if score > 0:
                    all_scores.append((float(score), chunks[i]))

        all_scores.sort(key=lambda x: x[0], reverse=True)
        results = []
        for score, chunk in all_scores[:top_k]:
            results.append({**chunk, "score": round(score, 4)})
        return results


def invalidate_index(kb_id: int):
    """KB 内容变更后调用，删除旧 BM25 索引。"""
    chunks_path = BM25_DIR / f"{kb_id}_chunks.pkl"
    index_path = BM25_DIR / f"{kb_id}_index.pkl"
    chunks_path.unlink(missing_ok=True)
    index_path.unlink(missing_ok=True)
