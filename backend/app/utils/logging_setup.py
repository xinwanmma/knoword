"""统一日志配置：所有项目日志输出到 backend/logs/。

按模块分文件 + 按天滚动 + 控制台双输出 + 全量汇总 + ERROR 单独文件。

启动：main.py 顶部 import 时自动调 setup_logging()。
"""
import logging
import os
import sys
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler


# 日志根目录
LOG_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "logs"))


# 日志格式
STANDARD_FORMAT = "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s"
DETAILED_FORMAT = (
    "[%(asctime)s] [%(levelname)s] [%(name)s] "
    "[%(filename)s:%(lineno)d] %(message)s"
)
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def _make_file_handler(
    filename: str,
    level: int = logging.INFO,
    formatter: str | None = None,
    when: str = "midnight",
    backup_count: int = 7,
) -> TimedRotatingFileHandler:
    """创建按天滚动的文件 handler。"""
    os.makedirs(LOG_DIR, exist_ok=True)
    filepath = os.path.join(LOG_DIR, filename)
    fh = TimedRotatingFileHandler(
        filepath,
        when=when,
        interval=1,
        backupCount=backup_count,
        encoding="utf-8",
    )
    fh.suffix = "%Y-%m-%d"
    fh.setLevel(level)
    fmt = logging.Formatter(formatter or STANDARD_FORMAT, datefmt=DATE_FORMAT)
    fh.setFormatter(fmt)
    return fh


def _make_module_filter(names: tuple[str, ...]) -> logging.Filter:
    """只接受指定 logger name 前缀的 filter。"""

    class _ModuleFilter(logging.Filter):
        def filter(self, record: logging.LogRecord) -> bool:
            return any(record.name == n or record.name.startswith(n + ".") for n in names)

    return _ModuleFilter()


def setup_logging(level: int = logging.INFO) -> None:
    """配置全局 logging：控制台 + 全量文件 + 按模块分文件 + ERROR 单独文件。

    调用后所有 `logger = logging.getLogger(__name__)` 自动写到对应文件。
    """
    root = logging.getLogger()
    # 清空已存在的 handler（防止 uvicorn reload 重复添加）
    for h in list(root.handlers):
        root.removeHandler(h)
    root.setLevel(level)

    # 1. 控制台
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(level)
    console.setFormatter(logging.Formatter(DETAILED_FORMAT, datefmt=DATE_FORMAT))
    root.addHandler(console)

    # 2. 全量文件（每天滚动，保留 7 天）
    all_fh = _make_file_handler(
        f"all_{datetime.now().strftime('%Y%m%d')}.log",
        level=logging.DEBUG,
        formatter=DETAILED_FORMAT,
    )
    root.addHandler(all_fh)

    # 3. ERROR 单独文件（关键错误）
    err_fh = _make_file_handler(
        f"error_{datetime.now().strftime('%Y%m%d')}.log",
        level=logging.ERROR,
        formatter=DETAILED_FORMAT,
    )
    root.addHandler(err_fh)

    # 4. 按模块分文件
    module_files = {
        "embedding.log": ("app.services.embedding",),
        "llm.log": ("app.services.llm_provider",),
        "eval.log": ("app.services.eval",),
        "retrieval.log": ("app.services.retrieval",),
        "rerank.log": ("app.services.rerank",),
        "vectorstore.log": ("app.services.vectorstore",),
        "api.log": ("app.api",),
        "db.log": ("app.db",),
        "chunking.log": ("app.services.chunking",),
        "document_processor.log": ("app.services.document_processor",),
        "parser.log": ("app.services.parser",),
    }
    for filename, names in module_files.items():
        fh = _make_file_handler(filename, level=logging.DEBUG, formatter=DETAILED_FORMAT)
        fh.addFilter(_make_module_filter(names))
        root.addHandler(fh)

    # 5. 抑制过吵的第三方库
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("chromadb").setLevel(logging.WARNING)
    logging.getLogger("multipart").setLevel(logging.WARNING)

    # 启动日志
    root.info("=" * 70)
    root.info(f"📂 日志系统已启动 → {LOG_DIR}")
    root.info("=" * 70)


def get_logger(name: str) -> logging.Logger:
    """便捷获取 logger（带 __name__ 风格）。"""
    return logging.getLogger(name)
