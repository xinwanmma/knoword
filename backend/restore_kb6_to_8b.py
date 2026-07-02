"""一次性脚本：把 KB 6 的 embedding_model 改回 8B。

配合 plan A 修复（siliconflow_provider.py 加 MRL 1024 维）：
- 4B/8B 走 SiliconFlow，强制 dimensions=1024（MRL 压缩）
- 与 ChromaDB 共享 collection 的 1024 维兼容
- KB 6 真的用 8B 跑（MRL 1024 维）

用法：
  cd backend
  python restore_kb6_to_8b.py

效果：
- KB 6.embedding_model: 'qwen3-embedding:0.6b' → 'Qwen/Qwen3-Embedding-8B'
- KB 6 旧 ChromaDB 向量已删（之前脚本删过）
- 旧 Document 标 failed
- 用户需重启后端 + 重新上传 KB 6 文档
"""
from app.db.database import async_session_factory
from app.models.models import KnowledgeBase


async def main():
    async with async_session_factory() as db:
        kb = (await db.execute(
            __import__("sqlalchemy").select(KnowledgeBase).where(KnowledgeBase.id == 6)
        )).scalar_one_or_none()
        if kb is None:
            print("KB 6 不存在，跳过")
            return
        old = kb.embedding_model
        kb.embedding_model = "Qwen/Qwen3-Embedding-8B"
        await db.commit()
        print(f"KB 6 embedding_model: {old!r} → 'Qwen/Qwen3-Embedding-8B'")
        print("下一步：重启后端 + 重新上传 KB 6 文档（会按 8B + MRL 1024 维写入）")


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
