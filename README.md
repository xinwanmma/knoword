# Knoword — RAG 知识库系统

> 基于 **LangChain 1.x + FastAPI + Vue 3** 的多知识库 RAG 系统，支持智能对话、检索增强生成、自动化评估。

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue)](https://www.python.org)
[![Vue](https://img.shields.io/badge/Vue-3.x-brightgreen)](https://vuejs.org)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

---

## ✨ 核心特性

- **多知识库管理**：每个 KB 独立配置 embedding / chunking / retrieval 策略
- **5 大可插拔 Strategy + Factory 模式**：LLM / Embedding / Rerank / Retrieval / Chunking
- **多 LLM 兼容**：MiMo（默认）/ DeepSeek / GLM 智谱，全部 OpenAI 兼容协议
- **多 Embedding 兼容**：Ollama（本地）/ HuggingFace（本地）/ SiliconFlow（云端）
- **Rerank 支持**：本地 BAAI CrossEncoder + 云端 Qwen3-Reranker
- **智能对话**：SSE 流式生成 + 多轮对话 + 参考资料溯源
- **评估中心**：8 个指标（5 检索 + 3 LLM），**支持断点续传 / 空状态补跑 / 跨 KB 复制数据集**
- **管理后台**：用户管理、KB 配额、操作日志

---

## 📊 评估指标（8 个，可独立开关）

| 类型 | 指标 | 含义 |
|------|------|------|
| 检索 | **Recall@K** | ground-truth chunks 在 top-K 中被找回的比例 |
| 检索 | **Precision@K** | top-K 中 ground-truth 占比 |
| 检索 | **Hit@K** | top-K 是否至少含一个 ground-truth |
| 检索 | **MRR** | 首个 ground-truth 的倒数排名 |
| 检索 | **NDCG@K** | 排序质量的综合指标 |
| LLM | **Faithfulness** | 答案是否由 retrieved contexts 推出（0-1）|
| LLM | **Answer Relevancy** | 答案是否直接回答了问题（0-1）|
| LLM | **Answer Correctness** | 0.5×F1 + 0.5×embedding cosine（0-1）|

> LLM 评估模型默认 `mimo-v2.5`，启动评估时可在 UI 切换。关闭指标后该指标不计入 summary / 报告。

---

## 🏗️ 技术栈

**后端**
- FastAPI · SQLAlchemy(async) · Alembic
- LangChain 1.x（ChatOpenAI + ChatPromptTemplate + RunnableParallel）
- ChromaDB（按 embedding 模型分库：`kb_emb_{name}`）
- rank_bm25

**前端**
- Vue 3 · Pinia · Vue Router · Element Plus · Vite

**AI**
- LLM：MiMo / DeepSeek / GLM
- Embedding：Ollama / HuggingFace / SiliconFlow
- Rerank：HuggingFace / SiliconFlow

---

## 📁 项目结构

```
knoword/
├── README.md                          # 本文件
├── start.py                           # 一键启动（带预检）
├── .gitignore
│
├── backend/
│   ├── .env.example                   # 环境变量模板
│   ├── requirements.txt
│   ├── alembic/                       # DB 迁移（9 个版本）
│   ├── app/
│   │   ├── main.py                    # FastAPI 入口
│   │   ├── config.py                  # Settings
│   │   ├── api/                       # 7 个 HTTP router
│   │   │   ├── auth.py                #   /api/auth
│   │   │   ├── chat.py                #   /api/chat
│   │   │   ├── documents.py           #   /api/documents
│   │   │   ├── knowledge_base.py      #   /api/knowledge-base
│   │   │   ├── eval.py                #   /api/eval
│   │   │   ├── admin.py               #   /api/admin/*
│   │   │   └── health.py              #   /api/system/health
│   │   ├── core/security.py           # JWT
│   │   ├── db/database.py             # SQLAlchemy session（自动适配 PG / SQLite）
│   │   ├── middleware/logging.py      # 访问日志
│   │   ├── models/                    # ORM
│   │   ├── schemas/                   # Pydantic
│   │   └── services/
│   │       ├── chunking/              # ★ Strategy + Factory
│   │       ├── embedding/             # ★ Provider + Factory
│   │       ├── llm_provider/          # ★ Provider + Factory
│   │       ├── rerank/                # ★ Provider + Factory
│   │       ├── retrieval/             # ★ Strategy + Factory
│   │       ├── eval/                  # 评估系统（runner/report/metrics/prompts）
│   │       ├── vectorstore.py         # ChromaDB 包装（按 embedding 分库）
│   │       ├── retrieval_pipeline.py  # 检索编排
│   │       ├── document_processor.py  # 文档入库
│   │       └── parser.py              # 多格式解析
│   ├── data/                          # 运行时（gitignore）
│   │   ├── uploads/
│   │   └── chromadb/                  # kb_emb_*/ 每个 embedding 一个目录
│   ├── reports/                       # 评估报告（gitignore，每个 run 1 .json + 1 .md）
│   ├── logs/                          # 评估 / LLM / 访问日志
│   ├── scripts/                       # 复用脚本（list_kb_and_datasets.py 等）
│   └── tests/
│
├── frontend/
│   ├── package.json
│   ├── vite.config.js
│   └── src/
│       ├── main.js · App.vue
│       ├── api/index.js               # axios 封装
│       ├── router/index.js            # 路由 + requiresAdmin 守卫
│       ├── stores/user.js             # Pinia 用户状态
│       ├── styles/global.css
│       └── views/                     # 6 个页面
│           ├── LoginView.vue
│           ├── RegisterView.vue
│           ├── ChatView.vue
│           ├── KnowledgeBaseView.vue
│           ├── AdminView.vue
│           └── EvaluationView.vue
│
└── docs/                              # 详细文档
    ├── README.md                      # 文档索引
    ├── ARCHITECTURE.md                # 系统架构
    ├── API.md                         # REST 接口
    ├── OPERATIONS.md                  # 运维 / 部署
    └── REFACTOR_PLAN.md               # 文档重构计划（ADR）
```

---

## 🚀 快速开始

### 1. 准备环境

- **Python 3.10+**
- **Node.js 18+**
- **PostgreSQL 14+**（默认端口 5432）
- **Ollama**（本地 embedding，可选；用云端 embedding 可不装）

### 2. 启动项目

```bash
# 克隆
git clone <repo-url>
cd knoword

# 一键预检 + 启动（推荐先 --check 只检查不启动）
python start.py --check
python start.py
```

`start.py` 会自动检查：
1. Python 版本
2. `.env` 是否就位
3. PostgreSQL / Ollama / MiMo API key 可达
4. 后端依赖 / 前端 node_modules

通过后会在新窗口里启动后端（:8000）和前端（:5173）。

### 3. 手动启动

如果 `start.py` 失败或要分别启动：

```bash
# 后端
cd backend
python -m venv venv
venv\Scripts\activate               # Windows
pip install -r requirements.txt
cp .env.example .env                # 填写 MIMO_API_KEY / JWT_SECRET_KEY / HF_CACHE_DIR
alembic upgrade head
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 前端
cd frontend
npm install
npm run dev
```

启动后访问：
- 前端：http://localhost:5173
- 后端 API：http://localhost:8000
- OpenAPI 文档：http://localhost:8000/docs

---

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

完整配置（含每项影响范围）见 [OPERATIONS.md#环境变量](docs/OPERATIONS.md)。

---

## 🧪 测试

```bash
cd backend
pytest tests/ -v
```

> 测试用 `sqlite+aiosqlite:///./test.db`（`tests/conftest.py` 自动设置）。`database.py` 按 URL 自动适配：SQLite 走 NullPool，PostgreSQL 走原连接池。

---

## 📈 评估中心使用

1. 创建 KB → 上传文档（自动分块 + embedding 入 ChromaDB）
2. 进入「评估中心」→ 创建数据集（自动从 KB 生成 QA 对，或导入）
3. 配置评估组合：`retrieval × rerank × generation`（笛卡尔积）
4. 启动评估，自动跑启用的指标
5. 报告输出到 `backend/reports/eval_{name}_{time}_{id}.{json|md}` 永久保留

**高级功能**：
- **断点续传**：评估中断后点「续跑」，自动跳过已完成 task
- **空状态补跑**：因 LLM 余额耗尽失败的 task，充值后点「续跑」自动补
- **跨 KB 复制数据集**：不同 embedding 的 KB 可共用同一份 QA（用 `backend/scripts/copy_dataset_to_other_kb.py`）
- **多 embedding 对比**：创建不同 KB 用不同 embedding，评估时多选 KB 自动产出对比报告

详细算法见 [docs/ARCHITECTURE.md#评估系统](docs/ARCHITECTURE.md)。

---

## 🛠️ 常见问题

<details>
<summary><b>Q: 启动报 "Collection expecting embedding with dimension of 1024, got 4096"</b></summary>

ChromaDB collection 与 embedding 模型维度不匹配。**新建 KB 时务必确认 embedding 模型**；切换 embedding 必须重新上传文档。详见 [OPERATIONS.md#ChromaDB 操作](docs/OPERATIONS.md#chromadb-操作)。
</details>

<details>
<summary><b>Q: 评估中途报 "402 Insufficient account balance"</b></summary>

LLM 余额耗尽。充值后点「续跑」即可继续。也可把 LLM judge 改为 deepseek 减少 mimo 用量。详见 [OPERATIONS.md#常见错误](docs/OPERATIONS.md#常见错误)。
</details>

<details>
<summary><b>Q: Vite HMR 改路由不生效</b></summary>

`router/index.js` 改动 Vite HMR 不可靠，需要 Ctrl+C 重启 `npm run dev`。
</details>

<details>
<summary><b>Q: HF 模型下载慢 / 失败</b></summary>

1. 设置 `HF_OFFLINE=0`（默认），确保有网络
2. 检查 `HF_CACHE_DIR` 路径存在且可写
3. 镜像：export `HF_ENDPOINT=https://hf-mirror.com`
</details>

更多 FAQ 见 [OPERATIONS.md#常见错误](docs/OPERATIONS.md#常见错误)。

---

## 📚 文档导航

| 文档 | 适合谁 | 内容 |
|------|--------|------|
| [README.md](README.md) | 所有用户 | 项目入口 |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 二次开发者 | 系统架构、5 大 Factory、关键流程、ADR |
| [docs/API.md](docs/API.md) | 前端 / 集成方 | 39 个 REST 端点 + 请求/响应示例 |
| [docs/OPERATIONS.md](docs/OPERATIONS.md) | 运维 / DBA | 部署、备份、迁移、监控、排查 SOP |

---

## 📝 License

MIT
