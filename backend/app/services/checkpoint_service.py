"""LangGraph Checkpointer — 持久化 Agent 状态，支持多轮对话上下文。"""

import logging
from langgraph.checkpoint.memory import MemorySaver

logger = logging.getLogger(__name__)

# 全局 checkpointer 实例
_checkpointer = None


def get_checkpointer() -> MemorySaver:
    """获取 MemorySaver checkpointer（单例）。

    MemorySaver 是 LangGraph 内置的内存 checkpoint 存储。
    用于持久化 Agent 状态到内存，支持断点续传和状态回放。

    注意：MemorySaver 是进程内存储，重启后丢失。
    生产环境应换成 PostgresSaver 或 SqliteSaver。
    """
    global _checkpointer
    if _checkpointer is None:
        _checkpointer = MemorySaver()
        logger.info("✅ LangGraph MemorySaver checkpointer 初始化成功")
    return _checkpointer


async def save_checkpoint(thread_id: str, state: dict):
    """保存状态到 checkpoint。"""
    checkpointer = get_checkpointer()
    config = {"configurable": {"thread_id": thread_id}}
    try:
        await checkpointer.awrite(state, config)
        logger.debug(f"Checkpoint saved: thread={thread_id}")
    except Exception as e:
        logger.error(f"Checkpoint save failed: {e}")


async def load_checkpoint(thread_id: str) -> dict | None:
    """从 checkpoint 加载状态。"""
    checkpointer = get_checkpointer()
    config = {"configurable": {"thread_id": thread_id}}
    try:
        snapshot = await checkpointer.aget(config)
        if snapshot:
            return snapshot.get("values", {})
        return None
    except Exception as e:
        logger.error(f"Checkpoint load failed: {e}")
        return None


async def list_checkpoints(thread_id: str) -> list[dict]:
    """列出某个 thread 的所有 checkpoint。"""
    checkpointer = get_checkpointer()
    config = {"configurable": {"thread_id": thread_id}}
    try:
        checkpoints = []
        async for cp in checkpointer.alist(config):
            checkpoints.append({
                "thread_id": cp.config.get("configurable", {}).get("thread_id"),
                "checkpoint_id": cp.config.get("configurable", {}).get("checkpoint_id"),
            })
        return checkpoints
    except Exception as e:
        logger.error(f"List checkpoints failed: {e}")
        return []
