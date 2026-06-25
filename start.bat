@echo off
setlocal EnableExtensions
setlocal EnableDelayedExpansion

set "BACKEND_DIR=%~dp0backend"
set "FRONTEND_DIR=%~dp0frontend"

set "SKIP_FRONTEND=0"

echo.
echo ========================================
echo   RAG Knowledge Base - Start
echo ========================================
echo.

echo [1/5] Checking environment...

REM --- Python ---
where python >nul 2>&1
if errorlevel 1 goto err_python
for /f "tokens=2" %%v in ('python --version 2^>nul') do echo   [OK] Python %%v
goto check_node

:err_python
echo   [FAIL] Python not found in PATH
pause
exit /b 1

:check_node
REM --- Node.js ---
where node >nul 2>&1
if errorlevel 1 goto node_missing
for /f "tokens=1" %%v in ('node --version 2^>nul') do echo   [OK] Node.js %%v
goto check_ollama
:node_missing
echo   [WARN] Node.js not found - frontend will be skipped
set "SKIP_FRONTEND=1"

:check_ollama
REM --- Ollama ---
where ollama >nul 2>&1
if errorlevel 1 goto ollama_missing
echo   [OK] Ollama installed
goto ollama_start
:ollama_missing
echo   [WARN] Ollama not found - local embedding will not work

:ollama_start
REM Start Ollama if not responding
curl -s http://localhost:11434/api/tags >nul 2>&1
if errorlevel 1 goto need_ollama_start
goto check_embed
:need_ollama_start
if not exist "%LOCALAPPDATA%\Programs\Ollama\ollama.exe" goto check_embed
echo   [INFO] Starting Ollama...
start /b "" "%LOCALAPPDATA%\Programs\Ollama\ollama.exe" serve >nul 2>&1
timeout /t 3 /nobreak >nul

:check_embed
REM Pull embedding model if missing
curl -s http://localhost:11434/api/tags 2>nul | findstr "qwen3-embedding" >nul
if errorlevel 1 goto pull_embed
goto embed_ok
:pull_embed
echo   [INFO] Pulling qwen3-embedding:0.6b (one-time)
ollama pull qwen3-embedding:0.6b
:embed_ok
echo   [OK] Embedding model ready
echo   [INFO] LLM: MiMo Cloud API (set MIMO_API_KEY in backend\.env)

REM --- Check .env file ---
if exist "%BACKEND_DIR%\.env" goto env_ok
echo.
echo   [WARN] backend\.env not found
echo          Please: cd backend ^&^& copy .env.example .env
echo          Then edit .env and set MIMO_API_KEY
echo.
:env_ok

echo.
echo [2/5] Installing backend dependencies...
cd /d "%BACKEND_DIR%"
pip install -r requirements.txt --quiet 2>nul
if errorlevel 1 goto pip_warn
echo   [OK] Backend dependencies ready
goto pip_done
:pip_warn
echo   [WARN] pip install had warnings
:pip_done
echo.

echo [3/5] Installing frontend dependencies...
if "%SKIP_FRONTEND%"=="1" goto skip_frontend
cd /d "%FRONTEND_DIR%"
if exist "node_modules" goto fe_ok
call npm install --silent 2>nul
if errorlevel 1 goto fe_warn
echo   [OK] Frontend dependencies ready
goto fe_done
:fe_warn
echo   [WARN] npm install had warnings
goto fe_done
:fe_ok
echo   [OK] node_modules already exists
:fe_done
:skip_frontend
echo.

echo [4/5] Running database migration...
cd /d "%BACKEND_DIR%"
alembic upgrade head 2>nul
if errorlevel 1 goto mig_warn
echo   [OK] Database schema ready
goto mig_done
:mig_warn
echo   [WARN] alembic upgrade failed - check PostgreSQL connection
echo          Make sure PostgreSQL is running and rag_user/rag_kb exists
:mig_done
echo.

echo [5/5] Starting services...
echo.
echo   Backend:  http://localhost:8000
if "%SKIP_FRONTEND%"=="0" echo   Frontend: http://localhost:3000
echo   API Docs: http://localhost:8000/docs
echo.

start "RAG-Backend" cmd /k "cd /d %BACKEND_DIR% && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000"
timeout /t 3 /nobreak >nul

if "%SKIP_FRONTEND%"=="0" start "RAG-Frontend" cmd /k "cd /d %FRONTEND_DIR% && npm run dev"

echo ========================================
echo   All services started!
echo   Close the popup windows to stop them.
echo ========================================
echo.
pause
