"""一次性脚本：把老 collection 'all_documents' 里的数据按 embedding_model 重写到新 collection。

按 embedding_model 物理隔离后：
- 老 collection 'all_documents' 不再使用
- 里面的数据要按 metadata.embedding_model 路由到 kb_emb_{safe_name} 集合
- 0.6b → kb_emb_qwen3_embedding_0_6b
- 8B   → kb_emb_Qwen_Qwen3_Embedding_8B

注意：老数据 metadata 可能有 'embedding_model' 字段（commit cbd8be9 之后上传的），
没有的 fallback 到 0.6b（兼容老历史数据，KB 4 是 0.6b）。

用法：
  cd backend
  python migrate_chromadb_collections.py
"""
import logging
from app.config import settings
from app.services.vectorstore import (
    DEFAULT_EMBEDDING_MODEL,
    LEGACY_COLLECTION_NAME,
    _collection_name,
    _safe_name,
    get_chroma_client,
    get_collection,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main():
    client = get_chroma_client()

    # 1. 找老 collection
    legacy = None
    try:
        legacy = client.get_collection(name=LEGACY_COLLECTION_NAME)
    except Exception as e:
        logger.info(f"老 collection '{LEGACY_COLLECTION_NAME}' 不存在或无法读取：{e}")
        return

    total = legacy.count()
    if total == 0:
        logger.info(f"老 collection '{LEGACY_COLLECTION_NAME}' 已是空，无需迁移")
        return

    logger.info(f"老 collection '{LEGACY_COLLECTION_NAME}' 有 {total} 条向量，开始迁移...")

    # 2. 读出所有数据（分批避免 OOM）
    batch_size = 1000
    offset = 0
    migrated = 0
    skipped = 0
    by_embedding: dict[str, int] = {}

    while offset < total:
        data = legacy.get(
            limit=batch_size,
            offset=offset,
            include=["documents", "metadatas", "embeddings"],
        )
        ids = data["ids"]
        docs = data["documents"]
        metas = data["metadatas"]
        embs = data["embeddings"]

        if not ids:
            break

        # 3. 按 embedding_model 分组
        groups: dict[str, dict] = {}
        for vid, doc, meta, emb in zip(ids, docs, metas, embs):
            em = (meta or {}).get("embedding_model") or DEFAULT_EMBEDDING_MODEL
            if em not in groups:
                groups[em] = {"ids": [], "documents": [], "metadatas": [], "embeddings": []}
            groups[em]["ids"].append(vid)
            groups[em]["documents"].append(doc)
            groups[em]["metadatas"].append(meta or {})
            groups[em]["embeddings"].append(emb)

        # 4. 写入新 collection
        for em, g in groups.items():
            target = get_collection(em)
            # ChromaDB 单次批量上限，分批
            sub_batch = 100
            for i in range(0, len(g["ids"]), sub_batch):
                end = min(i + sub_batch, len(g["ids"]))
                target.add(
                    ids=g["ids"][i:end],
                    documents=g["documents"][i:end],
                    embeddings=g["embeddings"][i:end],
                    metadatas=g["metadatas"][i:end],
                )
            count = len(g["ids"])
            by_embedding[em] = by_embedding.get(em, 0) + count
            logger.info(f"  迁移 {count} 条 → {_collection_name(em)}")
            migrated += count

        offset += len(ids)
        logger.info(f"  进度: {offset}/{total}")

    # 5. 总结
    logger.info(f"\n迁移完成: 总 {migrated} 条")
    for em, cnt in by_embedding.items():
        logger.info(f"  {em}: {cnt} 条 → {_collection_name(em)}")

    # 6. 删老 collection（不删数据，只删 collection 元信息）
    logger.info(f"\n删除老 collection '{LEGACY_COLLECTION_NAME}'...")
    client.delete_collection(name=LEGACY_COLLECTION_NAME)
    logger.info("完成。")


if __name__ == "__main__":
    main()
