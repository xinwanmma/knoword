"""LangGraph Checkpointer — 持久化 Agent 状态。

使用 MemorySaver（进程内存储），适用于开发和测试。
生产环境应换成 PostgresSaver。
"""

import logging
from langgraph.checkpoint.memory import MemorySaver

logger = logging.getLogger(__name__)

# 全局 checkpointer 实例
_checkpointer = None


def get_checkpointer() -> MemorySaver:
    """获取 MemorySaver checkpointer（单例）。"""
    global _checkpointer
    if _checkpointer is None:
        _checkpointer = MemorySaver()
        logger.info("✅ LangGraph MemorySaver checkpointer 初始化成功")
    return _checkpointer
