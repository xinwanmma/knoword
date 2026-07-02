"""一次性脚本：给 documents 表加 embedding_model 列 + 回填老文档。

配合 commit cbd8be9（Document 上传时用 KB.embedding_model），
但表里没有这个字段 → commit fe2d0c5 修复。

用法：
  cd backend
  python add_document_embedding_model.py

效果：
1. ALTER TABLE documents ADD COLUMN embedding_model VARCHAR(200) DEFAULT 'qwen3-embedding:0.6b'
2. 老文档的 embedding_model 回填为对应 KB 的 embedding_model
3. 已存在但无 KB 关联的文档（理论上不会有）保持默认 0.6b
"""
from sqlalchemy import text
from app.db.database import async_session_factory, engine
from app.config import settings


async def add_column_and_backfill():
    async with engine.begin() as conn:
        # 1. 加列（PostgreSQL / SQLite 不同语法）
        if settings.DATABASE_URL.startswith("postgresql"):
            await conn.execute(text(
                "ALTER TABLE documents "
                "ADD COLUMN IF NOT EXISTS embedding_model VARCHAR(200) "
                "DEFAULT 'qwen3-embedding:0.6b'"
            ))
        else:  # SQLite
            # SQLite 不支持 IF NOT EXISTS 加列；先查
            result = await conn.execute(text("PRAGMA table_info(documents)"))
            cols = [row[1] for row in result.fetchall()]
            if "embedding_model" not in cols:
                await conn.execute(text(
                    "ALTER TABLE documents "
                    "ADD COLUMN embedding_model VARCHAR(200) "
                    "DEFAULT 'qwen3-embedding:0.6b'"
                ))
                print("已加 documents.embedding_model 列")
            else:
                print("documents.embedding_model 列已存在，跳过")

    # 2. 回填老文档（把 embedding_model 设为 KB.embedding_model）
    async with async_session_factory() as db:
        result = await db.execute(text(
            "UPDATE documents d "
            "SET embedding_model = kb.embedding_model "
            "FROM knowledge_bases kb "
            "WHERE d.kb_id = kb.id "
            "AND (d.embedding_model IS NULL OR d.embedding_model = '')"
        ))
        if result.rowcount:
            print(f"已回填 {result.rowcount} 条老文档的 embedding_model")
        else:
            print("没有需要回填的文档")
        await db.commit()
    print("完成。")


if __name__ == "__main__":
    import asyncio
    asyncio.run(add_column_and_backfill())
