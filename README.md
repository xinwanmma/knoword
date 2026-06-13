# 📚 RAG 知识库系统

基于 LangGraph 多 Agent + Checkpointer + Store 的智能知识库问答系统。

## ✨ 功能

- **多 Agent 路由** — LangGraph Supervisor 自动判断意图，路由到 RAG 或 General Agent
- **真实流式** — llm.astream() 逐 token 输出，非模拟
- **Checkpointer** — LangGraph 状态持久化，对话断点续传
- **Store** — PostgreSQL JSONB 键值存储：
  - 用户画像自动提取（AI 主动记住你的偏好）
  - 问答缓存（相似问题毫秒级返回）
  - 文档权限过滤（企业级多租户 RAG）
- **RAG 检索** — Hybrid Search（BM25 + 向量）+ Reranking + 中文优化分块
- **流式对话** — SSE 逐 token 输出，引用来源先行渲染，进度指示器

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
│   │   ├── chat.py             # 对话（LangGraph + 真实流式）
│   │   ├── chunk_config.py     # 分块策略预览
│   │   ├── documents.py        # 文档管理
│   │   ├── health.py           # 健康检查
│   │   ├── knowledge_base.py   # 知识库 CRUD
│   │   └── store.py            # Store 状态接口
│   ├── core/
│   │   ├── embeddings.py       # OllamaEmbeddings
│   │   ├── llm.py              # ChatOllama
│   │   └── security.py         # JWT + 权限
│   ├── middleware/
│   │   └── logging.py          # 请求日志
│   ├── models/
│   │   └── models.py           # ORM 模型
│   ├── schemas/
│   │   └── schemas.py          # Pydantic 模式
│   ├── services/
│   │   ├── agent_graph.py      # ⭐ LangGraph Agent 图
│   │   ├── chunker.py          # 中文优化分块
│   │   ├── chunk_config.py     # 分块策略配置
│   │   ├── checkpoint_service.py  # Checkpointer
│   │   ├── document_processor.py  # 文档处理管道
│   │   ├── hybrid_search.py    # BM25 + 向量混合检索
│   │   ├── memory_service.py   # (已移除)
│   │   ├── graph_memory.py     # (已移除)
│   │   ├── ollama_service.py   # Ollama 原生调用
│   │   ├── parser.py           # 9 格式文档解析
│   │   ├── reranker.py         # Reranking
│   │   ├── store_service.py    # Store 服务
│   │   └── vectorstore.py      # ChromaDB
│   ├── config.py
│   └── main.py
├── tests/
├── alembic/
└── requirements.txt

frontend/
├── src/
│   ├── api/index.js
│   ├── components/MemoryPanel.vue  # Store 管理面板
│   ├── views/ChatView.vue          # 对话页
│   ├── views/KnowledgeBaseView.vue # 知识库管理
│   ├── views/AdminView.vue         # 管理员面板
│   ├── views/StatusView.vue        # 系统状态
│   ├── views/LoginView.vue         # 登录
│   └── views/RegisterView.vue      # 注册
└── package.json

start.bat              # 一键启动
docker-compose.yml     # PostgreSQL + ChromaDB
```

## 🧠 记忆系统

```
对话流程：
1. prepare（非流式）：加载 Store → 检查缓存 → Supervisor 路由 → 检索文档
2. generate（真流式）：llm.astream() 逐 token 输出
3. postprocess（异步）：保存缓存 + 自动提取用户偏好
```

### Store 功能

| 功能 | 说明 | 存储位置 |
|------|------|---------|
| 用户画像 | AI 自动提取对话中的偏好 | `profile_*` 键 |
| 问答缓存 | 相似问题直接返回缓存 | `cache_*` 键 |
| 权限过滤 | 用户有权限的知识库列表 | `permissions` 键 |
| 自定义状态 | 用户手动设置的偏好 | 任意键 |

### Store API

```bash
# 保存
curl -X PUT http://localhost:8000/api/store \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"key":"language","value":"中文"}'

# 读取
curl http://localhost:8000/api/store/language -H "Authorization: Bearer $TOKEN"

# 列出
curl http://localhost:8000/api/store -H "Authorization: Bearer $TOKEN"
```

## ⚙️ 配置

在 `backend/.env` 中设置：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `OLLAMA_LLM_MODEL` | `qwen3.5:2b` | 对话模型 |
| `OLLAMA_EMBED_MODEL` | `qwen3-embedding:0.6b` | 向量模型 |
| `STORE_ENABLED` | `true` | 启用 Store |
| `STORE_CACHE_TTL_DAYS` | `30` | 缓存过期天数 |
| `STORE_CACHE_SIMILARITY_THRESHOLD` | `0.9` | 缓存相似度阈值 |
| `STORE_AUTO_EXTRACT` | `true` | 自动提取用户偏好 |
| `CHUNK_TARGET_TOKENS` | `300` | 目标分块大小 |
| `DEBUG` | `false` | 调试模式 |

## License

MIT
