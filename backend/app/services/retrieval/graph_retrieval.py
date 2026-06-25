"""GraphRAG 检索策略 — 微软 GraphRAG（预留占位）。

需要安装 microsoft graphrag 库，并先对 KB 构建 graph index。
"""
import logging
from typing import List, Dict, Any

from app.services.retrieval.base import RetrievalStrategy

logger = logging.getLogger(__name__)


class GraphRetrieval(RetrievalStrategy):
    """Microsoft GraphRAG（图结构 RAG）。

    ⚠️ 首次完整实现：需要：
    1. pip install graphrag
    2. 对每个 KB 单独跑 indexing（耗时，按文档量 5-30 分钟）
    3. 索引产物: {kb_id}/entities.parquet, relationships.parquet, communities.parquet

    当前为占位实现，直接 fall back 到向量检索。
    """

    def __init__(self, embedding_model: str | None = None):
        self._embedding_model = embedding_model
        # Fallback：实例化向量检索
        from app.services.retrieval.vector_retrieval import VectorRetrieval
        self._fallback = VectorRetrieval(embedding_model)

    @property
    def strategy_name(self) -> str:
        return "graph"

    async def retrieve(
        self,
        query: str,
        kb_ids: List[int],
        top_k: int = 5,
        search_all: bool = False,
        **kwargs,
    ) -> List[Dict[str, Any]]:
        logger.warning("GraphRetrieval 暂未完整实现，fallback 到向量检索")
        return await self._fallback.retrieve(
            query=query,
            kb_ids=kb_ids,
            top_k=top_k,
            search_all=search_all,
        )
