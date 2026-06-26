"""数据库连接与会话管理。"""

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

# 根据 URL 自动适配 engine 配置：
#   - PostgreSQL（生产）：用连接池参数
#   - SQLite（测试 conftest.py）：用最简配置，aiosqlite 不接受 pool_size
_is_sqlite = settings.DATABASE_URL.startswith("sqlite")

if _is_sqlite:
    engine = create_async_engine(
        settings.DATABASE_URL,
        echo=settings.DEBUG,
    )
else:
    engine = create_async_engine(
        settings.DATABASE_URL,
        echo=settings.DEBUG,
        pool_size=20,
        max_overflow=10,
        pool_recycle=1800,
        pool_pre_ping=True,
        pool_timeout=30,
    )

# 创建异步会话工厂
async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。"""
    pass


async def get_db() -> AsyncSession:
    """FastAPI 依赖注入：获取数据库会话。"""
    async with async_session_factory() as session:
        try:
            yield session
        except Exception:
            if session.is_active:
                await session.rollback()
            raise
        finally:
            await session.close()


async def init_db():
    """创建所有表（仅开发环境使用，生产环境用 Alembic）。"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
