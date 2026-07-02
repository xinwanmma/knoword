"""一次性 helper：列出所有 KB + 所有 dataset + 关联信息。

用法：
    python -m scripts.list_kb_and_datasets
    或者 cd backend && python scripts/list_kb_and_datasets.py
"""
import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select, desc

from app.db.database import async_session_factory
from app.models.eval_models import EvaluationDataset
from app.models.models import KnowledgeBase, Document


async def main():
    print("=" * 80)
    print("Knowledge Bases (查 target_kb_id)")
    print("=" * 80)

    async with async_session_factory() as db:
        result = await db.execute(
            select(KnowledgeBase).order_by(KnowledgeBase.id)
        )
        kbs = result.scalars().all()

        for kb in kbs:
            # 算文档数和 chunk 总数
            doc_result = await db.execute(
                select(Document).where(Document.kb_id == kb.id)
            )
            docs = doc_result.scalars().all()
            total_chunks = sum(d.chunk_count or 0 for d in docs)

            print(f"\n  kb_id={kb.id}  name={kb.name!r}")
            print(f"    embedding: {kb.embedding_model}")
            print(f"    docs: {len(docs)} (total chunks: {total_chunks})")
            print(f"    created: {kb.created_at}")

    print("\n" + "=" * 80)
    print("Datasets (查 source_dataset_id)")
    print("=" * 80)

    async with async_session_factory() as db:
        result = await db.execute(
            select(EvaluationDataset).order_by(desc(EvaluationDataset.created_at))
        )
        datasets = result.scalars().all()

        for ds in datasets:
            n_qa = len(ds.qa_pairs or [])
            n_oos = sum(1 for q in (ds.qa_pairs or []) if q.get("is_out_of_scope"))
            n_mh = sum(1 for q in (ds.qa_pairs or []) if q.get("is_multihop"))
            print(f"\n  id={ds.id}")
            print(f"    name: {ds.name!r}")
            print(f"    kb_id: {ds.kb_id}  →  复制目标用这个")
            print(f"    qa_count: {n_qa}  (multi-hop: {n_mh}, OOS: {n_oos})")
            print(f"    created: {ds.created_at}")


if __name__ == "__main__":
    asyncio.run(main())
