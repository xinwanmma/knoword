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
- enabled: set[str] | None — 启用的指标 key；None = 全开

输出：
- dict[str, float] — 仅包含 enabled 中的 key，0-1
"""
import math
from typing import List, Dict, Optional, Set


# 5 个标准检索指标的标准 key
STANDARD_RETRIEVAL_KEYS: tuple[str, ...] = (
    "recall_at_k", "precision_at_k", "hit_at_k", "mrr", "ndcg_at_k",
)


def compute_retrieval_metrics(
    retrieved_ids: List[str],
    source_chunk_ids: List[str],
    k: int = 5,
    enabled: Optional[Set[str]] = None,
) -> Dict[str, float]:
    """计算 5 个标准检索指标。

    enabled=None → 全开 5 个；enabled=set → 仅返回集合内 key。

    容错：
    - source_chunk_ids 为空 → 全部 0
    - k=0 → precision/recall/ndcg 全 0，hit/mrr 也是 0
    - retrieved_ids 为空 → 全部 0
    """
    # 决定要算哪些 key
    keys = set(enabled) if enabled is not None else set(STANDARD_RETRIEVAL_KEYS)
    # 永远不算 enabled 之外的 key（即使计算了也不返回）
    keys &= set(STANDARD_RETRIEVAL_KEYS)

    # 全部禁用 → 立即返回空 dict
    if not keys:
        return {}

    if k <= 0:
        return {key: 0.0 for key in keys}

    relevant = set(source_chunk_ids or [])
    retrieved_k = list(retrieved_ids or [])[:k]

    # === Recall@K ===
    if "recall_at_k" in keys:
        if relevant and retrieved_k:
            recall = len(set(retrieved_k) & relevant) / len(relevant)
        else:
            recall = 0.0
    else:
        recall = None

    # === Precision@K ===
    if "precision_at_k" in keys:
        if retrieved_k:
            precision = len(set(retrieved_k) & relevant) / k
        else:
            precision = 0.0
    else:
        precision = None

    # === Hit@K ===
    if "hit_at_k" in keys:
        hit = 1.0 if (relevant and (set(retrieved_k) & relevant)) else 0.0
    else:
        hit = None

    # === MRR ===
    if "mrr" in keys:
        mrr = 0.0
        for i, cid in enumerate(retrieved_k, start=1):
            if cid in relevant:
                mrr = 1.0 / i
                break
    else:
        mrr = None

    # === NDCG@K（binary relevance）===
    if "ndcg_at_k" in keys:
        # DCG = sum(rel_i / log2(i+2)), i 从 0 开始
        dcg = 0.0
        for i, cid in enumerate(retrieved_k):
            rel = 1.0 if cid in relevant else 0.0
            dcg += rel / math.log2(i + 2)
        # IDCG = 理想排序（所有相关都排在前 K）
        ideal_count = min(len(relevant), k)
        idcg = sum(1.0 / math.log2(i + 2) for i in range(ideal_count))
        ndcg = dcg / idcg if idcg > 0 else 0.0
    else:
        ndcg = None

    out: Dict[str, float] = {}
    for key, val in (
        ("recall_at_k", recall), ("precision_at_k", precision),
        ("hit_at_k", hit), ("mrr", mrr), ("ndcg_at_k", ndcg),
    ):
        if key in keys and val is not None:
            out[key] = round(val, 4) if key != "hit_at_k" else val
    return out
