"""SQLAlchemy 数据模型。"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Column, Integer, String, Text, Boolean, DateTime, ForeignKey, ARRAY, JSON
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship

from app.db.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username = Column(String(100), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    is_admin = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    knowledge_bases = relationship("KnowledgeBase", back_populates="owner")
    conversations = relationship("Conversation", back_populates="user")


class Category(Base):
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), unique=True, nullable=False)

    knowledge_bases = relationship("KnowledgeBase", back_populates="category")


class KnowledgeBase(Base):
    __tablename__ = "knowledge_bases"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=True)
    owner_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    is_global = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    owner = relationship("User", back_populates="knowledge_bases")
    category = relationship("Category", back_populates="knowledge_bases")
    documents = relationship("Document", back_populates="knowledge_base", cascade="all, delete-orphan")


class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    kb_id = Column(Integer, ForeignKey("knowledge_bases.id"), nullable=False)
    filename = Column(String(500), nullable=False)
    file_path = Column(String(1000), nullable=False)
    file_type = Column(String(20), nullable=False)
    chunk_count = Column(Integer, default=0)
    status = Column(String(20), default="processing")  # processing / ready / failed
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    knowledge_base = relationship("KnowledgeBase", back_populates="documents")


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    title = Column(String(200), default="新对话")
    kb_ids = Column(ARRAY(Integer), default=list)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="conversations")
    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan")


class Message(Base):
    __tablename__ = "messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id = Column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    role = Column(String(20), nullable=False)  # user / assistant / system
    content = Column(Text, nullable=False)
    sources = Column(JSONB, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    conversation = relationship("Conversation", back_populates="messages")
