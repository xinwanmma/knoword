# 📚 RAG 知识库系统（多 Agent + 三层记忆）

基于 LangGraph 的多 Agent 智能知识库问答系统。支持 RAG 知识库检索、通用对话、三层记忆（Mem0 向量记忆 + Memary 知识图谱 + Store 会话状态），每个用户拥有独立的记忆空间。

## ✨ 功能特性

- **多 Agent 路由** — LangGraph Supervisor 自动判断意图，路由到 RAG Agent 或 General Agent
- **三层记忆系统**
  - 🧠 **Mem0** — 从对话中自动提取事实/偏好，向量语义搜索
  - 🔗 **Memary** — 知识图谱，实体关系网络，多跳推理
  - 💾 **Store** — 跨会话持久状态，用户偏好/进度/上下文
- **RAG 知识库** — 多格式文档上传、中文优化分块、语义检索
- **流式对话** — SSE 逐 token 打字机效果，引用来源先行渲染
- **引用来源追溯** — 每条回答附带原文出处、页码、相关度评分
- **每个用户独立记忆** — 所有记忆按 user_id 隔离

## 🛠 技术栈

| 组件 | 技术 |
|------|------|
| 后端 | FastAPI + SQLAlchemy (async) + Alembic |
| Agent 框架 | LangGraph (StateGraph + 条件路由) |
| LLM 调用 | LangChain-Ollama (ChatOllama) |
| 向量记忆 | Mem0 (自托管, ChromaDB) |
| 图谱记忆 | 知识图谱 (Neo4j) |
| 会话状态 | LangGraph Store (PostgreSQL JSONB) |
| 数据库 | PostgreSQL |
| 向量库 | ChromaDB |
| LLM | Ollama 本地 (qwen3.5:2b) |
| Embedding | Ollama 本地 (qwen3-embedding:0.6b) |
| 前端 | Vue3 + Vite + Element Plus |
| 认证 | JWT + bcrypt |

## 🚀 快速开始

### 前置条件

- Python 3.11+
- Node.js 18+
- PostgreSQL
- Ollama（已拉取模型）

### 1. 拉取 Ollama 模型

```bash
ollama pull qwen3.5:2b
ollama pull qwen3-embedding:0.6b
```

### 2. 准备数据库

```sql
CREATE USER rag_user WITH PASSWORD 'rag_password';
CREATE DATABASE rag_kb OWNER rag_user;
```

### 3. 启动 Docker 服务（PostgreSQL + ChromaDB + Neo4j）

```bash
docker-compose up -d
```

### 4. 配置环境变量

```bash
cd backend
copy .env.example .env
```

编辑 `.env`，修改数据库、Neo4j、管理员密码等配置。

### 5. 启动后端

```bash
cd backend
pip install -r requirements.txt
alembic revision --autogenerate -m "init"
alembic upgrade head
uvicorn app.main:app --reload --port 8080
```

### 6. 启动前端

```bash
cd frontend
npm install
npm run dev
```

### 7. 访问

- 前端：http://localhost:3000
- API 文档：http://localhost:8080/docs
- Neo4j Web UI：http://localhost:7474

## 📂 项目结构

```
.
├── backend/
│   ├── app/
│   │   ├── api/                    # 路由层
│   │   │   ├── auth.py             # 认证
│   │   │   ├── chat.py             # 对话（LangGraph + SSE）
│   │   │   ├── documents.py        # 文档管理
│   │   │   ├── graph_memory.py     # Memary 知识图谱
│   │   │   ├── health.py           # 健康检查
│   │   │   ├── knowledge_base.py   # 知识库 CRUD
│   │   │   ├── memory.py           # Mem0 记忆
│   │   │   └── store.py            # Store 状态
│   │   ├── core/
│   │   │   ├── embeddings.py       # LangChain Embeddings
│   │   │   ├── llm.py              # LangChain LLM
│   │   │   └── security.py         # JWT + 权限
│   │   ├── services/
│   │   │   ├── agent_graph.py      # ⭐ LangGraph 多 Agent 图
│   │   │   ├── chunker.py          # 中文优化分块
│   │   │   ├── document_processor.py
│   │   │   ├── graph_memory.py     # Memary 知识图谱服务
│   │   │   ├── memory_service.py   # Mem0 向量记忆服务
│   │   │   ├── ollama_service.py   # Ollama 原生调用
│   │   │   ├── parser.py           # 9 格式文档解析
│   │   │   ├── store_service.py    # Store 状态服务
│   │   │   └── vectorstore.py      # ChromaDB
│   │   ├── config.py
│   │   └── main.py
│   └── alembic/
├── frontend/
│   ├── src/
│   │   ├── api/                    # API 层（含记忆 API）
│   │   ├── components/
│   │   │   └── MemoryPanel.vue     # ⭐ 三 Tab 记忆面板
│   │   ├── views/
│   │   │   ├── ChatView.vue        # 对话页（Agent 标签）
│   │   │   └── ...
│   │   ├── App.vue
│   │   └── main.js
│   └── package.json
├── docker-compose.yml              # PG + ChromaDB + Neo4j
└── plan.md
```

## 🧠 记忆系统架构

```
用户消息
  ↓
1. Store.load()     → 加载用户偏好/进度
2. Mem0.search()    → 搜索事实记忆
3. Memary.search()  → 搜索知识图谱
  ↓
4. Supervisor → 路由到 Agent
  ↓
5. Agent 生成回答（注入三层记忆）
  ↓
6. 后处理写入：
   - Mem0.add()    → 提取事实
   - Memary.add()  → 更新图谱
   - Store.save()  → 保存状态
```

| 记忆层 | 技术 | 存储 | 用途 |
|--------|------|------|------|
| Mem0 | mem0ai | ChromaDB | 事实/偏好语义搜索 |
| Memary | Neo4j | 知识图谱 | 实体关系、多跳推理 |
| Store | PostgreSQL | JSONB | 跨会话状态 |
| 短时记忆 | PostgreSQL | Message 表 | 当前会话历史 |

## ⚙️ 配置说明

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama 地址 |
| `OLLAMA_LLM_MODEL` | `qwen3.5:2b` | 对话模型 |
| `OLLAMA_EMBED_MODEL` | `qwen3-embedding:0.6b` | 向量模型 |
| `MEM0_ENABLED` | `true` | 启用 Mem0 记忆 |
| `MEMARY_ENABLED` | `true` | 启用 Memary 知识图谱 |
| `NEO4J_URL` | `bolt://localhost:7687` | Neo4j 地址 |
| `NEO4J_PW` | `password` | Neo4j 密码 |
| `STORE_ENABLED` | `true` | 启用 Store 状态 |
| `CHUNK_TARGET_TOKENS` | `300` | 目标分块大小 |
| `ADMIN_USERNAME` | `admin` | 管理员用户名 |
| `ADMIN_PASSWORD` | `admin123456` | 管理员密码 |

## 📡 API 接口一览

### 认证
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/auth/register` | 注册 |
| POST | `/api/auth/login` | 登录 |
| GET | `/api/auth/me` | 当前用户 |

### 对话
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/chat` | 发送消息（SSE 流式） |
| GET | `/api/chat/history` | 会话列表 |
| GET | `/api/chat/history/{id}` | 消息详情 |
| DELETE | `/api/chat/history/{id}` | 删除对话 |

### 知识库
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/kb` | 创建知识库 |
| GET | `/api/kb` | 列出知识库 |
| POST | `/api/documents/upload?kb_id=1` | 上传文档 |
| POST | `/api/documents/{id}/reindex` | 重新向量化 |

### 记忆系统
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/memory` | Mem0 事实记忆列表 |
| GET | `/api/memory/search?q=xxx` | 搜索事实记忆 |
| DELETE | `/api/memory/{id}` | 删除记忆 |
| GET | `/api/graph/entities` | 知识图谱实体 |
| GET | `/api/graph/search?q=xxx` | 图谱搜索 |
| GET | `/api/graph/timeline` | 实体时间线 |
| GET | `/api/store` | 会话状态列表 |
| PUT | `/api/store` | 更新状态 |
| DELETE | `/api/store/{key}` | 删除状态 |

## License

MIT
