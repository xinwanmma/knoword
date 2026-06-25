@echo off
chcp 65001 >nul
setlocal

set "BACKEND_DIR=%~dp0backend"
set "FRONTEND_DIR=%~dp0frontend"

echo.
echo ========================================
echo   RAG Knowledge Base - Start
echo ========================================
echo.

REM --- [1/5] 环境检查 ---
echo [1/5] Checking environment...

python --version >nul 2>&1
if errorlevel 1 (
    echo   [FAIL] Python not found
    pause
    exit /b 1
)
for /f "delims=" %%v in ('python --version 2^>^&1') do echo   [OK] %%v

node --version >nul 2>&1
if errorlevel 1 (
    echo [WARN] Node.js not found - frontend will not start
    set "SKIP_FRONTEND=1"
) else (
    for /f "delims=" %%v in ('node --version 2^>^&1') do echo   [OK] %%v
)

ollama --version >nul 2>&1
if errorlevel 1 (
    echo   [WARN] Ollama not found - local embedding will not work
) else (
    echo   [OK] Ollama
)

REM 启动 Ollama（如果未运行）
curl -s http://localhost:11434/api/tags >nul 2>&1
if errorlevel 1 (
    if exist "%LOCALAPPDATA%\Programs\Ollama\ollama.exe" (
        echo   [INFO] Starting Ollama...
        start /b "" "%LOCALAPPDATA%\Programs\Ollama\ollama.exe" serve >nul 2>&1
        timeout /t 3 /nobreak >nul
    )
)

REM 检查 embedding 模型
curl -s http://localhost:11434/api/tags 2>nul | findstr "qwen3-embedding" >nul
if errorlevel 1 (
    echo   [INFO] Pulling qwen3-embedding:0.6b ...
    ollama pull qwen3-embedding:0.6b
)
echo   [OK] Embedding model ready
echo   [INFO] LLM: MiMo Cloud API (set MIMO_API_KEY in backend\.env)

REM MiMo API Key 检查
findstr /C:"MIMO_API_KEY=." "%BACKEND_DIR%\.env" >nul 2>&1
if errorlevel 1 (
    echo.
    echo   [WARN] backend\.env 未配置 MIMO_API_KEY
    echo          复制 backend\.env.example 为 .env 后填入 API Key
    echo.
)

REM PostgreSQL 检查
curl -s -o nul -w "%%{http_code}" http://localhost:5432 2>nul | findstr /v "200" >nul
if errorlevel 1 (
    echo   [WARN] PostgreSQL on port 5432 not responding
    echo          请确保 PostgreSQL 已启动并创建 rag_user / rag_kb
)

echo.

REM --- [2/5] 后端依赖 ---
echo [2/5] Installing backend dependencies...
cd /d "%BACKEND_DIR%"
pip install -r requirements.txt --quiet 2>nul
if errorlevel 1 (
    echo   [WARN] pip install had warnings - check output above
) else (
    echo   [OK] Backend ready
)
echo.

REM --- [3/5] 前端依赖 ---
echo [3/5] Installing frontend dependencies...
if defined SKIP_FRONTEND goto skip_frontend
cd /d "%FRONTEND_DIR%"
if not exist "node_modules" (
    npm install --silent 2>nul
    if errorlevel 1 (
        echo   [WARN] npm install had warnings
    ) else (
        echo   [OK] Frontend ready
    )
) else (
    echo   [OK] node_modules already exists
)
:skip_frontend
echo.

REM --- [4/5] 数据库迁移 ---
echo [4/5] Database migration...
cd /d "%BACKEND_DIR%"
alembic upgrade head 2>nul
if errorlevel 1 (
    echo   [WARN] alembic upgrade had warnings - check PostgreSQL connection
) else (
    echo   [OK] Database ready
)
echo.

REM --- [5/5] 启动服务 ---
echo [5/5] Starting services...
echo.
echo   Backend:  http://localhost:8000
if not defined SKIP_FRONTEND echo   Frontend: http://localhost:3000
echo   API Docs: http://localhost:8000/docs
echo.

start "RAG-Backend" cmd /k "cd /d %BACKEND_DIR% && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000"
timeout /t 3 /nobreak >nul

if not defined SKIP_FRONTEND (
    start "RAG-Frontend" cmd /k "cd /d %FRONTEND_DIR% && npm run dev"
)

echo ========================================
echo   All services started!
echo ========================================
echo.
pause
