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


async def _create_default_admin():
    """首次启动时自动创建默认管理员账号。"""
    from sqlalchemy import select
    from app.db.database import async_session_factory
    from app.models.models import User
    from app.core.security import hash_password

    if not settings.ADMIN_PASSWORD:
        logger.warning("ADMIN_PASSWORD 未设置，跳过默认管理员创建")
        return

    async with async_session_factory() as db:
        result = await db.execute(select(User).where(User.is_admin == True))
        if result.scalar_one_or_none() is not None:
            logger.info("管理员账号已存在，跳过初始化")
            return

        result = await db.execute(
            select(User).where(User.username == settings.ADMIN_USERNAME)
        )
        if result.scalar_one_or_none() is not None:
            logger.warning(
                f"用户名 '{settings.ADMIN_USERNAME}' 已被占用，"
                f"请手动将该用户设为管理员或修改 ADMIN_USERNAME"
            )
            return

        admin = User(
            username=settings.ADMIN_USERNAME,
            email=settings.ADMIN_EMAIL,
            hashed_password=hash_password(settings.ADMIN_PASSWORD),
            is_admin=True,
        )
        db.add(admin)
        await db.commit()
        logger.info(
            f"✅ 默认管理员已创建: 用户名={settings.ADMIN_USERNAME}"
        )
        logger.warning("⚠️  请在生产环境中修改默认管理员密码！")


async def _init_chromadb():
    """启动时初始化 ChromaDB collection，避免首次请求卡顿。"""
    try:
        from app.services.vectorstore import get_collection
        get_collection()
        logger.info("✅ ChromaDB collection 初始化完成")
    except Exception as e:
        logger.error(f"❌ ChromaDB 初始化失败: {e}", exc_info=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时初始化数据库，关闭时清理资源。"""
    logger.info("🚀 正在启动 RAG 知识库系统...")
    await init_db()
    await _create_default_admin()
    await _init_chromadb()
    logger.info("✅ 数据库初始化完成")

    if settings.JWT_SECRET_KEY.startswith("change-me"):
        logger.warning("⚠️  JWT_SECRET_KEY 使用默认值！请在生产环境中修改！")
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
    allow_origins=settings.CORS_ORIGINS.split(","),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
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
from app.api.knowledge_base import router as kb_router
from app.api.documents import router as doc_router
from app.api.chat import router as chat_router
from app.api.health import router as health_router
from app.api.admin import router as admin_router
from app.api.eval import router as eval_router
# 导入所有模型以触发 SQLAlchemy create_all
from app.models import models  # noqa: F401
from app.models.eval_models import (  # noqa: F401
    EvaluationDataset, EvaluationRun, EvaluationResult,
)

API_PREFIX = settings.API_PREFIX

app.include_router(auth_router, prefix=API_PREFIX)
app.include_router(kb_router, prefix=API_PREFIX)
app.include_router(doc_router, prefix=API_PREFIX)
app.include_router(chat_router, prefix=API_PREFIX)
app.include_router(health_router, prefix=API_PREFIX)
app.include_router(admin_router, prefix=API_PREFIX)
app.include_router(eval_router, prefix=API_PREFIX)


@app.get("/")
async def root():
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "docs": "/docs",
    }
