# 📚 RAG 知识库系统

模块化、可插拔的 RAG 知识库问答系统，支持多 LLM/Embedding/Retrieval/Rerank 策略，可视化对比与批量评估。

> **架构演进**：从 LangGraph → LCEL；新增 Strategy + Factory 模式；新增模型评估中心（LLM-as-Judge + RAGAS）。

## ✨ 核心功能

- **RAG 检索** — 向量 / BM25 / Rerank 策略可切换，中文优化分块
- **真实流式** — `llm.astream()` 逐 token 输出，非模拟
- **多轮对话** — 对话历史持久化，支持上下文继续提问
- **多知识库** — 用户私有 KB，按 owner_id 隔离，支持选 KB / 全库检索
- **多格式文档** — PDF、DOCX、TXT、MD、XLSX、PPTX、CSV、JSON、HTML
- **多 LLM** — MiMo（默认）/ DeepSeek / GLM（OpenAI 兼容协议）
- **多 Embedding** — Ollama / HuggingFace（本地离线） / SiliconFlow（云端）
- **多 Rerank** — HuggingFace CrossEncoder（本地） / SiliconFlow Qwen3-Reranker-4B
- **评估中心** — 一键对比不同模型/策略效果，含 RAGAS 6 维评估

## 🛠 技术栈

| 组件 | 技术 |
|------|------|
| 后端 | FastAPI + SQLAlchemy (async) + Alembic |
| LLM 编排 | **LangChain LCEL**（纯函数式 + 流式） |
| LLM 协议 | OpenAI 兼容（MiMo / DeepSeek / GLM） |
| Embedding | Ollama / HuggingFace（离线）/ SiliconFlow |
| Rerank | HuggingFace CrossEncoder / SiliconFlow |
| 向量库 | ChromaDB（本地持久化） |
| 评估 | RAGAS（可选）+ LLM-as-Judge（mimo-v2.5） |
| 前端 | Vue3 + Vite + Element Plus |
| 认证 | JWT + bcrypt |

## 🚀 快速开始

### 一键启动（Windows）

```bash
start.bat
```

### 手动启动

#### 1. 准备依赖服务

- **PostgreSQL**（端口 5432）：创建库和用户
- **Ollama**（端口 11434）：本地 embedding 服务
  ```bash
  ollama pull qwen3-embedding:0.6b
  ```
- **MiMo API Key**：到 https://api.xiaomimimo.com/ 申请

#### 2. 后端

```bash
cd backend
cp .env.example .env       # 填入 MIMO_API_KEY
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

#### 3. 前端

```bash
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
- 密码：`admin123456`（可在 `.env` 用 `ADMIN_USERNAME` / `ADMIN_PASSWORD` 修改）

## 📂 项目结构

```
backend/
├── app/
│   ├── api/                       # HTTP 路由
│   │   ├── auth.py                # 认证
│   │   ├── chat.py                # 流式对话
│   │   ├── documents.py           # 文档管理
│   │   ├── knowledge_base.py      # KB CRUD
│   │   ├── admin.py               # 管理员后台
│   │   ├── eval.py                # 评估 API
│   │   └── health.py              # 健康检查
│   ├── core/                      # 兼容层（安全/embedding/llm 入口）
│   ├── db/                        # SQLAlchemy 异步引擎
│   ├── middleware/                # 请求日志中间件
│   ├── models/                    # ORM 模型（含 eval_models）
│   ├── schemas/                   # Pydantic 模式
│   └── services/
│       ├── embedding/             # ★ Embedding 工厂（Ollama/HF/SiliconFlow）
│       ├── llm_provider/          # ★ LLM 工厂（MiMo/DeepSeek/GLM）
│       ├── chunking/              # ★ Chunking 工厂（fixed/recursive/semantic）
│       ├── retrieval/             # ★ Retrieval 工厂（vector/bm25/rerank/graph）
│       ├── rerank/                # ★ Rerank 工厂（HF CrossEncoder/SiliconFlow）
│       ├── eval/                  # ★ 评估系统
│       │   ├── judge.py           #   LLM-as-Judge（mimo-v2.5 固定）
│       │   ├── metrics.py         #   检索指标（hit/mrr/ndcg）
│       │   ├── dataset_builder.py #   自动生成 QA 数据集
│       │   ├── runner.py          #   断点续传 runner
│       │   ├── ragas_eval.py      #   RAGAS 6 维评估
│       │   └── report.py          #   JSON/MD 报告
│       ├── parser.py              # 9 格式文档解析
│       ├── retrieval_pipeline.py  # LCEL 检索管道
│       └── vectorstore.py         # ChromaDB 封装
├── alembic/                       # 数据库迁移
├── tests/
└── requirements.txt

frontend/
├── src/
│   ├── api/index.js               # 后端 API 封装
│   ├── router/index.js            # 路由（requiresAdmin 守卫）
│   ├── stores/user.js             # Pinia 用户状态
│   ├── views/
│   │   ├── ChatView.vue           # 对话
│   │   ├── KnowledgeBaseView.vue  # KB 管理
│   │   ├── EvaluationView.vue     # ★ 评估中心
│   │   ├── AdminView.vue          # 管理员后台
│   │   ├── LoginView.vue
│   │   └── RegisterView.vue
│   ├── App.vue
│   └── main.js
├── index.html
└── package.json

start.bat                  # 一键启动
newplan.md                 # 项目计划文档
```

## 🏭 模块化架构（Strategy + Factory）

每个能力点都有 `Provider` 抽象 + `Factory` 注册表 + 字符串 ID：

```python
# Embedding
from app.services.embedding import get_embedding_provider
emb = get_embedding_provider("qwen3-embedding:0.6b")  # OllamaProvider
emb = get_embedding_provider("shibing624/text2vec-base-chinese")  # HFProvider
emb = get_embedding_provider("Qwen/Qwen3-Embedding-8B")  # SiliconFlowProvider

# LLM
from app.services.llm_provider import get_llm_provider
llm = get_llm_provider("mimo-v2.5-pro")
llm = get_llm_provider("deepseek-v4-flash")
llm = get_llm_provider("GLM-4.5-flash")

# Chunking
from app.services.chunking import get_chunker
chunker = get_chunker("recursive", chunk_size=500, chunk_overlap=50)
chunker = get_chunker("semantic", embeddings=emb)
chunks = chunker.split(text)

# Rerank
from app.services.rerank import get_rerank_provider
rerank = get_rerank_provider("BAAI/bge-reranker-base")  # 本地
rerank = get_rerank_provider("Qwen/Qwen3-Reranker-4B")   # 云端
```

每个 KB 在数据库中保存策略选择，新建/上传时自动使用对应 Provider，无需改代码。

## 📊 评估中心

`/evaluation` 页面提供：

1. **新建评估**：选 KB → 选数据集（手动 / 自动生成 20 道）→ 勾选要对比的 Embedding / Retrieval / Rerank / LLM 组合
2. **断点续传**：每个 task 立即 commit，进程被杀后可恢复
3. **LLM-as-Judge**：每个 task 完成后用 mimo-v2.5 打 3 个分（faithfulness / relevance / completeness）
4. **RAGAS**（可选）：run 结束后批量跑 6 维评估
   - faithfulness（防幻觉）
   - answer_relevancy（答案相关度）
   - context_relevancy（上下文相关度）
   - context_recall（上下文召回率）
   - context_precision（上下文精度）
   - answer_correctness（答案正确性）
5. **报告导出**：JSON + Markdown，按 `eval_{name}_{YYYYMMDD_HHMMSS}_{id8}.{json|md}` 命名
6. **历史永久保留**：DB + `backend/reports/` 不清理

启用 RAGAS：在 `.env` 设 `USE_RAGAS=true`，或在 UI 创建评估时勾选。

## ⚙️ 配置

复制 `backend/.env.example` 为 `backend/.env` 后按需修改：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `MIMO_API_KEY` | *(空)* | **必填**，从 https://api.xiaomimimo.com/ 申请 |
| `MIMO_MODEL` | `mimo-v2.5-pro` | 默认生成模型 |
| `MIMO_LITE_MODEL` | `mimo-v2.5` | LLM-as-Judge 固定使用 |
| `DEEPSEEK_API_KEY` | *(空)* | 可选，启用 DeepSeek |
| `GLM_API_KEY` | *(空)* | 可选，启用 GLM |
| `OLLAMA_EMBED_MODEL` | `qwen3-embedding:0.6b` | 本地 embedding |
| `HF_CACHE_DIR` | `C:\Users\13596\.cache\huggingface\hub` | HF 模型统一缓存 |
| `HF_OFFLINE` | `1` | 1=强制离线（推荐），0=允许联网 |
| `SILICONFLOW_API_KEY` | *(空)* | 可选，启用云端 embedding/rerank |
| `JWT_SECRET_KEY` | `change-me-...` | **生产必改** |
| `USE_RAGAS` | `false` | 是否启用 RAGAS 评估 |
| `DEBUG` | `false` | 调试模式 |

## 💬 对话流程

```
1. 选 KB（可多选 / 全库）
2. 加载最近 10 条对话历史
3. 准备（非流式）：检索 → Rerank → 构造 context
4. 生成（真流式）：llm.astream() 逐 token 输出
5. 保存：用户消息 + AI 回答入库
```

## 🛡 权限

- 每个 KB 通过 `owner_id` 隔离，跨用户访问会被拒绝
- 管理员账号由 `ADMIN_USERNAME` / `ADMIN_PASSWORD` 配置
- `/admin/*` 和 `/evaluation` 路由需要 admin 权限（前端 `requiresAdmin` 守卫）
- JWT 认证，默认 24h 过期

## License

MIT
