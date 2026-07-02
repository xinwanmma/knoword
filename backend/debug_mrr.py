"""分析 BAAI rerank vs vector 的 MRR 差异具体在哪些 task。"""
import json

with open("D:/HHHUBS/clone/knoword/backend/reports/eval_1_20260702_073613_3360545f.json", "r", encoding="utf-8") as f:
    data = json.load(f)

# 按 strategy 分组
from collections import defaultdict
by_strategy = defaultdict(list)
for r in data["results"]:
    key = f"{r['retrieval_strategy']}|{r.get('rerank_model') or '-'}"
    by_strategy[key].append(r)

# 对比 vector vs BAAI rerank
for key in ["vector|-", "rerank|BAAI/bge-reranker-base", "rerank|Qwen/Qwen3-Reranker-4B"]:
    if key not in by_strategy:
        continue
    tasks = by_strategy[key]
    print(f"\n=== {key} ({len(tasks)} tasks) ===")
    for t in tasks:
        q_idx = t["qa_index"]
        q = t["question"][:40]
        m = t["retrieval_metrics"]
        # ground truth chunk_id（从 source_chunk_ids 取）
        gt_chunks = t.get("ground_truth", "")[:20]
        # 看 retrieved 第 1 个的 chunk_id
        top1 = t["retrieved_chunks"][0]["chunk_id"] if t.get("retrieved_chunks") else "-"
        # ground truth chunk_id
        # 从 task 拿 source_chunk_ids（result 字段没存，从原 ground_truth 推算；只能从 QA 顺序匹配 dataset）
        # 直接从 task 看 "gt" 字段没有，只能靠看 retrieved 里有没有 chunk_70/22/109/...
        # 简化：直接显示 retrieved top-3 chunk_id
        top3 = [c["chunk_id"].split("_chunk_")[1] for c in t["retrieved_chunks"][:3]]
        print(f"  qa[{q_idx}] MRR={m['mrr']} hit={m['hit_at_k']} | top1-3: {top3} | Q: {q}...")
