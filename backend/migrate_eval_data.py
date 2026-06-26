"""一次性迁移脚本：

1. 给 ChromaDB 现有的 147 个 chunk 的 metadata 加 chunk_id 字段
   （保持原 embedding 不变，避免重新向量化）
2. 把 datasets.qa_pairs[*].source_chunk_ids 从 ['107'] 改为 ['kb_4_doc_14_chunk_107']

使用：
  python migrate_eval_data.py          # 跑迁移
  python migrate_eval_data.py --dry-run  # 预览
"""
import asyncio
import sys
from sqlalchemy import select
from app.db.database import async_session_factory
from app.models.eval_models import EvaluationDataset
from app.services.vectorstore import get_collection


def make_vector_id(kb_id: int, doc_id: int, chunk_idx: int | str) -> str:
    return f"kb_{kb_id}_doc_{doc_id}_chunk_{chunk_idx}"


async def migrate_chromadb_metadata(dry_run: bool):
    """给 ChromaDB collection 现有所有 chunk 加 chunk_id 字段。"""
    col = get_collection()
    total = col.count()
    print(f"[ChromaDB] 总计 {total} chunks")

    # 分批读取（每次 200）
    batch_size = 200
    migrated = 0
    for offset in range(0, total, batch_size):
        data = col.get(
            limit=batch_size,
            offset=offset,
            include=["metadatas", "embeddings", "documents"],
        )
        ids = data["ids"]
        if not ids:
            break

        # 检查是否需要迁移：第一个没 chunk_id 字段就说明全没
        needs_migration = any("chunk_id" not in (m or {}) for m in data["metadatas"])
        if not needs_migration:
            print(f"[ChromaDB] offset={offset} 已有 chunk_id，跳过")
            continue

        new_metadatas = []
        for vid, meta in zip(ids, data["metadatas"]):
            new_meta = dict(meta or {})
            if "chunk_id" not in new_meta:
                new_meta["chunk_id"] = vid  # vector_id 本身就是 kb_X_doc_Y_chunk_Z
            new_metadatas.append(new_meta)

        if dry_run:
            print(f"[ChromaDB] [DRY] offset={offset} 将更新 {len(ids)} 条 metadata")
            migrated += len(ids)
        else:
            # ChromaDB 不支持直接 update metadata；用 add 覆盖（同 id 会替换）
            col.upsert(
                ids=ids,
                documents=data["documents"],
                embeddings=data["embeddings"],
                metadatas=new_metadatas,
            )
            migrated += len(ids)
            print(f"[ChromaDB] offset={offset} 已更新 {len(ids)} 条 metadata")

    print(f"[ChromaDB] 迁移完成: {migrated} 条")


async def migrate_dataset_qa_pairs(dry_run: bool):
    """迁移 datasets.qa_pairs[*].source_chunk_ids 格式。

    旧: ['107']
    新: ['kb_4_doc_14_chunk_107']

    用 raw SQL 避开 ORM mapper 排序问题（users table FK 解析）。
    """
    from sqlalchemy import text

    async with async_session_factory() as db:
        # 读所有 dataset
        result = await db.execute(text(
            "SELECT id, name, kb_id, qa_pairs FROM evaluation_datasets"
        ))
        rows = result.fetchall()
        total_changed = 0
        for row in rows:
            ds_id, ds_name, kb_id, qa_pairs = row
            if not qa_pairs:
                continue
            changed_in_ds = 0
            for qa in qa_pairs:
                src_ids = qa.get("source_chunk_ids", []) or []
                if not src_ids:
                    continue
                # 已迁移过？
                if any("/" in sid or sid.startswith("kb_") for sid in src_ids):
                    continue
                doc_ids = qa.get("source_doc_ids", []) or []
                if not doc_ids:
                    print(f"  ⚠️ dataset {ds_id} qa 缺 source_doc_ids: {qa.get('question', '')[:40]!r}")
                    continue
                doc_id = doc_ids[0]
                new_src = [make_vector_id(kb_id, doc_id, idx) for idx in src_ids]
                if dry_run:
                    print(f"  [DRY] ds={ds_id} {src_ids} → {new_src}")
                else:
                    qa["source_chunk_ids"] = new_src
                changed_in_ds += 1
            if changed_in_ds > 0 and not dry_run:
                # PostgreSQL JSONB 更新
                import json
                await db.execute(
                    text("UPDATE evaluation_datasets SET qa_pairs = CAST(:qa AS jsonb) WHERE id = :id"),
                    {"qa": json.dumps(qa_pairs, ensure_ascii=False), "id": ds_id},
                )
                total_changed += changed_in_ds
                print(f"  dataset {ds_id} ({ds_name!r}): 改了 {changed_in_ds} 个 qa")
        if not dry_run:
            await db.commit()
        print(f"[Datasets] 迁移完成: {total_changed} 个 qa_pairs")


async def main():
    dry_run = "--dry-run" in sys.argv
    if dry_run:
        print("=== DRY RUN 模式 ===")
    else:
        print("=== 执行迁移 ===")

    print("\n[1/2] 迁移 ChromaDB metadata")
    await migrate_chromadb_metadata(dry_run)

    print("\n[2/2] 迁移 datasets.qa_pairs.source_chunk_ids")
    await migrate_dataset_qa_pairs(dry_run)

    print("\n=== 完成 ===")


if __name__ == "__main__":
    asyncio.run(main())
