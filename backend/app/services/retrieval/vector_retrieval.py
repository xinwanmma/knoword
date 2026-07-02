"""向量检索策略。"""
import logging
from typing import List, Dict, Any

from app.services.embedding import get_embedding_provider
from app.services.retrieval.base import RetrievalStrategy
from app.services.vectorstore import search_documents

logger = logging.getLogger(__name__)


class VectorRetrieval(RetrievalStrategy):
    """纯向量检索（ChromaDB cosine 相似度）。"""

    def __init__(self, embedding_model: str | None = None):
        self._embedder = get_embedding_provider(embedding_model)

    @property
    def strategy_name(self) -> str:
        return "vector"

    async def retrieve(
        self,
        query: str,
        kb_ids: List[int],
        top_k: int = 5,
        search_all: bool = False,
        **kwargs,
    ) -> List[Dict[str, Any]]:
        if not kb_ids and not search_all:
            return []

        # 1. query 向量化
        query_emb = await self._embedder.embed_query(query)

        # 2. where 过滤
        if kb_ids and not search_all:
            if len(kb_ids) == 1:
                where_filter = {"kb_id": kb_ids[0]}
            else:
                where_filter = {"kb_id": {"$in": kb_ids}}
        else:
            where_filter = None

        # 3. 向量检索（按 embedding_model 路由 collection）
        results = search_documents(
            query_embedding=query_emb,
            n_results=top_k,
            where=where_filter,
            embedding_model=self._embedder.model_name,
        )

        if not results.get("documents"):
            return []

        # 4. 格式化
        chunks = []
        for doc, meta, dist in zip(
            results["documents"],
            results["metadatas"],
            results["distances"],
        ):
            chunks.append({
                "chunk_id": meta.get("chunk_id", ""),
                "doc_id": meta.get("doc_id", 0),
                "filename": meta.get("filename", ""),
                "page": meta.get("page"),
                "content": doc,
                "score": round(1 - dist, 4),
            })
        return chunks
