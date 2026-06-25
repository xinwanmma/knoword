"""Rerank 检索策略：先向量初筛，再用 Rerank 重排。"""
import logging
from typing import List, Dict, Any

from app.services.embedding import get_embedding_provider
from app.services.rerank import get_rerank_provider
from app.services.retrieval.base import RetrievalStrategy
from app.services.vectorstore import search_documents

logger = logging.getLogger(__name__)


class RerankRetrieval(RetrievalStrategy):
    """向量初筛 + Rerank 重排。

    1. 向量初筛 top_n (默认 20)
    2. 调用 Rerank 模型对初筛结果重排
    3. 取 top_k 返回
    """

    def __init__(
        self,
        embedding_model: str | None = None,
        rerank_model: str | None = None,
        rerank_top_n: int = 20,
    ):
        self._embedder = get_embedding_provider(embedding_model)
        self._reranker = get_rerank_provider(rerank_model)
        self._rerank_top_n = rerank_top_n

    @property
    def strategy_name(self) -> str:
        return "rerank"

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

        # 1. 向量初筛
        query_emb = await self._embedder.embed_query(query)

        if kb_ids and not search_all:
            if len(kb_ids) == 1:
                where_filter = {"kb_id": kb_ids[0]}
            else:
                where_filter = {"kb_id": {"$in": kb_ids}}
        else:
            where_filter = None

        results = search_documents(
            query_embedding=query_emb,
            n_results=self._rerank_top_n,
            where=where_filter,
        )

        if not results.get("documents"):
            return []

        # 2. 构造候选列表
        candidates = [
            {
                "chunk_id": meta.get("chunk_id", ""),
                "doc_id": meta.get("doc_id", 0),
                "filename": meta.get("filename", ""),
                "page": meta.get("page"),
                "content": doc,
            }
            for doc, meta in zip(results["documents"], results["metadatas"])
        ]

        # 3. Rerank
        documents = [c["content"] for c in candidates]
        ranked = await self._reranker.rerank(query, documents, top_k=top_k)

        # 4. 格式化（保留 rerank 分数）
        return [
            {
                **candidates[idx],
                "score": round(rerank_score, 4),
                "rerank_score": round(rerank_score, 4),
            }
            for idx, rerank_score in ranked
        ]
