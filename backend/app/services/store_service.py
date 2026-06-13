"""Store 记忆系统 — 基于 PostgreSQL JSONB 的跨会话持久状态存储。

每个用户拥有独立的 namespace，存储偏好、进度、上下文快照等。
"""

import json
import logging
from datetime import datetime, timezone

from sqlalchemy import Column, Integer, String, DateTime, Text, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete

from app.db.database import Base

logger = logging.getLogger(__name__)


# ==================== 数据模型 ====================

class UserStore(Base):
    """用户 Store 键值对存储表。"""
    __tablename__ = "user_store"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(36), nullable=False, index=True)
    namespace = Column(String(100), nullable=False, default="default")
    key = Column(String(200), nullable=False)
    value = Column(JSONB, nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        Index("idx_store_user_ns_key", "user_id", "namespace", "key", unique=True),
    )


# ==================== Store 操作 ====================

async def store_put(
    db: AsyncSession,
    user_id: str,
    key: str,
    value: dict | list | str | int | float,
    namespace: str = "default",
):
    """存储或更新一个键值对。"""
    result = await db.execute(
        select(UserStore).where(
            UserStore.user_id == user_id,
            UserStore.namespace == namespace,
            UserStore.key == key,
        )
    )
    existing = result.scalar_one_or_none()

    if existing:
        existing.value = value if isinstance(value, (dict, list)) else {"data": value}
        existing.updated_at = datetime.now(timezone.utc)
    else:
        entry = UserStore(
            user_id=user_id,
            namespace=namespace,
            key=key,
            value=value if isinstance(value, (dict, list)) else {"data": value},
        )
        db.add(entry)

    await db.commit()


async def store_get(
    db: AsyncSession,
    user_id: str,
    key: str,
    namespace: str = "default",
) -> dict | None:
    """获取一个键值对。"""
    result = await db.execute(
        select(UserStore).where(
            UserStore.user_id == user_id,
            UserStore.namespace == namespace,
            UserStore.key == key,
        )
    )
    entry = result.scalar_one_or_none()
    if entry is None:
        return None
    return {"key": entry.key, "value": entry.value, "updated_at": entry.updated_at.isoformat()}


async def store_get_all(
    db: AsyncSession,
    user_id: str,
    namespace: str | None = None,
) -> list[dict]:
    """获取用户所有 Store 数据。"""
    query = select(UserStore).where(UserStore.user_id == user_id)
    if namespace:
        query = query.where(UserStore.namespace == namespace)
    query = query.order_by(UserStore.updated_at.desc())

    result = await db.execute(query)
    entries = result.scalars().all()
    return [
        {
            "key": e.key,
            "namespace": e.namespace,
            "value": e.value,
            "updated_at": e.updated_at.isoformat(),
        }
        for e in entries
    ]


async def store_delete(
    db: AsyncSession,
    user_id: str,
    key: str,
    namespace: str = "default",
) -> bool:
    """删除一个键值对。"""
    result = await db.execute(
        select(UserStore).where(
            UserStore.user_id == user_id,
            UserStore.namespace == namespace,
            UserStore.key == key,
        )
    )
    entry = result.scalar_one_or_none()
    if entry is None:
        return False

    await db.delete(entry)
    await db.commit()
    return True


async def store_delete_all(
    db: AsyncSession,
    user_id: str,
    namespace: str | None = None,
) -> int:
    """清空用户所有 Store 数据，返回删除条数。"""
    query = delete(UserStore).where(UserStore.user_id == user_id)
    if namespace:
        query = query.where(UserStore.namespace == namespace)

    result = await db.execute(query)
    await db.commit()
    return result.rowcount
