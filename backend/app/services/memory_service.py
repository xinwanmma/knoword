"""Mem0 记忆服务 — 向量语义记忆，从对话中自动提取用户事实/偏好。

使用自托管模式，用 ChromaDB 作为 vector store（独立 collection）。
"""

import logging
from datetime import datetime

from app.config import settings

logger = logging.getLogger(__name__)

# Mem0 实例（延迟初始化）
_mem0_instance = None


def _get_mem0():
    """获取或初始化 Mem0 实例。"""
    global _mem0_instance
    if _mem0_instance is not None:
        return _mem0_instance

    try:
        from mem0 import Memory

        config = {
            "llm": {
                "provider": "ollama",
                "config": {
                    "model": settings.MEM0_LLM_MODEL,
                    "ollama_base_url": settings.OLLAMA_BASE_URL,
                },
            },
            "embedder": {
                "provider": "ollama",
                "config": {
                    "model": settings.MEM0_EMBED_MODEL,
                    "ollama_base_url": settings.OLLAMA_BASE_URL,
                },
            },
            "vector_store": {
                "provider": "chroma",
                "config": {
                    "collection_name": "mem0_memories",
                    "path": settings.CHROMADB_PATH + "/mem0",
                },
            },
            "version": "v2.0",
        }

        _mem0_instance = Memory.from_config(config)
        logger.info("✅ Mem0 记忆服务初始化成功")
        return _mem0_instance

    except Exception as e:
        logger.error(f"❌ Mem0 初始化失败: {e}")
        return None


async def search_memories(user_id: str, query: str, top_k: int = 5) -> list[dict]:
    """搜索用户相关的事实记忆。

    Args:
        user_id: 用户 ID
        query: 搜索查询
        top_k: 返回结果数

    Returns:
        记忆列表 [{"memory": "...", "score": 0.9, "id": "..."}, ...]
    """
    mem0 = _get_mem0()
    if mem0 is None:
        return []

    try:
        results = mem0.search(query, user_id=user_id, top_k=top_k)
        memories = results.get("results", [])
        logger.info(f"Mem0 搜索 user={user_id}, query='{query[:30]}...', 命中 {len(memories)} 条")
        return memories
    except Exception as e:
        logger.error(f"Mem0 搜索失败: {e}")
        return []


async def add_memory(user_id: str, messages: list[dict]) -> list[dict]:
    """从对话中提取并存储记忆。

    Args:
        user_id: 用户 ID
        messages: [{"role": "user"/"assistant", "content": "..."}, ...]

    Returns:
        新创建的记忆列表
    """
    mem0 = _get_mem0()
    if mem0 is None:
        return []

    try:
        result = mem0.add(messages, user_id=user_id)
        new_memories = result.get("results", [])
        if new_memories:
            logger.info(f"Mem0 新增 {len(new_memories)} 条记忆 user={user_id}")
        return new_memories
    except Exception as e:
        logger.error(f"Mem0 添加记忆失败: {e}")
        return []


async def get_all_memories(user_id: str) -> list[dict]:
    """获取用户所有记忆。"""
    mem0 = _get_mem0()
    if mem0 is None:
        return []

    try:
        results = mem0.get_all(user_id=user_id)
        return results.get("results", [])
    except Exception as e:
        logger.error(f"Mem0 获取记忆列表失败: {e}")
        return []


async def delete_memory(memory_id: str) -> bool:
    """删除单条记忆。"""
    mem0 = _get_mem0()
    if mem0 is None:
        return False

    try:
        mem0.delete(memory_id)
        return True
    except Exception as e:
        logger.error(f"Mem0 删除记忆失败: {e}")
        return False


async def delete_all_memories(user_id: str) -> bool:
    """清空用户所有记忆。"""
    mem0 = _get_mem0()
    if mem0 is None:
        return False

    try:
        mem0.delete_all(user_id=user_id)
        logger.info(f"Mem0 已清空 user={user_id} 的所有记忆")
        return True
    except Exception as e:
        logger.error(f"Mem0 清空记忆失败: {e}")
        return False


async def get_memory_stats(user_id: str) -> dict:
    """获取用户记忆统计。"""
    memories = await get_all_memories(user_id)
    return {
        "total": len(memories),
        "memories": memories[:10],  # 返回最近 10 条
    }
