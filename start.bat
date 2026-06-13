@echo off
setlocal

REM ============================================
REM  RAG 知识库系统 - 一键启动脚本 (Windows)
REM ============================================

set "BACKEND_DIR=%~dp0backend"
set "FRONTEND_DIR=%~dp0frontend"

echo.
echo ========================================
echo   RAG 知识库系统 - 一键启动
echo ========================================
echo.

REM --- 1. 检查 Python ---
echo [1/5] 检查环境...
python --version >nul 2>&1
if errorlevel 1 (
    echo   [FAIL] Python 未安装，请安装 Python 3.11+
    pause
    exit /b 1
)
for /f "delims=" %%v in ('python --version 2^>^&1') do echo   [OK] %%v

REM --- 2. 检查 Node.js ---
node --version >nul 2>&1
if errorlevel 1 (
    echo   [FAIL] Node.js 未安装，请安装 Node.js 18+
    pause
    exit /b 1
)
for /f "delims=" %%v in ('node --version 2^>^&1') do echo   [OK] Node.js %%v

REM --- 3. 检查 Ollama ---
ollama --version >nul 2>&1
if errorlevel 1 (
    echo   [FAIL] Ollama 未安装，请安装 https://ollama.com/download
    pause
    exit /b 1
)
echo   [OK] Ollama

REM 检查 Ollama 服务
curl -s http://localhost:11434/api/tags >nul 2>&1
if errorlevel 1 (
    echo   [INFO] Ollama 服务未运行，正在启动...
    start /b ollama serve >nul 2>&1
    timeout /t 3 /nobreak >nul
)

REM 检查模型
curl -s http://localhost:11434/api/tags 2>nul | findstr "qwen3.5" >nul
if errorlevel 1 (
    echo   [INFO] 正在下载 qwen3.5:2b ...
    ollama pull qwen3.5:2b
)
curl -s http://localhost:11434/api/tags 2>nul | findstr "qwen3-embedding" >nul
if errorlevel 1 (
    echo   [INFO] 正在下载 qwen3-embedding:0.6b ...
    ollama pull qwen3-embedding:0.6b
)
echo   [OK] Ollama 模型就绪

REM --- 4. 检查 Neo4j ---
curl -s http://localhost:7474 >nul 2>&1
if errorlevel 1 (
    echo   [WARN] Neo4j 未运行，知识图谱功能不可用
) else (
    echo   [OK] Neo4j
)

REM --- 5. 检查 .env ---
if not exist "%BACKEND_DIR%\.env" (
    echo   复制 .env ...
    copy "%BACKEND_DIR%\.env.example" "%BACKEND_DIR%\.env" >nul
)
echo   [OK] 配置文件就绪
echo.

REM ========== 安装依赖 ==========
echo [2/5] 安装后端依赖...
cd /d "%BACKEND_DIR%"
pip install -r requirements.txt --quiet 2>nul
echo   [OK] 后端依赖就绪

echo [3/5] 安装前端依赖...
cd /d "%FRONTEND_DIR%"
if not exist "node_modules" (
    npm install --silent 2>nul
)
echo   [OK] 前端依赖就绪
echo.

REM ========== 数据库 ==========
echo [4/5] 数据库初始化...
cd /d "%BACKEND_DIR%"
alembic upgrade head 2>nul
echo   [OK] 数据库就绪
echo.

REM ========== 启动服务 ==========
echo [5/5] 启动服务...
echo.
echo   后端: http://localhost:8000
echo   前端: http://localhost:3000
echo   API 文档: http://localhost:8000/docs
echo   Neo4j: http://localhost:7474
echo.

start "RAG-Backend" cmd /k "cd /d %BACKEND_DIR% && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000"
timeout /t 3 /nobreak >nul
start "RAG-Frontend" cmd /k "cd /d %FRONTEND_DIR% && npm run dev"

echo ========================================
echo   所有服务已启动！
echo ========================================
echo.
pause
