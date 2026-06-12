"""应用配置模块，从 .env 文件读取所有配置项。"""

import os
from pathlib import Path
from dotenv import load_dotenv

# 加载 .env 文件
_env_path = Path(__file__).resolve().parent.parent / ".env"
if _env_path.exists():
    load_dotenv(_env_path)
else:
    # 尝试加载 .env.example 作为默认值
    _env_example = Path(__file__).resolve().parent.parent / ".env.example"
    if _env_example.exists():
        load_dotenv(_env_example)


class Settings:
    # --- 数据库 ---
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://rag_user:rag_password@localhost:5432/rag_kb",
    )
    DATABASE_URL_SYNC: str = os.getenv(
        "DATABASE_URL_SYNC",
        "postgresql://rag_user:rag_password@localhost:5432/rag_kb",
    )

    # --- ChromaDB ---
    CHROMADB_PATH: str = os.getenv("CHROMADB_PATH", "./data/chromadb")

    # --- Ollama ---
    OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    OLLAMA_LLM_MODEL: str = os.getenv("OLLAMA_LLM_MODEL", "qwen3.5:2b")
    OLLAMA_EMBED_MODEL: str = os.getenv("OLLAMA_EMBED_MODEL", "qwen3-embedding:0.6b")

    # --- JWT ---
    JWT_SECRET_KEY: str = os.getenv("JWT_SECRET_KEY", "change-me-to-a-random-secret")
    JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")
    JWT_EXPIRE_MINUTES: int = int(os.getenv("JWT_EXPIRE_MINUTES", "1440"))

    # --- 分块配置 ---
    CHUNK_TARGET_TOKENS: int = int(os.getenv("CHUNK_TARGET_TOKENS", "300"))
    CHUNK_MAX_TOKENS: int = int(os.getenv("CHUNK_MAX_TOKENS", "512"))
    CHUNK_OVERLAP_SENTENCES: int = int(os.getenv("CHUNK_OVERLAP_SENTENCES", "2"))

    # --- 文件上传 ---
    MAX_UPLOAD_SIZE_BYTES: int = int(os.getenv("MAX_UPLOAD_SIZE_MB", "50")) * 1024 * 1024
    ALLOWED_FILE_TYPES: list[str] = [
        ".pdf", ".docx", ".txt", ".md",
        ".xlsx", ".pptx", ".csv", ".json", ".html",
    ]

    # --- 默认管理员（首次启动自动创建） ---
    ADMIN_USERNAME: str = os.getenv("ADMIN_USERNAME", "admin")
    ADMIN_PASSWORD: str = os.getenv("ADMIN_PASSWORD", "admin123456")
    ADMIN_EMAIL: str = os.getenv("ADMIN_EMAIL", "admin@example.com")

    # --- Mem0 向量记忆 ---
    MEM0_ENABLED: bool = os.getenv("MEM0_ENABLED", "true").lower() == "true"
    MEM0_LLM_MODEL: str = os.getenv("MEM0_LLM_MODEL", "qwen3.5:2b")
    MEM0_EMBED_MODEL: str = os.getenv("MEM0_EMBED_MODEL", "qwen3-embedding:0.6b")

    # --- Memary 知识图谱记忆 ---
    MEMARY_ENABLED: bool = os.getenv("MEMARY_ENABLED", "true").lower() == "true"
    NEO4J_URL: str = os.getenv("NEO4J_URL", "bolt://localhost:7687")
    NEO4J_PW: str = os.getenv("NEO4J_PW", "password")

    # --- Store 会话状态 ---
    STORE_ENABLED: bool = os.getenv("STORE_ENABLED", "true").lower() == "true"

    # --- 应用 ---
    APP_NAME: str = "RAG 知识库系统"
    APP_VERSION: str = "0.1.0"
    API_PREFIX: str = "/api"
    DEBUG: bool = os.getenv("DEBUG", "true").lower() == "true"


settings = Settings()
