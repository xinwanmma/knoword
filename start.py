#!/usr/bin/env python3
"""RAG 知识库启动脚本（纯 Python 跨平台版）。

启动前会逐项检查（不会自动下载任何依赖）：
  1. Python 版本 >= 3.10
  2. .env 文件存在
  3. PostgreSQL 可达（端口 5432）
  4. Ollama 可达（端口 11434）
  5. MIMO_API_KEY 已设置
  6. 后端 Python 依赖已安装
  7. 前端 node_modules 存在（可用 --no-frontend 跳过）

通过后启动后端和前端（在独立命令行窗口中运行）。

使用：
  python start.py                # 启动后端 + 前端
  python start.py --no-frontend  # 只启动后端
  python start.py --check        # 只检查，不启动
"""
from __future__ import annotations

import os
import re
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Optional, Tuple

# ============================
# 路径
# ============================
ROOT = Path(__file__).resolve().parent
BACKEND_DIR = ROOT / "backend"
FRONTEND_DIR = ROOT / "frontend"
ENV_FILE = BACKEND_DIR / ".env"
ENV_EXAMPLE = BACKEND_DIR / ".env.example"
REPORT_DIR = BACKEND_DIR / "reports"

# ============================
# 控制台颜色
# ============================
class C:
    R = "\033[91m"
    G = "\033[92m"
    Y = "\033[93m"
    B = "\033[94m"
    M = "\033[95m"
    D = "\033[90m"
    BOLD = "\033[1m"
    END = "\033[0m"

if sys.platform == "win32":
    # 让 Windows cmd 识别 ANSI 颜色
    os.system("")


def log(msg: str) -> None:
    print(f"{C.B}[INFO]{C.END} {msg}")


def ok(msg: str) -> None:
    print(f"{C.G}[ OK ]{C.END} {msg}")


def warn(msg: str) -> None:
    print(f"{C.Y}[WARN]{C.END} {msg}")


def err(msg: str) -> None:
    print(f"{C.R}[FAIL]{C.END} {msg}")


def die(msg: str, code: int = 1) -> None:
    err(msg)
    sys.exit(code)


# ============================
# 检查项
# ============================

def check_python() -> None:
    if sys.version_info < (3, 10):
        die(f"Python 3.10+ required, current: {sys.version_info.major}.{sys.version_info.minor}")
    ok(f"Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")


def _read_env_value(key: str) -> Optional[str]:
    """从 .env 读取一个 KEY=VALUE，忽略注释和空行。"""
    if not ENV_FILE.exists():
        return None
    try:
        text = ENV_FILE.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = ENV_FILE.read_text(encoding="gbk", errors="replace")
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip()
    return None


def check_env_file() -> None:
    if not ENV_FILE.exists():
        die(
            f".env not found: {ENV_FILE}\n"
            f"     Run: cd {BACKEND_DIR.name} && cp {ENV_EXAMPLE.name} .env\n"
            f"     Then edit .env and fill in MIMO_API_KEY (and other [!!] items)"
        )
    ok(f".env exists: {ENV_FILE.name}")


def _parse_postgres_host_port(url: str) -> Tuple[str, int]:
    """从 postgresql+asyncpg://user:pass@host:port/db 解析 host/port"""
    m = re.search(r"@([^:/]+):(\d+)", url)
    if m:
        return m.group(1), int(m.group(2))
    return "localhost", 5432


def check_postgres() -> None:
    url = _read_env_value("DATABASE_URL")
    if not url:
        die("DATABASE_URL not set in .env")
    host, port = _parse_postgres_host_port(url)
    log(f"Probing PostgreSQL at {host}:{port} ...")
    try:
        s = socket.create_connection((host, port), timeout=3)
        s.close()
    except (socket.timeout, ConnectionRefusedError, OSError) as e:
        die(
            f"Cannot connect to PostgreSQL at {host}:{port}\n"
            f"     {e}\n"
            f"     Make sure PostgreSQL is running and rag_user / rag_kb exist.\n"
            f"     SQL: CREATE USER rag_user WITH PASSWORD 'rag_password';\n"
            f"          CREATE DATABASE rag_kb OWNER rag_user;"
        )
    ok(f"PostgreSQL reachable at {host}:{port}")


def _http_get(url: str, timeout: float = 3.0) -> Tuple[Optional[int], object]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status, r.read()
    except Exception as e:
        return None, e


def check_ollama() -> None:
    log("Probing Ollama at http://localhost:11434 ...")
    status, _ = _http_get("http://localhost:11434/api/tags")
    if status != 200:
        die(
            "Ollama not reachable at http://localhost:11434\n"
            "     Start it manually: ollama serve"
        )
    ok("Ollama is running")


def check_mimo_key() -> None:
    val = _read_env_value("MIMO_API_KEY") or ""
    placeholder_markers = ("change-me", "your-key", "your_key", "xxxxx", "todo")
    if not val or any(p in val.lower() for p in placeholder_markers):
        die(
            "MIMO_API_KEY is empty or placeholder in .env\n"
            "     Get one at: https://api.xiaomimimo.com/\n"
            "     Then set in .env: MIMO_API_KEY=sk-xxxxx"
        )
    ok(f"MIMO_API_KEY is set (length={len(val)})")


def check_backend_deps() -> None:
    log("Checking backend Python dependencies ...")
    # 关键模块（避免 langchain_experimental 这种可选依赖）
    required = [
        "fastapi", "uvicorn", "sqlalchemy", "asyncpg", "alembic",
        "chromadb", "langchain_core", "langchain_openai",
        "pydantic", "dotenv", "httpx", "jose", "passlib", "bcrypt",
    ]
    missing = []
    for mod in required:
        try:
            __import__(mod)
        except ImportError:
            missing.append(mod)
    if missing:
        die(
            f"Missing Python packages: {', '.join(missing)}\n"
            f"     Run: cd {BACKEND_DIR.name} && pip install -r requirements.txt"
        )
    ok(f"Backend dependencies OK ({len(required)} modules)")


def check_frontend_deps() -> None:
    log("Checking frontend dependencies ...")
    if not (FRONTEND_DIR / "node_modules").exists():
        die(
            f"Frontend node_modules not found\n"
            f"     Run: cd {FRONTEND_DIR.name} && npm install"
        )
    pkg_lock = FRONTEND_DIR / "package.json"
    if not pkg_lock.exists():
        die(f"package.json not found in {FRONTEND_DIR}")
    ok("Frontend node_modules found")


# ============================
# 启动服务
# ============================

def start_in_new_window(title: str, cmd_str: str, cwd: Path) -> None:
    """在新命令行窗口中运行命令（仅 Windows）。"""
    if sys.platform == "win32":
        # 用 shell=True + 字符串，让 cmd 自己解析 start 的 title 引号规则
        # 注意：cmd_str 需要自己加双引号以防路径含空格
        # 不需要 CREATE_NEW_CONSOLE —— start 命令本身就会开新窗口
        full = f'start "{title}" cmd /k "{cmd_str}"'
        subprocess.Popen(full, cwd=str(cwd), shell=True)
    elif sys.platform == "darwin":
        # macOS：用 osascript 打开 Terminal.app 新窗口
        script = f'tell application "Terminal" to do script "cd \\"{cwd}\\" && {cmd_str}"'
        subprocess.Popen(["osascript", "-e", script])
    else:
        # Linux：尝试用 gnome-terminal / xterm
        for term in ("gnome-terminal", "konsole", "xterm"):
            try:
                subprocess.Popen(
                    [term, "--", "bash", "-c", f'cd "{cwd}" && {cmd_str}; exec bash'],
                    creationflags=0,
                )
                return
            except FileNotFoundError:
                continue
        warn(f"Cannot auto-open a new terminal on {sys.platform}")
        warn(f"Please run manually: cd {cwd} && {cmd_str}")


def start_backend() -> None:
    cmd = "uvicorn app.main:app --reload --host 0.0.0.0 --port 8000"
    log(f"Starting backend: {cmd}")
    start_in_new_window("RAG-Backend", cmd, BACKEND_DIR)
    ok("Backend window opened")


def start_frontend() -> None:
    cmd = "npm run dev"
    log(f"Starting frontend: {cmd}")
    start_in_new_window("RAG-Frontend", cmd, FRONTEND_DIR)
    ok("Frontend window opened")


def wait_for_backend() -> None:
    log("Waiting for backend at http://localhost:8000 (up to 30s) ...")
    for i in range(30):
        status, _ = _http_get("http://localhost:8000/docs", timeout=1.5)
        if status == 200:
            ok("Backend is responding")
            return
        time.sleep(1)
    warn("Backend did not respond in 30s — check the backend window for errors")


# ============================
# 入口
# ============================

def main() -> None:
    print()
    print(f"{C.BOLD}{C.M}=== RAG Knowledge Base - Start ==={C.END}")
    print()

    args = sys.argv[1:]
    check_only = "--check" in args
    no_frontend = "--no-frontend" in args

    # 检查
    check_python()
    check_env_file()
    check_postgres()
    check_ollama()
    check_mimo_key()
    check_backend_deps()
    if not no_frontend:
        check_frontend_deps()

    if check_only:
        print()
        ok(f"{C.BOLD}All checks passed!{C.END}")
        return

    if no_frontend:
        warn("Skipping frontend (--no-frontend)")

    print()
    start_backend()
    wait_for_backend()
    if not no_frontend:
        time.sleep(2)
        start_frontend()

    print()
    print(f"{C.G}{C.BOLD}=== All services started ==={C.END}")
    print(f"  {C.BOLD}Backend:{C.END}  http://localhost:8000")
    if not no_frontend:
        print(f"  {C.BOLD}Frontend:{C.END} http://localhost:3000")
    print(f"  {C.BOLD}API Docs:{C.END} http://localhost:8000/docs")
    print()
    print(f"{C.D}Close the popup windows to stop the services.{C.END}")
    print(f"{C.D}Press Enter to exit this launcher (services keep running).{C.END}")
    try:
        input()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print()
        warn("Interrupted")
        sys.exit(130)
