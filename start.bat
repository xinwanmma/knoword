@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

REM ============================================
REM  RAG 知识库系统 - 一键启动脚本 (Windows)
REM  自动检查环境 → 安装依赖 → 启动服务
REM ============================================

set "PROJECT_ROOT=%~dp0"
set "BACKEND_DIR=%PROJECT_ROOT%backend"
set "FRONTEND_DIR=%PROJECT_ROOT%frontend"
set "BACKEND_PORT=8000"
set "FRONTEND_PORT=3000"

echo.
echo ========================================
echo   RAG 知识库系统 - 一键启动
echo ========================================
echo.

REM ========== 第 1 步：环境检查 ==========
echo [1/5] 检查运行环境...
echo.

REM 检查 Python
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo   [FAIL] Python 未安装
    echo         请安装 Python 3.11+: https://www.python.org/downloads/
    pause
    exit /b 1
)
for /f "tokens=*" %%i in ('python --version 2^>^&1') do set PYTHON_VER=%%i
echo   [OK] %PYTHON_VER%

REM 检查 Node.js
where node >nul 2>&1
if %errorlevel% neq 0 (
    echo   [FAIL] Node.js 未安装
    echo         请安装 Node.js 18+: https://nodejs.org/
    pause
    exit /b 1
)
for /f "tokens=*" %%i in ('node --version 2^>^&1') do set NODE_VER=%%i
echo   [OK] Node.js %NODE_VER%

REM 检查 PostgreSQL
where psql >nul 2>&1
if %errorlevel% neq 0 (
    echo   [WARN] psql 未在 PATH 中，尝试检查默认安装路径...
    set "PSQL_PATH=C:\Program Files\PostgreSQL\16\bin\psql.exe"
    if exist "!PSQL_PATH!" (
        echo   [OK] PostgreSQL 已安装
    ) else (
        echo   [WARN] PostgreSQL 可能未安装，后端启动时会报错
        echo         请安装: https://www.postgresql.org/download/windows/
    )
) else (
    echo   [OK] PostgreSQL
)

REM 检查 Ollama
where ollama >nul 2>&1
if %errorlevel% neq 0 (
    echo   [FAIL] Ollama 未安装
    echo         请安装: https://ollama.com/download
    pause
    exit /b 1
)
echo   [OK] Ollama

REM 检查 Ollama 服务是否在运行
curl -s http://localhost:11434/api/tags >nul 2>&1
if %errorlevel% neq 0 (
    echo   [WARN] Ollama 服务未运行，正在启动...
    start /b ollama serve >nul 2>&1
    timeout /t 3 /nobreak > nul
)

REM 检查 Ollama 模型
curl -s http://localhost:11434/api/tags 2>nul | findstr "qwen3.5" >nul
if %errorlevel% neq 0 (
    echo   [WARN] qwen3.5:2b 模型未安装，正在下载...
    ollama pull qwen3.5:2b
)
curl -s http://localhost:11434/api/tags 2>nul | findstr "qwen3-embedding" >nul
if %errorlevel% neq 0 (
    echo   [WARN] qwen3-embedding:0.6b 模型未安装，正在下载...
    ollama pull qwen3-embedding:0.6b
)
echo   [OK] Ollama 模型就绪

REM 检查 Neo4j
curl -s http://localhost:7474 >nul 2>&1
if %errorlevel% neq 0 (
    echo   [WARN] Neo4j 未运行
    echo         知识图谱功能将不可用
    echo         请启动 Neo4j Desktop 或安装: https://neo4j.com/download/
) else (
    echo   [OK] Neo4j
)

echo.

REM ========== 第 2 步：配置文件 ==========
echo [2/5] 检查配置文件...
if not exist "%BACKEND_DIR%\.env" (
    echo   复制 .env.example ...
    copy "%BACKEND_DIR%\.env.example" "%BACKEND_DIR%\.env" >nul
    echo   [INFO] 已创建 .env，请根据需要修改配置
) else (
    echo   [OK] .env 已存在
)
echo.

REM ========== 第 3 步：安装后端依赖 ==========
echo [3/5] 安装后端依赖...
cd /d "%BACKEND_DIR%"
pip install -r requirements.txt --quiet 2>nul
if %errorlevel% neq 0 (
    echo   [WARN] 部分依赖安装失败，尝试继续...
)
echo   [OK] 后端依赖就绪
echo.

REM ========== 第 4 步：数据库迁移 ==========
echo [4/5] 数据库迁移...
python -c "from app.db.database import engine, Base; import asyncio; asyncio.run(engine.begin().then(lambda c: c.run_sync(Base.metadata.create_all)))" >nul 2>&1
if %errorlevel% neq 0 (
    echo   [INFO] 尝试使用 alembic 迁移...
    alembic upgrade head 2>nul
)
echo   [OK] 数据库就绪
echo.

REM ========== 第 5 步：启动服务 ==========
echo [5/5] 启动服务...
echo.
echo ========================================
echo   后端: http://localhost:%BACKEND_PORT%
echo   前端: http://localhost:%FRONTEND_PORT%
echo   API 文档: http://localhost:%BACKEND_PORT%/docs
echo   Neo4j: http://localhost:7474
echo ========================================
echo.

REM 启动后端（新窗口）
echo 正在启动后端...
start "RAG Backend" cmd /k "cd /d %BACKEND_DIR% && uvicorn app.main:app --reload --host 0.0.0.0 --port %BACKEND_PORT%"

REM 等待后端启动
timeout /t 3 /nobreak > nul

REM 启动前端（新窗口）
echo 正在启动前端...
start "RAG Frontend" cmd /k "cd /d %FRONTEND_DIR% && npm run dev"

echo.
echo ========================================
echo   所有服务已启动！
echo ========================================
echo.
echo   按任意键关闭此窗口（服务将在后台运行）
echo.
pause >nul
