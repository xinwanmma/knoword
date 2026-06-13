# 📚 RAG 知识库系统

基于 LangGraph 多 Agent + Checkpointer + Store 的智能知识库问答系统。

## ✨ 功能

- **多 Agent 路由** — LangGraph Supervisor 自动判断意图，路由到 RAG 或 General Agent
- **Checkpointer** — LangGraph 状态持久化，对话断点续传
- **Store** — PostgreSQL JSONB 键值存储，保存用户偏好/进度/自定义状态
- **RAG 检索** — Hybrid Search（BM25 + 向量）+ Reranking + 中文优化分块
- **流式对话** — SSE 逐 token 输出，引用来源先行渲染

## 🛠 技术栈

| 组件 | 技术 |
|------|------|
| 后端 | FastAPI + SQLAlchemy (async) + Alembic |
| Agent | LangGraph StateGraph + 条件路由 |
| LLM | Ollama 本地 (qwen3.5:2b) + LangChain-Ollama |
| 向量库 | ChromaDB |
| 记忆 | Checkpointer (MemorySaver) + Store (PostgreSQL JSONB) |
| 前端 | Vue3 + Vite + Element Plus |
| 认证 | JWT + bcrypt |

## 🚀 快速开始

### 一键启动（Windows）

```bash
start.bat
```

自动检查环境 → 安装依赖 → 启动后端(:8000) + 前端(:3000)

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
- 密码：`000`

## 📂 项目结构

```
backend/
├── app/
│   ├── api/
│   │   ├── auth.py             # 认证
│   │   ├── chat.py             # 对话（LangGraph + SSE）
│   │   ├── chunk_config.py     # 分块策略预览
│   │   ├── documents.py        # 文档管理
│   │   ├── health.py           # 健康检查
│   │   ├── knowledge_base.py   # 知识库 CRUD
│   │   └── store.py            # Store 状态接口
│   ├── core/
│   │   ├── embeddings.py       # OllamaEmbeddings
│   │   ├── llm.py              # ChatOllama
│   │   └── security.py         # JWT + 权限
│   ├── services/
│   │   ├── agent_graph.py      # ⭐ LangGraph 多 Agent 图
│   │   ├── chunker.py          # 中文优化分块
│   │   ├── checkpoint_service.py  # Checkpointer
│   │   ├── hybrid_search.py    # BM25 + 向量混合检索
│   │   ├── reranker.py         # Reranking
│   │   ├── store_service.py    # Store 服务
│   │   └── vectorstore.py      # ChromaDB
│   ├── config.py
│   └── main.py
├── tests/
└── requirements.txt

frontend/
├── src/
│   ├── api/index.js
│   ├── components/MemoryPanel.vue  # Store 管理面板
│   ├── views/ChatView.vue          # 对话页
│   └── views/KnowledgeBaseView.vue # 知识库管理
└── package.json

start.bat              # 一键启动
docker-compose.yml     # PostgreSQL + ChromaDB
```

## ⚙️ 配置

在 `backend/.env` 中设置：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `OLLAMA_LLM_MODEL` | `qwen3.5:2b` | 对话模型 |
| `OLLAMA_EMBED_MODEL` | `qwen3-embedding:0.6b` | 向量模型 |
| `STORE_ENABLED` | `true` | 启用 Store 状态 |
| `CHUNK_TARGET_TOKENS` | `300` | 目标分块大小 |
| `ADMIN_USERNAME` | `admin` | 管理员用户名 |
| `ADMIN_PASSWORD` | `000` | 管理员密码（必须修改） |
| `DEBUG` | `false` | 调试模式 |

## License

MIT
