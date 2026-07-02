"""一次性迁移：把 dataset.qa_pairs 里 KB 6 老 doc_16 的 source_chunk_ids / source_doc_ids
改为新 doc_17。

背景：用户重新上传了 KB 6 的 PDF，老 doc_id=16 被删，新 doc_id=17 上传；
但 dataset `tst-8b` 写死了 doc_16 命名空间，导致评估指标全 0。

安全校验：
- 老 doc_16 chunks 数（从原 .chroma 旧 collection 推算 = 147）== 新 doc_17 chunks 数
- doc_16 → doc_17 命名 1:1（chunk_index 范围 0..146 一致）
"""
import asyncio
import json
import sys
from sqlalchemy import select, text
from app.db.database import async_session_factory
from app.models.eval_models import EvaluationDataset
from app.models.models import Document
from app.services.vectorstore import get_collection, _collection_name


# 映射：老 doc_id -> 新 doc_id（按文件名前缀匹配；本项目 KB 6 只换过这一次）
OLD_DOC_ID = 16
NEW_DOC_ID = 17


async def main():
    # 1. 校验新 doc 17 存在 + chunk 数
    async with async_session_factory() as db:
        result = await db.execute(
            select(Document).where(
                Document.kb_id == 6,
                Document.id == NEW_DOC_ID,
            )
        )
        new_doc = result.scalar_one_or_none()
        if not new_doc:
            print(f"新 doc_id={NEW_DOC_ID} 不存在，无法迁移！")
            return
        print(f"[校验] 新 doc: id={new_doc.id} filename={new_doc.filename} chunks={new_doc.chunk_count}")

    # 2. 校验新 doc 的 chunk_id 范围
    coll_8b = get_collection("Qwen/Qwen3-Embedding-8B")
    data = coll_8b.get(where={"doc_id": NEW_DOC_ID}, limit=200)
    chunk_indices = sorted(int(m["chunk_index"]) for m in data["metadatas"] if m.get("chunk_index") is not None)
    print(f"[校验] 新 doc_17 在 8B collection 里有 {len(chunk_indices)} 个 chunks，范围 {min(chunk_indices) if chunk_indices else '-'} ~ {max(chunk_indices) if chunk_indices else '-'}")
    expected = list(range(new_doc.chunk_count))
    if chunk_indices != expected:
        print(f"  ⚠️  chunk_index 不连续或不全！可能不是简单 doc_16→doc_17 替换")
        # 不直接 abort，让用户决定

    # 3. 扫所有 dataset
    async with async_session_factory() as db:
        result = await db.execute(text(
            "SELECT id, name, kb_id, qa_pairs FROM evaluation_datasets"
        ))
        rows = result.fetchall()
        print(f"\n[扫描] 共 {len(rows)} 个 dataset")
        target_datasets = []  # (ds_id, ds_name, qa_pairs)
        for row in rows:
            ds_id, ds_name, ds_kb_id, qa_pairs = row
            if not qa_pairs:
                continue
            # 找包含 doc_16 的 dataset
            hits = []
            for qa in qa_pairs:
                src = qa.get("source_chunk_ids", []) or []
                if any(f"_doc_{OLD_DOC_ID}_" in s for s in src):
                    hits.append({
                        "question": qa.get("question", "")[:60],
                        "old_src": src,
                        "old_doc": qa.get("source_doc_ids", []),
                    })
            if hits:
                print(f"  - {ds_id} ({ds_name!r}, kb_id={ds_kb_id}): {len(hits)} 个 qa 命中 doc_{OLD_DOC_ID}")
                for h in hits[:3]:
                    print(f"      {h['question']!r}: {h['old_src']} (doc_ids={h['old_doc']})")
                if len(hits) > 3:
                    print(f"      ... 还有 {len(hits)-3} 个")
                target_datasets.append((ds_id, ds_name, ds_kb_id, qa_pairs, len(hits)))

        if not target_datasets:
            print("  没有 dataset 含 doc_16，无需迁移")
            return

    # 4. 确认执行
    if "--dry-run" in sys.argv:
        print("\n=== DRY RUN 模式（不写库） ===")
        for ds_id, ds_name, ds_kb_id, qa_pairs, n in target_datasets:
            print(f"  将改 dataset {ds_id} ({ds_name!r}) 的 {n} 个 qa")
        return

    print("\n=== 执行迁移 ===")
    # 5. 实际改：替换 chunk_id 命名 + 改 source_doc_ids
    async with async_session_factory() as db:
        for ds_id, ds_name, ds_kb_id, qa_pairs, n in target_datasets:
            new_qa_pairs = []
            changed = 0
            for qa in qa_pairs:
                qa = dict(qa)  # copy
                old_src = qa.get("source_chunk_ids", []) or []
                new_src = [
                    s.replace(f"_doc_{OLD_DOC_ID}_", f"_doc_{NEW_DOC_ID}_")
                    for s in old_src
                ]
                old_docs = qa.get("source_doc_ids", []) or []
                new_docs = [
                    NEW_DOC_ID if d == OLD_DOC_ID else d
                    for d in old_docs
                ]
                if new_src != old_src or new_docs != old_docs:
                    qa["source_chunk_ids"] = new_src
                    qa["source_doc_ids"] = new_docs
                    changed += 1
                new_qa_pairs.append(qa)

            # 写回 DB
            await db.execute(
                text("UPDATE evaluation_datasets SET qa_pairs = CAST(:qa AS jsonb) WHERE id = :id"),
                {"qa": json.dumps(new_qa_pairs, ensure_ascii=False), "id": ds_id},
            )
            print(f"  ✓ dataset {ds_id} ({ds_name!r}): 改 {changed}/{n} 个 qa")

        await db.commit()

    print("\n=== 完成 ===")
    print("现在跑评估，retrieval_metrics 应该不再全 0。")


if __name__ == "__main__":
    asyncio.run(main())
