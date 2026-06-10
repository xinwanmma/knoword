# 📚 RAG 知识库系统

基于 RAG（检索增强生成）的智能知识库问答系统。支持多种文档格式上传、中文语义检索、流式对话，引用来源可追溯。

## ✨ 功能特性

- **多格式文档支持** — PDF、DOCX、XLSX、PPTX、TXT、MD、CSV、JSON、HTML 一键上传
- **中文优化分块** — 句子级切分 + tiktoken 精确 token 计数，不破坏语义完整性
- **流式对话** — SSE 逐 token 打字机效果，引用来源先行渲染
- **引用来源追溯** — 每条回答附带原文出处、页码、相关度评分
- **多轮上下文** — 保留最近 5 轮对话历史
- **知识库分类管理** — 分类、全局/私有知识库、管理员全局库
- **角色权限** — 管理员 / 普通用户，JWT 认证
- **系统健康监控** — 一键检查 PostgreSQL、ChromaDB、Ollama 服务状态

## 🛠 技术栈

| 组件 | 技术 |
|------|------|
| 后端 | FastAPI + SQLAlchemy (async) + Alembic |
| 数据库 | PostgreSQL |
| 向量库 | ChromaDB |
| LLM | Ollama 本地模型 (qwen3:2b) |
| Embedding | Ollama 本地模型 (qwen3-embedding:0.6b) |
| 前端 | Vue3 + Vite + Element Plus |
| 认证 | JWT + bcrypt |

## 🚀 快速开始

### 前置条件

- Python 3.11+
- Node.js 18+
- PostgreSQL（已安装并运行）
- Ollama（已安装，模型已拉取）

### 1. 拉取 Ollama 模型

```bash
ollama pull qwen3:2b
ollama pull qwen3-embedding:0.6b
```

### 2. 准备数据库

```sql
-- 在 PostgreSQL 中执行
CREATE USER rag_user WITH PASSWORD 'rag_password';
CREATE DATABASE rag_kb OWNER rag_user;
```

### 3. 配置环境变量

```bash
cd backend
copy .env.example .env
```

编辑 `.env`，确保数据库连接信息正确，并**修改默认管理员密码**：

```
DATABASE_URL=postgresql+asyncpg://rag_user:rag_password@localhost:5432/rag_kb
DATABASE_URL_SYNC=postgresql://rag_user:rag_password@localhost:5432/rag_kb
OLLAMA_BASE_URL=http://localhost:11434

# 管理员账号（首次启动自动创建，之后忽略）
ADMIN_USERNAME=admin
ADMIN_PASSWORD=your-secure-password
ADMIN_EMAIL=admin@example.com
```

> ⚠️ **首次启动**会自动创建默认管理员账号，日志中会打印用户名和密码。请务必在生产环境中修改密码。

### 4. 启动后端

```bash
cd backend

# 安装依赖
pip install -r requirements.txt

# 首次运行：生成数据库迁移
alembic revision --autogenerate -m "init"
alembic upgrade head

# 启动服务（端口 8080）
uvicorn app.main:app --reload --port 8080
```

### 5. 启动前端

```bash
cd frontend

# 安装依赖
npm install

# 启动开发服务器（端口 3000）
npm run dev
```

### 6. 访问

- 前端界面：http://localhost:3000
- 后端 API 文档：http://localhost:8080/docs

## 📂 项目结构

```
.
├── backend/
│   ├── app/
│   │   ├── api/            # 路由层
│   │   │   ├── auth.py         # 认证（注册/登录）
│   │   │   ├── chat.py         # 对话（SSE 流式）
│   │   │   ├── documents.py    # 文档管理
│   │   │   ├── health.py       # 健康检查
│   │   │   └── knowledge_base.py  # 知识库 + 分类
│   │   ├── core/
│   │   │   └── security.py     # JWT + 权限
│   │   ├── db/
│   │   │   └── database.py     # 数据库连接
│   │   ├── models/
│   │   │   └── models.py       # SQLAlchemy 模型
│   │   ├── schemas/
│   │   │   └── schemas.py      # Pydantic 数据模式
│   │   ├── services/
│   │   │   ├── chunker.py          # 中文优化分块
│   │   │   ├── document_processor.py  # 文档处理管道
│   │   │   ├── ollama_service.py      # Ollama 调用
│   │   │   ├── parser.py             # 9 格式文档解析
│   │   │   └── vectorstore.py        # ChromaDB 集成
│   │   ├── config.py           # 配置
│   │   └── main.py             # FastAPI 入口
│   ├── alembic/            # 数据库迁移
│   ├── .env.example        # 环境变量模板
│   └── requirements.txt    # Python 依赖
├── frontend/
│   ├── src/
│   │   ├── api/            # Axios + SSE 封装
│   │   ├── router/         # Vue Router
│   │   ├── stores/         # Pinia 状态管理
│   │   ├── views/          # 页面组件
│   │   │   ├── ChatView.vue       # 对话页
│   │   │   ├── KnowledgeBaseView.vue  # 知识库管理
│   │   │   ├── LoginView.vue      # 登录
│   │   │   ├── RegisterView.vue   # 注册
│   │   │   ├── AdminView.vue      # 管理员面板
│   │   │   └── StatusView.vue     # 系统状态
│   │   ├── App.vue         # 布局
│   │   └── main.js         # 入口
│   └── package.json
├── docker-compose.yml      # PostgreSQL + ChromaDB（可选）
├── start.bat               # Windows 一键启动
└── plan.md                 # 完整实现计划
```

## 📡 API 接口一览

### 认证

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/auth/register` | 注册 |
| POST | `/api/auth/login` | 登录 |
| GET | `/api/auth/me` | 当前用户信息 |

### 知识库

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/kb` | 创建知识库 |
| GET | `/api/kb` | 列出可访问的知识库 |
| GET | `/api/kb/{id}` | 知识库详情 |
| PUT | `/api/kb/{id}` | 更新知识库 |
| DELETE | `/api/kb/{id}` | 删除知识库 |

### 文档

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/documents/upload?kb_id=1` | 上传文档（多文件） |
| GET | `/api/documents/{id}/status` | 查询处理状态 |
| DELETE | `/api/documents/{id}` | 删除文档 |
| POST | `/api/documents/{id}/reindex` | 重新向量化 |

### 对话

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/chat` | 发送消息（SSE 流式返回） |
| GET | `/api/chat/history` | 会话列表 |
| GET | `/api/chat/history/{id}` | 对话消息详情 |
| DELETE | `/api/chat/history/{id}` | 删除对话 |

### 系统

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查 |
| GET | `/api/categories` | 分类列表 |
| POST | `/api/categories` | 添加分类（admin） |

## ⚙️ 配置说明

所有配置项在 `backend/.env` 中设置：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `DATABASE_URL` | `postgresql+asyncpg://...` | 数据库连接 |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama 地址 |
| `OLLAMA_LLM_MODEL` | `qwen3:2b` | 对话模型 |
| `OLLAMA_EMBED_MODEL` | `qwen3-embedding:0.6b` | 向量模型 |
| `CHUNK_TARGET_TOKENS` | `300` | 目标分块大小 |
| `CHUNK_MAX_TOKENS` | `512` | 最大分块大小 |
| `CHUNK_OVERLAP_SENTENCES` | `2` | 重叠句数 |
| `MAX_UPLOAD_SIZE_MB` | `50` | 最大上传文件大小 |
| `JWT_SECRET_KEY` | — | JWT 密钥（必须修改） |
| `ADMIN_USERNAME` | `admin` | 默认管理员用户名 |
| `ADMIN_PASSWORD` | `admin123456` | 默认管理员密码（必须修改） |
| `ADMIN_EMAIL` | `admin@example.com` | 默认管理员邮箱 |

## 🔧 常见问题

### Ollama 没启动？

后端会返回友好错误提示。确保 Ollama 正在运行：

```bash
ollama serve
```

### 数据库连接失败？

检查 PostgreSQL 是否启动，以及 `.env` 中的连接信息是否正确。

### 前端请求 404？

确认后端在 8080 端口运行，Vite 代理配置正确。

### 分块效果不好？

调整 `CHUNK_TARGET_TOKENS` 和 `CHUNK_MAX_TOKENS` 参数，修改后重新上传文档并 reindex。

## 📝 License

MIT
