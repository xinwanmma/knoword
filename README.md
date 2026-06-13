# 📚 RAG 知识库系统

基于 LangGraph 多 Agent + 三层记忆的智能知识库问答系统。

## ✨ 功能

- **多 Agent 路由** — LangGraph Supervisor 自动判断意图，路由到 RAG 或 General Agent
- **三层记忆** — Mem0（向量事实）+ Memary（知识图谱）+ Store（会话状态）
- **RAG 检索** — Hybrid Search（BM25 + 向量）+ Reranking + 中文优化分块
- **流式对话** — SSE 逐 token 输出，引用来源先行渲染
- **每用户独立记忆** — 所有记忆按 user_id 完全隔离

## 🛠 技术栈

| 组件 | 技术 |
|------|------|
| 后端 | FastAPI + SQLAlchemy (async) + Alembic |
| Agent | LangGraph StateGraph + 条件路由 |
| LLM | Ollama 本地 (qwen3.5:2b) + LangChain-Ollama |
| 记忆 | Mem0 (ChromaDB) + Neo4j 知识图谱 + PostgreSQL JSONB |
| 向量库 | ChromaDB |
| 前端 | Vue3 + Vite + Element Plus |
| 认证 | JWT + bcrypt |

## 🚀 快速开始

### 环境要求

- Python 3.11+
- Node.js 18+
- PostgreSQL
- Ollama

### 一键启动（Windows）

```bash
# 双击运行
start.bat
```

自动检查环境 → 安装依赖 → 启动后端(:8000) + 前端(:3000)

### 手动启动

```bash
# 1. Ollama 模型
ollama pull qwen3.5:2b
ollama pull qwen3-embedding:0.6b

# 2. PostgreSQL
CREATE USER rag_user WITH PASSWORD 'rag_password';
CREATE DATABASE rag_kb OWNER rag_user;

# 3. Neo4j（可选，知识图谱功能需要）
# 安装 Neo4j Desktop: https://neo4j.com/download/
# 创建数据库，密码设为 password

# 4. 后端
cd backend
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload --port 8000

# 5. 前端
cd frontend
npm install
npm run dev
```

### 访问地址

| 服务 | 地址 |
|------|------|
| 前端 | http://localhost:3000 |
| API 文档 | http://localhost:8000/docs |
| Neo4j | http://localhost:7474 |

### 默认管理员

- 用户名：`admin`
- 密码：`000`（在 .env 中配置，**生产环境请修改**）

## 📂 项目结构

```
backend/
├── app/
│   ├── api/                    # 路由
│   │   ├── auth.py             # 认证（注册/登录/管理员）
│   │   ├── chat.py             # 对话（LangGraph + SSE 流式）
│   │   ├── chunk_config.py     # 分块策略预览/对比
│   │   ├── documents.py        # 文档管理（上传/删除/reindex）
│   │   ├── graph_memory.py     # Memary 知识图谱接口
│   │   ├── health.py           # 健康检查
│   │   ├── knowledge_base.py   # 知识库 CRUD + 分类
│   │   ├── memory.py           # Mem0 记忆接口
│   │   └── store.py            # Store 状态接口
│   ├── core/
│   │   ├── embeddings.py       # OllamaEmbeddings 封装
│   │   ├── llm.py              # ChatOllama 封装
│   │   └── security.py         # JWT + bcrypt + 权限
│   ├── db/
│   │   └── database.py         # SQLAlchemy async 引擎
│   ├── middleware/
│   │   └── logging.py          # 请求日志中间件
│   ├── models/
│   │   └── models.py           # 7 张表（User/Category/KB/Doc/Conv/Msg/Store）
│   ├── schemas/
│   │   └── schemas.py          # Pydantic 请求/响应模式
│   ├── services/
│   │   ├── agent_graph.py      # ⭐ LangGraph 多 Agent 图
│   │   ├── chunker.py          # 中文优化分块（tiktoken）
│   │   ├── chunk_config.py     # 分块策略配置
│   │   ├── checkpoint_service.py  # MemorySaver checkpointer
│   │   ├── document_processor.py  # 文档处理管道
│   │   ├── graph_memory.py     # Memary 知识图谱（Neo4j）
│   │   ├── hybrid_search.py    # BM25 + 向量混合检索
│   │   ├── memory_service.py   # Mem0 向量记忆
│   │   ├── ollama_service.py   # Ollama 原生 HTTP 调用
│   │   ├── parser.py           # 9 格式文档解析
│   │   ├── reranker.py         # Reranking 重排序
│   │   ├── store_service.py    # Store 状态服务
│   │   └── vectorstore.py      # ChromaDB 集成
│   ├── config.py
│   └── main.py
├── alembic/
├── tests/
├── .env.example
└── requirements.txt

frontend/
├── src/
│   ├── api/index.js            # API 层 + SSE 流式
│   ├── components/
│   │   └── MemoryPanel.vue     # 三 Tab 记忆面板
│   ├── views/
│   │   ├── ChatView.vue        # 对话（Agent 标签 + 流式）
│   │   ├── KnowledgeBaseView.vue  # 知识库管理
│   │   ├── AdminView.vue       # 管理员面板
│   │   ├── StatusView.vue      # 系统状态
│   │   ├── LoginView.vue       # 登录
│   │   └── RegisterView.vue    # 注册
│   ├── router/index.js
│   ├── stores/user.js
│   └── styles/global.css
├── package.json
└── vite.config.js

start.bat              # 一键启动
docker-compose.yml     # PostgreSQL + Neo4j
```

## 🧠 记忆系统架构

```
用户消息 → Supervisor（LangGraph）
              ├── 🟢 RAG Agent（知识库检索 + 记忆）
              └── 🔵 General Agent（通用对话 + 记忆）
                      ↓
              三层记忆并行读写：
              ├── 🧠 Mem0 → ChromaDB（事实/偏好语义记忆）
              ├── 🔗 Memary → Neo4j（实体关系图谱）
              └── 💾 Store → PostgreSQL JSONB（跨会话状态）
```

| 记忆层 | 技术 | 存储 | 用途 |
|--------|------|------|------|
| Mem0 | mem0ai | ChromaDB | 事实/偏好语义搜索 |
| Memary | Neo4j | 知识图谱 | 实体关系、多跳推理 |
| Store | PostgreSQL | JSONB | 跨会话状态 |

## 📡 API 接口

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

### 记忆
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/memory` | Mem0 事实记忆 |
| GET | `/api/graph/entities` | 知识图谱实体 |
| GET | `/api/store` | 会话状态 |

### 分块策略
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/chunks/preview` | 预览分块效果 |
| POST | `/api/chunks/compare` | 对比不同策略 |

### 系统
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查 |
| GET | `/api/categories` | 分类列表 |

## ⚙️ 配置

所有配置在 `backend/.env` 中设置（从 `.env.example` 复制）：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `OLLAMA_LLM_MODEL` | `qwen3.5:2b` | 对话模型 |
| `OLLAMA_EMBED_MODEL` | `qwen3-embedding:0.6b` | 向量模型 |
| `MEM0_ENABLED` | `true` | 启用 Mem0 记忆 |
| `MEMARY_ENABLED` | `true` | 启用知识图谱 |
| `NEO4J_URL` | `bolt://localhost:7687` | Neo4j 地址 |
| `STORE_ENABLED` | `true` | 启用 Store 状态 |
| `CHUNK_TARGET_TOKENS` | `300` | 目标分块大小 |
| `ADMIN_USERNAME` | `admin` | 管理员用户名 |
| `ADMIN_PASSWORD` | `000` | 管理员密码（必须修改） |
| `DEBUG` | `false` | 调试模式 |

## License

MIT
