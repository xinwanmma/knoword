"""pytest 共享 fixtures。"""

import os
import sys

# 设置测试环境变量（在导入 app 之前）
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test.db"
os.environ["DATABASE_URL_SYNC"] = "sqlite:///./test.db"
os.environ["CHROMADB_PATH"] = "./test_chromadb"
os.environ["MEM0_ENABLED"] = "false"
os.environ["MEMARY_ENABLED"] = "false"
os.environ["STORE_ENABLED"] = "true"
os.environ["ADMIN_USERNAME"] = "testadmin"
os.environ["ADMIN_PASSWORD"] = "testpass123"
os.environ["ADMIN_EMAIL"] = "test@test.com"
os.environ["DEBUG"] = "false"

import pytest
import asyncio
from httpx import AsyncClient, ASGITransport

from sqlalchemy import event
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.db.database import Base, async_session_factory
from app.config import settings

# 创建测试专用引擎（SQLite）
test_engine = create_async_engine(
    "sqlite+aiosqlite:///./test.db",
    echo=False,
)

# SQLite 类型适配：让 PostgreSQL 特有类型在 SQLite 上工作
@event.listens_for(test_engine.sync_engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    """SQLite 启用外键支持。"""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session", autouse=True)
async def setup_database():
    """测试前创建数据库表 + 管理员用户。"""
    # SQLite 不支持 PostgreSQL 特有类型（UUID、JSONB、ARRAY），
    # 需要 monkey-patch 为通用类型
    from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSONB as PG_JSONB, ARRAY as PG_ARRAY
    from sqlalchemy import String, JSON, Text

    # 保存原始类型
    _orig_uuid = PG_UUID
    _orig_jsonb = PG_JSONB
    _orig_array = PG_ARRAY

    # 临时替换为 SQLite 兼容类型（只影响 create_all 的 DDL）
    PG_UUID.__visit__ = lambda self, dialect: String(36)
    PG_JSONB.__visit__ = lambda self, dialect: JSON()
    PG_ARRAY.__visit__ = lambda self, dialect: Text()

    try:
        async with test_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    finally:
        # 恢复原始类型
        PG_UUID.__visit__ = _orig_uuid.__visit__
        PG_JSONB.__visit__ = _orig_jsonb.__visit__
        PG_ARRAY.__visit__ = _orig_array.__visit__

    # 创建管理员用户
    TestSession = async_sessionmaker(test_engine, expire_on_commit=False)
    from app.models.models import User
    from app.core.security import hash_password

    async with TestSession() as session:
        from sqlalchemy import select
        result = await session.execute(select(User).where(User.username == "testadmin"))
        if result.scalar_one_or_none() is None:
            admin = User(
                username="testadmin",
                email="test@test.com",
                hashed_password=hash_password("testpass123"),
                is_admin=True,
            )
            session.add(admin)
            await session.commit()

    yield

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def db_session():
    """每个测试使用独立的数据库会话。"""
    TestSession = async_sessionmaker(test_engine, expire_on_commit=False)
    async with TestSession() as session:
        yield session
        await session.rollback()


@pytest.fixture
async def client():
    """异步 HTTP 测试客户端（不触发 lifespan）。"""
    # 导入 app 但不使用 lifespan（手动管理数据库）
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
async def auth_client(client):
    """已登录的测试客户端。"""
    # 注册用户
    await client.post("/api/auth/register", json={
        "username": "testuser",
        "email": "test@example.com",
        "password": "testpass123",
    })
    # 登录获取 token
    resp = await client.post("/api/auth/login", json={
        "username": "testuser",
        "password": "testpass123",
    })
    token = resp.json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    return client
