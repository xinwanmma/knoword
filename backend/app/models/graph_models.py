"""知识图谱数据模型 — 用 PostgreSQL 存储实体和关系，NetworkX 做图遍历。"""

from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, DateTime, Text, Index, Float,
)
from sqlalchemy.dialects.postgresql import JSONB
from app.db.database import Base


class GraphEntity(Base):
    """图谱实体表。"""
    __tablename__ = "graph_entities"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(36), nullable=False, index=True)
    name = Column(String(200), nullable=False)
    entity_type = Column(String(50), default="UNKNOWN")
    mention_count = Column(Integer, default=1)
    last_mentioned = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_entity_user_name", "user_id", "name", unique=True),
    )


class GraphRelation(Base):
    """图谱关系表。"""
    __tablename__ = "graph_relations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(36), nullable=False, index=True)
    source_name = Column(String(200), nullable=False)
    relation_type = Column(String(100), nullable=False)
    target_name = Column(String(200), nullable=False)
    last_updated = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_relation_user", "user_id", "source_name", "target_name"),
    )
