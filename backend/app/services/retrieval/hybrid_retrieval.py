"""Hybrid Fusion 混合检索策略：vector 召回 + BM25 召回 → 合并去重 → 加权融合。

流程：
1. vector 召回 top_n_vec (默认 20) — ChromaDB cosine 相似度
2. BM25 召回 top_n_bm25 (默认 20) — jieba + BM25Okapi（本地 pickle 缓存）
3. 两种分数分别归一化到 [0, 1]（min-max）
4. 加权融合：score = alpha * vec_norm + (1 - alpha) * bm25_norm
5. 按 chunk_id 合并去重，同 chunk 累加分数
6. 取 top_k

与纯 vector / 纯 BM25 对比：
- 纯 vector：依赖 embedding 语义，对关键词 / 专有名词召回弱
- 纯 BM25：依赖关键词，对长 query / 语义近似召回弱
- Hybrid：两者互补，长 query 关键词 + 语义都能命中

BM25 索引目录仍用 bm25_index/（保留 pickle 缓存，避免重新构建）。
文档处理完成时调 invalidate_index() 失效缓存。
"""
import logging
import pickle
from pathlib import Path
from typing import List, Dict, Any

from app.config import settings
from app.services.embedding import get_embedding_provider
from app.services.retrieval.base import RetrievalStrategy
from app.services.vectorstore import get_collection, search_documents

logger = logging.getLogger(__name__)


# BM25 索引目录（保留旧目录结构，兼容已有 pickle 缓存）
BM25_DIR = Path(settings.CHROMADB_PATH).parent / "bm25_index"
BM25_DIR.mkdir(parents=True, exist_ok=True)


class HybridRetrieval(RetrievalStrategy):
    """Hybrid Fusion 混合检索：vector + BM25 加权融合。

    适用场景：
    - 文档既有大量专有名词 / 关键词（BM25 强项）
    - 也有需要语义理解的描述（vector 强项）
    - 用户期望"两种召回结合"的质量

    参数：
    - embedding_model: str | None — 用于 vector 召回的 embedding 模型
    - alpha: float = 0.5 — vector 权重；1-alpha 是 BM25 权重（0=纯 BM25, 1=纯 vector）
    - top_n_vec: int = 20 — vector 召回候选数（> top_k，保证融合后有足够候选）
    - top_n_bm25: int = 20 — BM25 召回候选数
    """

    def __init__(
        self,
        embedding_model: str | None = None,
        alpha: float = 0.5,
        top_n_vec: int = 20,
        top_n_bm25: int = 20,
    ):
        self._embedder = get_embedding_provider(embedding_model) if embedding_model else None
        self._alpha = alpha
        self._top_n_vec = top_n_vec
        self._top_n_bm25 = top_n_bm25
        # BM25 索引缓存：kb_id -> (chunks, bm25_index)
        self._indices: dict = {}

    @property
    def strategy_name(self) -> str:
        return "hybrid"

    # ===== BM25 索引加载（与原 BM25Retrieval 一致，保留 pickle 缓存兼容）=====

    def _load_bm25_index(self, kb_id: int):
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

    # ===== Vector 召回 =====

    async def _retrieve_vector(
        self, query: str, kb_ids: List[int], top_n: int, search_all: bool,
    ) -> List[Dict[str, Any]]:
        """vector 召回 top_n 个候选。返回 [{chunk_id, ..., vec_score}, ...]"""
        if not self._embedder:
            logger.warning("HybridRetrieval 缺少 embedding_model，跳过 vector 召回")
            return []
        if not kb_ids and not search_all:
            return []

        query_emb = await self._embedder.embed_query(query)

        if kb_ids and not search_all:
            where_filter = (
                {"kb_id": kb_ids[0]} if len(kb_ids) == 1
                else {"kb_id": {"$in": kb_ids}}
            )
        else:
            where_filter = None

        results = search_documents(
            query_embedding=query_emb,
            n_results=top_n,
            where=where_filter,
        )
        if not results.get("documents"):
            return []

        chunks = []
        for doc, meta, dist in zip(
            results["documents"], results["metadatas"], results["distances"]
        ):
            chunks.append({
                "chunk_id": meta.get("chunk_id", ""),
                "doc_id": meta.get("doc_id", 0),
                "filename": meta.get("filename", ""),
                "page": meta.get("page"),
                "content": doc,
                # 距离 → 相似度 (ChromaDB cosine: 距离 = 1 - cos_sim)
                "vec_score": round(1 - dist, 4),
            })
        return chunks

    # ===== BM25 召回 =====

    def _retrieve_bm25(
        self, query: str, kb_ids: List[int], top_n: int, search_all: bool,
    ) -> List[Dict[str, Any]]:
        """BM25 召回 top_n 个候选。返回 [{chunk_id, ..., bm25_score}, ...]"""
        import jieba
        target_kbs = kb_ids if not search_all else list(self._indices.keys())
        if not target_kbs:
            return []

        all_scores: list[tuple[float, dict]] = []
        for kb_id in target_kbs:
            chunks, index = self._load_bm25_index(kb_id)
            if not chunks or index is None:
                continue
            tokenized_query = list(jieba.cut(query))
            scores = index.get_scores(tokenized_query)
            for i, score in enumerate(scores):
                if score > 0:
                    all_scores.append((float(score), chunks[i]))

        all_scores.sort(key=lambda x: x[0], reverse=True)
        return [
            {**chunk, "bm25_score": round(score, 4)}
            for score, chunk in all_scores[:top_n]
        ]

    # ===== Hybrid Fusion 主流程 =====

    async def retrieve(
        self,
        query: str,
        kb_ids: List[int],
        top_k: int = 5,
        search_all: bool = False,
        **kwargs,
    ) -> List[Dict[str, Any]]:
        """vector + BM25 召回 → 归一化 → 加权融合 → top_k。"""
        # 1. 两种召回并行（vector 是 async，BM25 是 sync；分两步）
        vec_chunks = await self._retrieve_vector(
            query, kb_ids, self._top_n_vec, search_all,
        )
        bm25_chunks = self._retrieve_bm25(
            query, kb_ids, self._top_n_bm25, search_all,
        )

        if not vec_chunks and not bm25_chunks:
            return []

        # 2. 按 chunk_id 合并去重
        merged: dict[str, dict] = {}
        # 先放 vector
        for c in vec_chunks:
            merged[c["chunk_id"]] = {
                "chunk_id": c["chunk_id"],
                "doc_id": c.get("doc_id", 0),
                "filename": c.get("filename", ""),
                "page": c.get("page"),
                "content": c["content"],
                "vec_score": c.get("vec_score", 0.0),
                "bm25_score": 0.0,
            }
        # 合并 BM25
        for c in bm25_chunks:
            cid = c["chunk_id"]
            if cid in merged:
                merged[cid]["bm25_score"] = c.get("bm25_score", 0.0)
            else:
                merged[cid] = {
                    "chunk_id": cid,
                    "doc_id": c.get("doc_id", 0),
                    "filename": c.get("filename", ""),
                    "page": c.get("page"),
                    "content": c["content"],
                    "vec_score": 0.0,
                    "bm25_score": c.get("bm25_score", 0.0),
                }

        # 3. 分数归一化到 [0, 1]（min-max）
        def min_max_norm(values: List[float]) -> List[float]:
            if not values:
                return []
            lo, hi = min(values), max(values)
            if hi - lo < 1e-9:
                return [1.0] * len(values)  # 全相等
            return [(v - lo) / (hi - lo) for v in values]

        vec_scores = [c["vec_score"] for c in merged.values()]
        bm25_scores = [c["bm25_score"] for c in merged.values()]
        vec_norm = min_max_norm(vec_scores)
        bm25_norm = min_max_norm(bm25_scores)

        # 4. 加权融合
        fused: list[dict] = []
        for c, v_n, b_n in zip(merged.values(), vec_norm, bm25_norm):
            fused_score = self._alpha * v_n + (1 - self._alpha) * b_n
            fused.append({**c, "score": round(fused_score, 4)})

        # 5. 排序取 top_k
        fused.sort(key=lambda x: x["score"], reverse=True)
        return fused[:top_k]


def invalidate_index(kb_id: int):
    """文档处理完成后调用，删除 BM25 缓存 pickle。

    保留旧函数名以兼容调用点（document_processor.py 引用了此名）。
    """
    chunks_path = BM25_DIR / f"{kb_id}_chunks.pkl"
    index_path = BM25_DIR / f"{kb_id}_index.pkl"
    chunks_path.unlink(missing_ok=True)
    index_path.unlink(missing_ok=True)
