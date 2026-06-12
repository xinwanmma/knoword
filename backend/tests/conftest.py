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

from app.main import app
from app.db.database import engine, Base, async_session_factory


@pytest.fixture(scope="session")
def event_loop():
    """创建事件循环。"""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session", autouse=True)
async def setup_database():
    """测试前创建数据库表。"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def db_session():
    """每个测试创建独立的数据库会话。"""
    async with async_session_factory() as session:
        yield session
        await session.rollback()


@pytest.fixture
async def client():
    """异步 HTTP 测试客户端。"""
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
