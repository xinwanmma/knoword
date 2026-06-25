# 📚 RAG 知识库系统

基于 LangGraph + RAG 的简洁知识库问答系统。

> **当前 LLM 后端**：小米 **MiMo** 云端 API（OpenAI 兼容）。
> Embedding 仍使用本地 **Ollama**（`qwen3-embedding:0.6b`）。

## ✨ 功能

- **RAG 检索** — 向量检索 + Score Fusion Reranking + 中文优化分块
- **真实流式** — llm.astream() 逐 token 输出，非模拟
- **多轮对话** — 对话历史持久化，支持继续提问
- **多知识库** — 用户私有知识库，支持选/全检索
- **多格式文档** — PDF、DOCX、TXT、MD、XLSX、PPTX、CSV、JSON、HTML

## 🛠 技术栈

| 组件 | 技术 |
|------|------|
| 后端 | FastAPI + SQLAlchemy (async) + Alembic |
| Agent | LangGraph StateGraph |
| LLM | **MiMo 云端 API** (mimo-v2.5-pro) — 通过 langchain-openai |
| Embedding | **Ollama 本地** (qwen3-embedding:0.6b) |
| 向量库 | ChromaDB |
| 前端 | Vue3 + Vite + Element Plus |
| 认证 | JWT + bcrypt |

## 🚀 快速开始

### 一键启动（Windows）

```bash
start.bat
```

### 手动启动

```bash
# 1. Ollama
ollama pull qwen3.5:2b
ollama pull qwen3-embedding:0.6b

# 2. PostgreSQL
CREATE USER rag_user WITH PASSWORD 'rag_password';
CREATE DATABASE rag_kb OWNER rag_user;

# 3. 后端
cd backend
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload --port 8000

# 4. 前端
cd frontend
npm install
npm run dev
```

### 访问

| 服务 | 地址 |
|------|------|
| 前端 | http://localhost:3000 |
| API 文档 | http://localhost:8000/docs |

### 默认管理员

- 用户名：`admin`
- 密码：`admin123456`（首次启动自动创建，可在 .env 修改）

## 📂 项目结构

```
backend/
├── app/
│   ├── api/
│   │   ├── auth.py             # 认证（注册/登录/me）
│   │   ├── chat.py             # 对话（LangGraph + 真实流式）
│   │   ├── documents.py        # 文档管理
│   │   ├── health.py           # 健康检查
│   │   └── knowledge_base.py   # 知识库 CRUD
│   ├── core/
│   │   ├── embeddings.py       # OllamaEmbeddings
│   │   ├── llm.py              # ChatOllama
│   │   └── security.py         # JWT + 权限
│   ├── middleware/
│   │   └── logging.py
│   ├── models/
│   │   └── models.py           # ORM 模型
│   ├── schemas/
│   │   └── schemas.py          # Pydantic 模式
│   ├── services/
│   │   ├── agent_graph.py      # LangGraph 图
│   │   ├── chunker.py          # 中文优化分块
│   │   ├── document_processor.py
│   │   ├── hybrid_search.py    # BM25 + 向量（备选）
│   │   ├── ollama_service.py
│   │   ├── parser.py           # 9 格式文档解析
│   │   ├── reranker.py         # Score Fusion
│   │   └── vectorstore.py      # ChromaDB
│   ├── config.py
│   └── main.py
├── tests/
├── alembic/
└── requirements.txt

frontend/
├── src/
│   ├── api/index.js
│   ├── views/ChatView.vue          # 对话页
│   ├── views/KnowledgeBaseView.vue # 知识库管理
│   ├── views/LoginView.vue         # 登录
│   └── views/RegisterView.vue      # 注册
└── package.json

start.bat              # 一键启动
docker-compose.yml     # PostgreSQL + ChromaDB
```

## 💬 对话流程

```
1. prepare（非流式）：向量检索 → Rerank → 准备上下文
2. generate（真流式）：llm.astream() 逐 token 输出
3. 保存：用户消息 + AI 回答入库
```

## ⚙️ 配置

在 `backend/.env` 中设置（从 `.env.example` 复制）：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `MIMO_API_KEY` | *(空)* | **必填**，从 https://api.xiaomimimo.com/ 申请 |
| `MIMO_BASE_URL` | `https://api.xiaomimimo.com/v1` | MiMo API 端点 |
| `MIMO_MODEL` | `mimo-v2.5-pro` | 使用的模型 |
| `MIMO_LLM_TEMPERATURE` | `0.7` | 温度参数 |
| `OLLAMA_EMBED_MODEL` | `qwen3-embedding:0.6b` | Embedding 模型（本地） |
| `JWT_SECRET_KEY` | `change-me-...` | **生产必改** |
| `ADMIN_USERNAME` | `admin` | 默认管理员 |
| `DEBUG` | `false` | 调试模式 |

## License

MIT
