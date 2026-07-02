# RAG 知识库系统

一个基于 **LangChain + FastAPI + Vue3** 的 RAG 知识库系统，支持多知识库管理、智能对话、评估中心。

## ✨ 核心特性

- **多知识库管理**：每个 KB 独立配置 embedding / chunking / retrieval 策略
- **策略可插拔**：5 类 Strategy + Factory（embedding / llm / rerank / retrieval / chunking）
- **智能对话**：SSE 流式生成 + 多轮对话 + 参考资料溯源
- **评估中心**：每次评估默认跑 **8 个指标**（5 检索 + 3 LLM），基于 LangChain
- **Rerank 支持**：本地 HF CrossEncoder + 云端 SiliconFlow API
- **管理后台**：用户管理、KB 配额、操作日志

## 📊 评估指标（8 个，可手动开关，默认全开）

| 类型 | 指标 | 说明 |
|------|------|------|
| 检索 | **Recall@K** | 所有相关文档里，前 K 个找回了多少比例 |
| 检索 | **Precision@K** | 前 K 个结果里，相关文档的比例 |
| 检索 | **Hit@K** | 前 K 个里有没有至少一个相关文档 |
| 检索 | **MRR** | 第一个正确答案的倒数排名 |
| 检索 | **NDCG@K** | 考虑排序质量的综合指标 |
| LLM | **Faithfulness / Groundedness** | 答案是否由 retrieved contexts 推出 |
| LLM | **Answer Relevancy** | 答案是否直接回答了问题 |
| LLM | **Answer Correctness** | 0.5×F1 + 0.5×embedding cos sim |

> 8 个指标可独立开关；默认全开，关闭后该指标不计入 summary / 报告。
> LLM 评估模型默认 `settings.MIMO_MODEL`（即 `mimo-v2.5-pro`），UI 启动时可改为 `mimo-v2.5` / 其它（手输任意模型名）。

## 🏗️ 技术栈

**后端**
- FastAPI + SQLAlchemy(async) + Alembic
- LangChain 1.x（核心架构：ChatOpenAI + ChatPromptTemplate + RunnableParallel）
- ChromaDB（本地持久化向量库）
- rank_bm25（BM25 检索）

**前端**
- Vue 3 + Pinia + Vue Router
- Element Plus
- Vite

**AI / ML**
- MiMo LLM（小米，默认生成模型）
- DeepSeek / GLM 智谱（可选）
- Ollama（本地 embedding，推荐）
- HuggingFace（本地 embedding + rerank）

## 📁 项目结构

```
d:\HHHUBS\clone\knoword\
├── README.md
├── start.py                       # 一键启动（后端 + 前端）
├── .gitignore
│
├── backend/
│   ├── .env.example               # 环境变量模板
│   ├── requirements.txt
│   ├── alembic/                   # DB 迁移
│   ├── app/
│   │   ├── main.py                # FastAPI 入口
│   │   ├── config.py              # Settings
│   │   ├── api/                   # HTTP 路由
│   │   │   ├── auth.py
│   │   │   ├── chat.py
│   │   │   ├── documents.py
│   │   │   ├── knowledge_base.py
│   │   │   ├── admin.py
│   │   │   ├── eval.py
│   │   │   └── health.py
│   │   ├── core/security.py       # JWT 认证
│   │   ├── db/database.py         # SQLAlchemy session
│   │   ├── models/                # ORM 模型
│   │   ├── schemas/               # Pydantic schemas
│   │   └── services/
│   │       ├── chunking/          # ★ Chunking Strategy + Factory
│   │       ├── embedding/         # ★ Embedding Provider + Factory
│   │       ├── llm_provider/      # ★ LLM Provider + Factory
│   │       ├── rerank/            # ★ Rerank Provider + Factory
│   │       ├── retrieval/         # ★ Retrieval Strategy + Factory
│   │       ├── eval/              # ★ 评估系统
│   │       ├── parser.py
│   │       ├── document_processor.py
│   │       ├── retrieval_pipeline.py
│   │       └── vectorstore.py
│   ├── data/                      # 运行时数据（gitignore）
│   │   ├── uploads/
│   │   └── chromadb/
│   ├── reports/                   # 评估报告（gitignore）
│   ├── tests/
│   │   └── test_auth.py
│   └── migrate_eval_data.py       # 一次性数据迁移脚本
│
└── frontend/
    ├── package.json
    ├── vite.config.js
    ├── index.html
    └── src/
        ├── main.js
        ├── App.vue
        ├── api/index.js
        ├── router/index.js
        ├── stores/user.js
        ├── styles/global.css
        └── views/
            ├── LoginView.vue
            ├── RegisterView.vue
            ├── ChatView.vue
            ├── KnowledgeBaseView.vue
            ├── AdminView.vue
            └── EvaluationView.vue
```

## 🚀 快速开始

### 1. 启动后端

```bash
# 准备环境
cd backend
python -m venv venv
venv\Scripts\activate            # Windows
pip install -r requirements.txt

# 配置环境变量
copy .env.example .env           # Windows
# 编辑 .env 填入 MIMO_API_KEY、JWT_SECRET_KEY、HF_CACHE_DIR

# 初始化数据库
alembic upgrade head

# 启动后端
python start.py                  # 或 uvicorn app.main:app --reload
```

后端默认运行在 `http://localhost:8000`，API 文档在 `http://localhost:8000/docs`。

### 2. 启动前端

```bash
cd frontend
npm install
npm run dev
```

前端默认运行在 `http://localhost:5173`。

### 3. 一键启动（项目根目录）

```bash
# 在 d:\HHHUBS\clone\knoword\ 目录下
python start.py
```

## 🔑 必填环境变量

| 变量 | 必填 | 说明 |
|------|------|------|
| `MIMO_API_KEY` | ✅ | 小米 MiMo LLM（默认生成模型）|
| `JWT_SECRET_KEY` | ✅ | JWT 签名密钥（生产必改）|
| `ADMIN_PASSWORD` | ✅ | 默认管理员密码（首次启动创建）|
| `HF_CACHE_DIR` | ✅ | HF 模型本地缓存目录 |
| `DEEPSEEK_API_KEY` | ❌ | DeepSeek（可选）|
| `GLM_API_KEY` | ❌ | GLM 智谱（可选）|
| `SILICONFLOW_API_KEY` | ❌ | SiliconFlow 云端 embedding/rerank（可选）|

完整配置见 `backend/.env.example`。

## 🧪 测试

```bash
cd backend
pytest tests/test_auth.py -v
```

> 测试用 `sqlite+aiosqlite:///./test.db`（由 `tests/conftest.py` 自动设置），`database.py` 会按 URL 自动选择引擎配置（SQLite 走 NullPool，不接 pool_size 等 PG 专用参数）。生产 PostgreSQL 走原连接池配置。

## 📈 评估中心使用

1. 进入「评估中心」→ 创建数据集（自动从 KB 生成 QA 对，或手动导入）
2. 配置评估组合：`retrieval × rerank × generation`（笛卡尔积）
3. （可选）勾选/取消评估指标，配置 LLM 评估模型 — 默认全开 8 个 + `mimo-v2.5`
4. 启动评估，自动跑启用的指标
5. 查看报告（`backend/reports/eval_*.json` + `*.md`）

> KB 由数据集创建时绑定，评估时强制使用 KB 上传文档时的 embedding（KB 创建时锁定）。
> 不支持多 embedding 模型对比（ChromaDB 共享 collection，维度锁死）。

详细算法见 `backend/app/services/eval/metrics.py`（检索）和 `llm_metrics.py`（LLM）。

## 📝 License

MIT
