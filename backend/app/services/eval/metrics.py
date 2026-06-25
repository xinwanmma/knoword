"""评估指标计算。"""
from typing import List, Set


def hit_at_k(retrieved_ids: List[str], ground_truth_ids: Set[str], k: int = 5) -> float:
    """Hit@K：前 K 个结果中是否包含任意一个 ground truth。"""
    top_k = retrieved_ids[:k]
    return 1.0 if any(rid in ground_truth_ids for rid in top_k) else 0.0


def recall_at_k(retrieved_ids: List[str], ground_truth_ids: Set[str], k: int = 5) -> float:
    """Recall@K：前 K 个结果中 ground truth 占比。"""
    if not ground_truth_ids:
        return 0.0
    top_k = set(retrieved_ids[:k])
    return len(top_k & ground_truth_ids) / len(ground_truth_ids)


def mrr(retrieved_ids: List[str], ground_truth_ids: Set[str]) -> float:
    """Mean Reciprocal Rank：第一个相关结果的位置的倒数。"""
    for i, rid in enumerate(retrieved_ids):
        if rid in ground_truth_ids:
            return 1.0 / (i + 1)
    return 0.0


def ndcg_at_k(retrieved_ids: List[str], ground_truth_ids: Set[str], k: int = 5) -> float:
    """NDCG@K：归一化折损累计增益。"""
    import math
    if not ground_truth_ids:
        return 0.0
    top_k = retrieved_ids[:k]
    # DCG
    dcg = sum(
        1.0 / math.log2(i + 2) for i, rid in enumerate(top_k) if rid in ground_truth_ids
    )
    # IDCG（理想情况：所有 ground truth 都在前 K）
    ideal_hits = min(k, len(ground_truth_ids))
    idcg = sum(1.0 / math.log2(i + 2) for i in range(ideal_hits))
    return dcg / idcg if idcg > 0 else 0.0


def compute_retrieval_metrics(
    retrieved_ids: List[str], source_chunk_ids: List[str], k: int = 5
) -> dict:
    """计算所有检索指标。"""
    gt_set = set(source_chunk_ids)
    return {
        "hit_at_5": hit_at_k(retrieved_ids, gt_set, k),
        "recall_at_5": recall_at_k(retrieved_ids, gt_set, k),
        "mrr": mrr(retrieved_ids, gt_set),
        "ndcg_at_5": ndcg_at_k(retrieved_ids, gt_set, k),
    }
