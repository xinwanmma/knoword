"""混合检索 — BM25 关键词检索 + 向量语义检索的融合。

核心思路：
- BM25 擅长精确关键词匹配（如搜索"年假"精确命中含"年假"的文档）
- 向量检索擅长语义理解（如搜索"假期"能找到含"年假"的文档）
- 两者融合，取长补短，提升整体检索质量
"""

import logging

from app.config import settings
from app.services.ollama_service import get_embedding
from app.services.vectorstore import search_documents

logger = logging.getLogger(__name__)


def _tokenize_chinese(text: str) -> list[str]:
    """简单的中文分词（基于字符 + 常见词组合）。

    生产环境应替换为 jieba / pkuseg 等专业分词器。
    """
    tokens = []
    # 按标点和空格切分
    import re
    segments = re.split(r'[，。！？；：、\s,.!?;:\n\r]+', text)
    for seg in segments:
        seg = seg.strip()
        if not seg:
            continue
        # 单字、双字、整段都加入
        tokens.append(seg)
        for i in range(len(seg)):
            tokens.append(seg[i])
            if i + 1 < len(seg):
                tokens.append(seg[i:i+2])
    return [t for t in tokens if t.strip()]


def _bm25_score(query_tokens: list[str], doc_tokens: list[str], avg_dl: float = 1.0, k1: float = 1.5, b: float = 0.75) -> float:
    """简化版 BM25 评分。

    Args:
        query_tokens: 查询分词
        doc_tokens: 文档分词
        avg_dl: 语料库平均文档长度
        k1: 词频饱和参数
        b: 文档长度归一化参数

    Returns:
        BM25 分数
    """
    from collections import Counter

    doc_counter = Counter(doc_tokens)
    doc_len = len(doc_tokens)
    avg_dl = max(avg_dl, 1)

    score = 0.0
    for qt in query_tokens:
        if qt not in doc_counter:
            continue
        tf = doc_counter[qt]
        numerator = tf * (k1 + 1)
        denominator = tf + k1 * (1 - b + b * doc_len / avg_dl)
        score += numerator / denominator

    return score


async def hybrid_search(
    query: str,
    kb_ids: list[int] | None = None,
    n_results: int = 5,
    vector_weight: float = 0.6,
    bm25_weight: float = 0.4,
) -> dict:
    """混合检索：BM25 + 向量检索，加权融合。

    Args:
        query: 查询文本
        kb_ids: 知识库 ID 过滤
        n_results: 返回结果数
        vector_weight: 向量检索权重
        bm25_weight: BM25 检索权重

    Returns:
        与 search_documents 格式兼容的结果
    """
    # 1. 向量检索
    query_embedding = await get_embedding(query)
    if kb_ids:
        if len(kb_ids) == 1:
            where_filter = {"kb_id": kb_ids[0]}
        else:
            where_filter = {"kb_id": {"$in": kb_ids}}
    else:
        where_filter = None

    vector_results = search_documents(
        query_embedding=query_embedding,
        n_results=n_results * 2,  # 多取一些用于融合
        where=where_filter,
    )

    if not vector_results.get("documents"):
        return vector_results

    # 2. BM25 评分（基于已有向量结果）
    query_tokens = _tokenize_chinese(query)

    # 归一化向量分数
    vector_scores = [1.0 - d for d in vector_results["distances"]]  # distance → similarity
    max_vs = max(vector_scores) if vector_scores else 1.0
    vector_scores = [s / max_vs if max_vs > 0 else 0 for s in vector_scores]

    # BM25 评分
    doc_token_lists = []
    for doc in vector_results["documents"]:
        doc_token_lists.append(_tokenize_chinese(doc))

    # 计算全局平均文档长度用于归一化
    avg_dl = sum(len(dt) for dt in doc_token_lists) / max(len(doc_token_lists), 1)

    bm25_scores = []
    for doc_tokens in doc_token_lists:
        bm25_scores.append(_bm25_score(query_tokens, doc_tokens, avg_dl=avg_dl))

    max_bs = max(bm25_scores) if bm25_scores else 1.0
    bm25_scores = [s / max_bs if max_bs > 0 else 0 for s in bm25_scores]

    # 3. 加权融合
    fused_scores = []
    for i in range(len(vector_scores)):
        fused = vector_weight * vector_scores[i] + bm25_weight * bm25_scores[i]
        fused_scores.append(fused)

    # 4. 排序取 top_n
    ranked_indices = sorted(range(len(fused_scores)), key=lambda i: fused_scores[i], reverse=True)[:n_results]

    return {
        "ids": [vector_results["ids"][i] for i in ranked_indices],
        "documents": [vector_results["documents"][i] for i in ranked_indices],
        "metadatas": [vector_results["metadatas"][i] for i in ranked_indices],
        "distances": [1.0 - fused_scores[i] for i in ranked_indices],  # 转回 distance
    }


async def check_hybrid_available() -> dict:
    """检查混合检索是否可用。"""
    return {
        "vector": True,  # 向量检索始终可用
        "bm25": True,    # BM25 本地计算，始终可用
        "hybrid": True,
    }
