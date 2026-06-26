"""检索指标计算 — 5 个标准指标。

定义（K = top_k）：
- Recall@K    = |retrieved[:K] ∩ relevant| / |relevant|
- Precision@K = |retrieved[:K] ∩ relevant| / K
- Hit@K       = 1 if any(retrieved[:K] ∩ relevant) else 0
- MRR         = 1 / rank_of_first_relevant（rank 从 1 开始）
- NDCG@K      = DCG@K / IDCG@K（binary relevance 0/1）

输入：
- retrieved_ids: list[str] — 按 rank 排序的 chunk_id
- source_chunk_ids: list[str] — 相关 chunk_id 集合
- k: int — top_k 截断（默认 5）

输出：
- dict[str, float] — 5 个指标，全部 0-1
"""
import math
from typing import List, Dict


def compute_retrieval_metrics(
    retrieved_ids: List[str],
    source_chunk_ids: List[str],
    k: int = 5,
) -> Dict[str, float]:
    """计算 5 个标准检索指标。

    容错：
    - source_chunk_ids 为空 → 全部 0
    - k=0 → precision/recall/ndcg 全 0，hit/mrr 也是 0
    - retrieved_ids 为空 → 全部 0
    """
    if k <= 0:
        return {
            "recall_at_k": 0.0,
            "precision_at_k": 0.0,
            "hit_at_k": 0.0,
            "mrr": 0.0,
            "ndcg_at_k": 0.0,
        }

    relevant = set(source_chunk_ids or [])
    retrieved_k = list(retrieved_ids or [])[:k]

    # === Recall@K ===
    if relevant and retrieved_k:
        recall = len(set(retrieved_k) & relevant) / len(relevant)
    else:
        recall = 0.0

    # === Precision@K ===
    if retrieved_k:
        precision = len(set(retrieved_k) & relevant) / k
    else:
        precision = 0.0

    # === Hit@K ===
    hit = 1.0 if (relevant and (set(retrieved_k) & relevant)) else 0.0

    # === MRR ===
    mrr = 0.0
    for i, cid in enumerate(retrieved_k, start=1):
        if cid in relevant:
            mrr = 1.0 / i
            break

    # === NDCG@K（binary relevance）===
    # DCG = sum(rel_i / log2(i+2)), i 从 0 开始
    dcg = 0.0
    for i, cid in enumerate(retrieved_k):
        rel = 1.0 if cid in relevant else 0.0
        dcg += rel / math.log2(i + 2)
    # IDCG = 理想排序（所有相关都排在前 K）
    ideal_count = min(len(relevant), k)
    idcg = sum(1.0 / math.log2(i + 2) for i in range(ideal_count))
    ndcg = dcg / idcg if idcg > 0 else 0.0

    return {
        "recall_at_k": round(recall, 4),
        "precision_at_k": round(precision, 4),
        "hit_at_k": hit,
        "mrr": round(mrr, 4),
        "ndcg_at_k": round(ndcg, 4),
    }
