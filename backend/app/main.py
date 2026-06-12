"""FastAPI 主应用入口。"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.db.database import init_db
from app.services.ollama_service import close_client
from app.middleware.logging import RequestLoggingMiddleware

# 配置日志
logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# 配置 LangSmith（可选，需注册 https://smith.langchain.com）
if settings.LANGCHAIN_TRACING_V2 and settings.LANGCHAIN_API_KEY:
    import os as _os
    _os.environ["LANGCHAIN_TRACING_V2"] = "true"
    _os.environ["LANGCHAIN_API_KEY"] = settings.LANGCHAIN_API_KEY
    _os.environ["LANGCHAIN_PROJECT"] = settings.LANGCHAIN_PROJECT
    _os.environ["LANGCHAIN_ENDPOINT"] = settings.LANGCHAIN_ENDPOINT
    logger.info(f"✅ LangSmith 追踪已启用: project={settings.LANGCHAIN_PROJECT}")


async def _create_default_admin():
    """首次启动时自动创建默认管理员账号。"""
    from sqlalchemy import select
    from app.db.database import async_session_factory
    from app.models.models import User
    from app.core.security import hash_password

    async with async_session_factory() as db:
        # 检查是否已有管理员
        result = await db.execute(select(User).where(User.is_admin == True))
        if result.scalar_one_or_none() is not None:
            logger.info("管理员账号已存在，跳过初始化")
            return

        # 检查用户名是否被占用
        result = await db.execute(
            select(User).where(User.username == settings.ADMIN_USERNAME)
        )
        if result.scalar_one_or_none() is not None:
            logger.warning(
                f"用户名 '{settings.ADMIN_USERNAME}' 已被占用，"
                f"请手动将该用户设为管理员或修改 ADMIN_USERNAME"
            )
            return

        # 创建管理员
        admin = User(
            username=settings.ADMIN_USERNAME,
            email=settings.ADMIN_EMAIL,
            hashed_password=hash_password(settings.ADMIN_PASSWORD),
            is_admin=True,
        )
        db.add(admin)
        await db.commit()
        logger.info(
            f"✅ 默认管理员已创建: "
            f"用户名={settings.ADMIN_USERNAME}, "
            f"密码={settings.ADMIN_PASSWORD}"
        )
        logger.info(
            "⚠️  请在生产环境中修改默认管理员密码！"
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时初始化数据库，关闭时清理资源。"""
    logger.info("🚀 正在启动 RAG 知识库系统...")
    await init_db()
    await _create_default_admin()
    logger.info("✅ 数据库初始化完成")
    yield
    logger.info("🔄 正在关闭...")
    await close_client()
    logger.info("✅ 已关闭")


# 创建 FastAPI 应用
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 请求日志中间件
app.add_middleware(RequestLoggingMiddleware)


# 全局异常处理
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"未处理的异常: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "服务器内部错误，请稍后重试"},
    )


# 注册路由
from app.api.auth import router as auth_router
from app.api.knowledge_base import router as kb_router, category_router
from app.api.documents import router as doc_router
from app.api.chat import router as chat_router
from app.api.health import router as health_router
from app.api.store import router as store_router
from app.api.memory import router as memory_router
from app.api.graph_memory import router as graph_router
from app.api.chunk_config import router as chunk_router

API_PREFIX = settings.API_PREFIX

app.include_router(auth_router, prefix=API_PREFIX)
app.include_router(kb_router, prefix=API_PREFIX)
app.include_router(category_router, prefix=API_PREFIX)
app.include_router(doc_router, prefix=API_PREFIX)
app.include_router(chat_router, prefix=API_PREFIX)
app.include_router(health_router, prefix=API_PREFIX)
app.include_router(store_router, prefix=API_PREFIX)
app.include_router(memory_router, prefix=API_PREFIX)
app.include_router(graph_router, prefix=API_PREFIX)
app.include_router(chunk_router, prefix=API_PREFIX)


@app.get("/")
async def root():
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "docs": "/docs",
    }
