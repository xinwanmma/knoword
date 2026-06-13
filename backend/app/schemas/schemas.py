"""Pydantic 数据模式。"""

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field


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
    category_id: Optional[int] = None
    is_global: bool = False


class KnowledgeBaseUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = None
    category_id: Optional[int] = None


class KnowledgeBaseOut(BaseModel):
    id: int
    name: str
    description: Optional[str]
    category_id: Optional[int]
    category_name: Optional[str] = None
    owner_id: Optional[uuid.UUID]
    is_global: bool
    created_at: datetime
    document_count: int = 0

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


# ==================== 分类 ====================

class CategoryCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)


class CategoryOut(BaseModel):
    id: int
    name: str

    class Config:
        from_attributes = True


# ==================== 对话 ====================

class ChatRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=5000)
    kb_ids: list[int] = []
    search_all: bool = False
    conversation_id: Optional[str] = None


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
    agent: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


# ==================== 通用 ====================

class HealthCheck(BaseModel):
    status: str
    services: dict[str, bool]
