"""Pydantic 数据模式。"""

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field, field_validator


# ==================== 用户 ====================

class UserRegister(BaseModel):
    username: str = Field(..., min_length=2, max_length=100)
    email: EmailStr
    password: str = Field(..., min_length=6, max_length=128)


class UserLogin(BaseModel):
    username: str
    password: str


class UserOut(BaseModel):
    id: uuid.UUID
    username: str
    email: str
    is_admin: bool
    created_at: datetime

    class Config:
        from_attributes = True


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


# ==================== 知识库 ====================

class KnowledgeBaseCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    # 策略配置（Phase 3）
    embedding_model: str = "qwen3-embedding:0.6b"
    chunking_strategy: str = "recursive"
    chunk_size: int = 500
    chunk_overlap: int = 50
    retrieval_strategy: str = "vector"
    rerank_model: str = "BAAI/bge-reranker-base"
    rerank_top_n: int = 20


class KnowledgeBaseUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = None
    # 策略更新
    embedding_model: Optional[str] = None
    chunking_strategy: Optional[str] = None
    chunk_size: Optional[int] = None
    chunk_overlap: Optional[int] = None
    retrieval_strategy: Optional[str] = None
    rerank_model: Optional[str] = None
    rerank_top_n: Optional[int] = None


class KnowledgeBaseOut(BaseModel):
    id: int
    name: str
    description: Optional[str]
    owner_id: uuid.UUID
    created_at: datetime
    document_count: int = 0
    # 策略
    embedding_model: str = "qwen3-embedding:0.6b"
    chunking_strategy: str = "recursive"
    chunk_size: int = 500
    chunk_overlap: int = 50
    retrieval_strategy: str = "vector"
    rerank_model: str = "BAAI/bge-reranker-base"
    rerank_top_n: int = 20

    class Config:
        from_attributes = True


# ==================== 文档 ====================

class DocumentOut(BaseModel):
    id: int
    kb_id: int
    filename: str
    file_type: str
    chunk_count: int
    status: str
    error: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class DocumentStatusOut(BaseModel):
    id: int
    status: str
    chunk_count: int
    error: Optional[str]


# ==================== 对话 ====================

class ChatRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=5000)
    kb_ids: list[int] = []
    search_all: bool = False
    conversation_id: Optional[str] = None

    @field_validator('query')
    @classmethod
    def sanitize_query(cls, v: str) -> str:
        """去除控制字符，保留换行。"""
        return ''.join(c for c in v if c.isprintable() or c in '\n\r\t').strip()


class SourceOut(BaseModel):
    doc_id: int
    filename: str
    page: Optional[int]
    content: str
    score: float


class ChatResponse(BaseModel):
    conversation_id: str
    answer: str
    sources: list[SourceOut]


class ConversationOut(BaseModel):
    id: uuid.UUID
    title: str
    kb_ids: list[int]
    created_at: datetime

    class Config:
        from_attributes = True


class MessageOut(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    sources: Optional[list[dict]] = None
    created_at: datetime

    class Config:
        from_attributes = True


# ==================== 通用 ====================

class HealthCheck(BaseModel):
    status: str
    services: dict[str, bool]
