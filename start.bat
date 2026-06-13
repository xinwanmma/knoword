@echo off
setlocal

set "BACKEND_DIR=%~dp0backend"
set "FRONTEND_DIR=%~dp0frontend"

echo.
echo ========================================
echo   RAG Knowledge Base - Start
echo ========================================
echo.

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
    echo   [FAIL] Node.js not found
    pause
    exit /b 1
)
for /f "delims=" %%v in ('node --version 2^>^&1') do echo   [OK] Node.js %%v

ollama --version >nul 2>&1
if errorlevel 1 (
    echo   [FAIL] Ollama not found
    pause
    exit /b 1
)
echo   [OK] Ollama

curl -s http://localhost:11434/api/tags >nul 2>&1
if errorlevel 1 (
    echo   [INFO] Starting Ollama...
    start /b ollama serve >nul 2>&1
    timeout /t 3 /nobreak >nul
)

curl -s http://localhost:11434/api/tags 2>nul | findstr "qwen3.5" >nul
if errorlevel 1 (
    echo   [INFO] Pulling qwen3.5:2b ...
    ollama pull qwen3.5:2b
)
curl -s http://localhost:11434/api/tags 2>nul | findstr "qwen3-embedding" >nul
if errorlevel 1 (
    echo   [INFO] Pulling qwen3-embedding:0.6b ...
    ollama pull qwen3-embedding:0.6b
)
echo   [OK] Models ready

echo.
echo [2/5] Installing backend dependencies...
cd /d "%BACKEND_DIR%"
pip install -r requirements.txt --quiet 2>nul
echo   [OK] Backend ready

echo [3/5] Installing frontend dependencies...
cd /d "%FRONTEND_DIR%"
if not exist "node_modules" (
    npm install --silent 2>nul
)
echo   [OK] Frontend ready
echo.

echo [4/5] Database migration...
cd /d "%BACKEND_DIR%"
alembic upgrade head 2>nul
echo   [OK] Database ready
echo.

echo [5/5] Starting services...
echo.
echo   Backend:  http://localhost:8000
echo   Frontend: http://localhost:3000
echo   API Docs: http://localhost:8000/docs
echo.

start "RAG-Backend" cmd /k "cd /d %BACKEND_DIR% && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000"
timeout /t 3 /nobreak >nul
start "RAG-Frontend" cmd /k "cd /d %FRONTEND_DIR% && npm run dev"

echo ========================================
echo   All services started!
echo ========================================
echo.
pause
