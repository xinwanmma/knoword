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

    # --- Ollama（仅用于 embedding） ---
    OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    OLLAMA_EMBED_MODEL: str = os.getenv("OLLAMA_EMBED_MODEL", "qwen3-embedding:0.6b")

    # --- MiMo LLM（云端 API，OpenAI 兼容） ---
    MIMO_BASE_URL: str = os.getenv("MIMO_BASE_URL", "https://api.xiaomimimo.com/v1")
    MIMO_API_KEY: str = os.getenv("MIMO_API_KEY", "")
    MIMO_MODEL: str = os.getenv("MIMO_MODEL", "mimo-v2.5-pro")
    # [已废弃] MIMO_LITE_MODEL 不再作为评估默认 judge LLM，
    # LLM 评估指标默认改用 MIMO_MODEL（mimo-v2.5-pro）。
    # 保留字段仅为向后兼容（可被 EvalRunCreate.llm_metric_model 显式覆盖）。
    MIMO_LITE_MODEL: str = os.getenv("MIMO_LITE_MODEL", "mimo-v2.5")
    MIMO_LLM_TEMPERATURE: float = float(os.getenv("MIMO_LLM_TEMPERATURE", "0.7"))

    # --- DeepSeek LLM（云端 API，OpenAI 兼容） ---
    DEEPSEEK_BASE_URL: str = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
    DEEPSEEK_API_KEY: str = os.getenv("DEEPSEEK_API_KEY", "")
    DEEPSEEK_MODEL: str = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")

    # --- GLM 智谱 LLM（云端 API，OpenAI 兼容） ---
    GLM_BASE_URL: str = os.getenv("GLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4")
    GLM_API_KEY: str = os.getenv("GLM_API_KEY", "")
    GLM_MODEL: str = os.getenv("GLM_MODEL", "GLM-4.5-flash")

    # --- Embedding: HuggingFace 本地（统一缓存目录） ---
    HF_EMBED_MODEL: str = os.getenv("HF_EMBED_MODEL", "shibing624/text2vec-base-chinese")
    HF_CACHE_DIR: str = os.getenv("HF_CACHE_DIR", "C:\\Users\\13596\\.cache\\huggingface\\hub")
    HF_OFFLINE: bool = os.getenv("HF_OFFLINE", "1") == "1"

    # --- Embedding: SiliconFlow ---
    SILICONFLOW_BASE_URL: str = os.getenv("SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1")
    SILICONFLOW_API_KEY: str = os.getenv("SILICONFLOW_API_KEY", "")
    SILICONFLOW_EMBED_8B: str = os.getenv("SILICONFLOW_EMBED_8B", "Qwen/Qwen3-Embedding-8B")
    SILICONFLOW_EMBED_4B: str = os.getenv("SILICONFLOW_EMBED_4B", "Qwen/Qwen3-Embedding-4B")

    # --- Rerank: HuggingFace 本地（共享 HF 缓存目录） ---
    HF_RERANK_MODEL: str = os.getenv("HF_RERANK_MODEL", "BAAI/bge-reranker-base")

    # --- Rerank: SiliconFlow ---
    SILICONFLOW_RERANK_MODEL: str = os.getenv("SILICONFLOW_RERANK_MODEL", "Qwen/Qwen3-Reranker-4B")
    SILICONFLOW_RERANK_URL: str = os.getenv(
        "SILICONFLOW_RERANK_URL", "https://api.siliconflow.cn/v1/rerank"
    )

    # --- 评估 ---
    DEFAULT_EVAL_QA_COUNT: int = int(os.getenv("DEFAULT_EVAL_QA_COUNT", "20"))
    DEFAULT_EVAL_CONCURRENCY: int = int(os.getenv("DEFAULT_EVAL_CONCURRENCY", "4"))
    EVAL_REPORT_DIR: str = os.getenv("EVAL_REPORT_DIR", "./reports")

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

    # --- 应用 ---
    APP_NAME: str = "RAG 知识库系统"
    APP_VERSION: str = "0.2.0"
    API_PREFIX: str = "/api"
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"
    CORS_ORIGINS: str = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:5173")


settings = Settings()
