"""一次性脚本：把 KB 6 的 embedding_model 改成 0.6b + 删旧 ChromaDB 向量。

根因：KB 6 字段声明 8B（4096 维），但上传时 Document 默认 0.6b（1024 维）→ collection 已锁死 1024 维。
处理：把 KB 6 字段也改为 0.6b，与 collection 一致；删旧向量让用户重新上传。

用法：
  cd backend
  python fix_kb6_embedding.py
"""
from app.config import settings
from app.db.database import async_session_factory
from app.models.models import Document, KnowledgeBase
from app.services.vectorstore import delete_by_kb_id


async def main():
    async with async_session_factory() as db:
        kb = (await db.execute(
            __import__("sqlalchemy").select(KnowledgeBase).where(KnowledgeBase.id == 6)
        )).scalar_one_or_none()
        if kb is None:
            print("KB 6 不存在，跳过")
            return
        old = kb.embedding_model
        kb.embedding_model = "qwen3-embedding:0.6b"
        await db.commit()
        print(f"KB 6 embedding_model: {old!r} → 'qwen3-embedding:0.6b'")

    # 删 ChromaDB 旧向量（让用户重新上传）
    delete_by_kb_id(6)
    print("已删 KB 6 旧 ChromaDB 向量")

    # 顺手把 Document 表里 KB 6 的旧记录标 failed（可选，用户重新上传即可覆盖）
    async with async_session_factory() as db:
        from sqlalchemy import update
        await db.execute(
            update(Document).where(Document.kb_id == 6).values(status="failed", error="embedding model 变更，需重新上传")
        )
        await db.commit()
    print("KB 6 旧 Document 记录已标 failed（请重新上传文档）")


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
