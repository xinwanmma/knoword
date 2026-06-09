@echo off
REM ============================================
REM RAG 知识库系统 - Windows 启动脚本
REM ============================================

echo.
echo ========================================
echo   RAG 知识库系统 - 启动中...
echo ========================================
echo.

REM 检查 .env 文件
if not exist "backend\.env" (
    echo [INFO] 未找到 .env 文件，正在从模板复制...
    copy "backend\.env.example" "backend\.env"
    echo [INFO] 请编辑 backend\.env 配置你的环境变量
)

REM 启动 Docker 服务
echo [1/3] 启动 Docker 服务 (PostgreSQL + ChromaDB)...
docker-compose up -d
echo.

REM 等待服务就绪
echo [2/3] 等待服务就绪...
timeout /t 5 /nobreak > nul
echo.

REM 启动后端
echo [3/3] 启动后端服务...
cd backend
pip install -r requirements.txt > nul 2>&1
uvicorn app.main:app --reload --host 0.0.0.0 --port 8080
cd ..
