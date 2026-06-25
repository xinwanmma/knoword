@echo off
setlocal EnableExtensions

set "BACKEND_DIR=%~dp0backend"
set "FRONTEND_DIR=%~dp0frontend"

echo.
echo ========================================
echo   RAG Knowledge Base - Start
echo ========================================
echo.

echo [1/5] Checking environment...

where python >nul 2>&1
if errorlevel 1 (
    echo   [FAIL] Python not found in PATH
    pause
    exit /b 1
)
for /f "tokens=2" %%v in ('python --version 2^>^&1') do echo   [OK] Python %%v

where node >nul 2>&1
if errorlevel 1 (
    echo   [WARN] Node.js not found - frontend will be skipped
    set "SKIP_FRONTEND=1"
) else (
    for /f "tokens=1" %%v in ('node --version 2^>^&1') do echo   [OK] Node.js %%v
)

where ollama >nul 2>&1
if errorlevel 1 (
    echo   [WARN] Ollama not found - local embedding will not work
) else (
    echo   [OK] Ollama installed
)

REM Try to start Ollama if not responding
curl -s http://localhost:11434/api/tags >nul 2>&1
if errorlevel 1 (
    if exist "%LOCALAPPDATA%\Programs\Ollama\ollama.exe" (
        echo   [INFO] Starting Ollama...
        start /b "" "%LOCALAPPDATA%\Programs\Ollama\ollama.exe" serve >nul 2>&1
        timeout /t 3 /nobreak >nul
    )
)

REM Pull embedding model if missing
curl -s http://localhost:11434/api/tags 2>nul | findstr "qwen3-embedding" >nul
if errorlevel 1 (
    echo   [INFO] Pulling qwen3-embedding:0.6b (one-time)...
    ollama pull qwen3-embedding:0.6b
)
echo   [OK] Embedding model ready
echo   [INFO] LLM: MiMo Cloud API (set MIMO_API_KEY in backend\.env)

REM Check .env file
if not exist "%BACKEND_DIR%\.env" (
    echo.
    echo   [WARN] backend\.env not found
    echo          Please: cd backend ^&^& copy .env.example .env
    echo          Then edit .env and set MIMO_API_KEY
    echo.
)

echo.

echo [2/5] Installing backend dependencies...
cd /d "%BACKEND_DIR%"
pip install -r requirements.txt --quiet 2>nul
if errorlevel 1 (
    echo   [WARN] pip install had warnings
) else (
    echo   [OK] Backend dependencies ready
)
echo.

echo [3/5] Installing frontend dependencies...
if defined SKIP_FRONTEND goto skip_frontend
cd /d "%FRONTEND_DIR%"
if not exist "node_modules" (
    call npm install --silent 2>nul
    if errorlevel 1 (
        echo   [WARN] npm install had warnings
    ) else (
        echo   [OK] Frontend dependencies ready
    )
) else (
    echo   [OK] node_modules already exists
)
:skip_frontend
echo.

echo [4/5] Running database migration...
cd /d "%BACKEND_DIR%"
alembic upgrade head 2>nul
if errorlevel 1 (
    echo   [WARN] alembic upgrade failed - check PostgreSQL connection
    echo          Make sure PostgreSQL is running and rag_user/rag_kb exists
) else (
    echo   [OK] Database schema ready
)
echo.

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
echo   Close the popup windows to stop them.
echo ========================================
echo.
pause
