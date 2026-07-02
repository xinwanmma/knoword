# Knoword 系统架构

> 适合：新加入的开发者、二次开发、要做技术决策时
> 配套：[README.md](../README.md)（项目入口）· [API.md](./API.md) · [OPERATIONS.md](./OPERATIONS.md)

---

## 1. 系统总览

```
┌────────────────────────────────────────────────────────────────────┐
│                          Browser (User)                            │
└─────────────────────────────┬──────────────────────────────────────┘
                              │ HTTPS / SSE
┌─────────────────────────────▼──────────────────────────────────────┐
│              Frontend (Vue 3 + Element Plus + Pinia)               │
│   LoginView · ChatView · KnowledgeBaseView · EvaluationView · Admin│
└─────────────────────────────┬──────────────────────────────────────┘
                              │ REST + SSE
┌─────────────────────────────▼──────────────────────────────────────┐
│                    FastAPI (backend/app/main.py)                   │
│                                                                    │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌─────────┐ │
│  │ /auth    │ │ /chat    │ │ /kb      │ │ /doc     │ │ /eval   │ │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └─────────┘ │
│  ┌──────────┐ ┌──────────┐                                        │
│  │ /admin/* │ │ /system  │                                        │
│  └──────────┘ └──────────┘                                        │
└────┬──────────────────┬──────────────────┬───────────────────────┬─┘
     │                  │                  │                       │
     ▼                  ▼                  ▼                       ▼
┌──────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────────┐
│PostgreSQL│    │   ChromaDB   │    │  LLM Provider│    │  Embedding/Rerank│
│  + SQLAl-│    │  (per-KB     │    │  MiMo/       │    │  Ollama / HF /   │
│  chemy + │    │  collection) │    │  DeepSeek/   │    │  SiliconFlow     │
│ Alembic  │    │  kb_emb_*    │    │  GLM         │    │                  │
└──────────┘    └──────────────┘    └──────────────┘    └──────────────────┘
```

---

## 2. 后端模块结构（5 大 Factory）

所有第三方能力都走 **Strategy + Factory** 模式，加新实现 = 改 1 个文件 + 1 行注册。

| 模块 | Factory 文件 | 注册的 Provider / Strategy |
|------|-------------|---------------------------|
| **LLM Provider** | `services/llm_provider/factory.py` | `MiMoProvider` / `DeepSeekProvider` / `GLMProvider`（extends `OpenAICompatibleProvider`）|
| **Embedding** | `services/embedding/factory.py` | `OllamaEmbedding` / `HFEmbedding` / `SiliconFlowEmbedding` |
| **Rerank** | `services/rerank/factory.py` | `BGERerankLocal` / `QwenRerankSiliconFlow` |
| **Retrieval** | `services/retrieval/factory.py` | `VectorRetrieval` / `BM25Retrieval` / `HybridRetrieval` / `RerankRetrieval` |
| **Chunking** | `services/chunking/factory.py` | `RecursiveChunker` / `SemanticChunker` / `FixedChunker` |

### 2.1 LLM Provider 设计

```
LLMProvider (base.py, abstract)
    │
    ├── OpenAICompatibleProvider (openai_compatible.py)
    │       implements _model, _base_url, _api_key, get_chat_model()
    │       │
    │       ├── MiMoProvider       (MiMo = 小米)
    │       ├── DeepSeekProvider   (DeepSeek)
    │       └── GLMProvider        (智谱 GLM-4)
    │
    └── (未来可加) AnthropicCompatibleProvider
```

调用链路：
```python
# 1. 业务代码
from app.services.llm_provider import get_llm_provider
provider = get_llm_provider("mimo-v2.5")
chat = provider.get_chat_model(temperature=0.5)
response = await chat.ainvoke([...])

# 2. factory 根据 model_id 选 Provider
#    "mimo-*" → MiMoProvider
#    "deepseek-*" → DeepSeekProvider
#    "GLM-*" → GLMProvider
```

### 2.2 Retrieval 设计

**4 种 Strategy 可独立或组合使用**：

| Strategy | 流程 | 适用场景 |
|----------|------|---------|
| `VectorRetrieval` | query → embedding → ChromaDB top-K | 大多数 RAG 场景的 baseline |
| `BM25Retrieval` | query → 关键词 → rank_bm25 top-K | 强关键词 / 术语场景 |
| `HybridRetrieval` | vector + BM25 加权融合 (alpha=0.5) | 想取两者之长 |
| `RerankRetrieval` | vector top-N → rerank → top-K | **对精度要求高的场景** |

代码层面：
```python
# 业务调用
retriever = get_retriever("rerank", kb_id=6, rerank_model="Qwen/Qwen3-Reranker-4B")
chunks = await retriever.retrieve(query, top_k=10, top_n_vec=20)
```

### 2.3 ChromaDB 按 Embedding 模型分库

**问题**：不同 embedding 模型维度不同（Qwen 0.6B=1024, Qwen 8B=4096, bge-base=768），**一个 collection 不能混维度**。

**解决**：每个 KB 创建独立 collection，命名规则 `kb_emb_{safe_model_name}`：

```
backend/data/chromadb/
├── kb_emb_qwen3_embedding_0_6b/
│   └── chroma.sqlite3 + 索引
├── kb_emb_qwen3_embedding_8b/
│   └── chroma.sqlite3
└── kb_emb_bge_base_zh_v1_5/
    └── chroma.sqlite3
```

切换 embedding = 新建 KB，**不能直接改**。代码层面在 `vectorstore.py` 提供 `get_or_create_collection(kb_id, embedding_model)`。

---

## 3. 数据模型

### 3.1 关键表

```
users
├── id (UUID)
├── username (unique)
├── password_hash
├── email
├── is_admin (boolean)
├── is_active (boolean)
└── created_at

knowledge_bases
├── id (int)
├── owner_id → users.id
├── name
├── description
├── embedding_model (str)           # 例: "Qwen/Qwen3-Embedding-8B"
├── chunking_strategy (str)         # 例: "recursive"
├── chunk_size (int)
├── chunk_overlap (int)
├── retrieval_strategy (str)        # 例: "hybrid"
└── created_at

documents
├── id (int)
├── kb_id → knowledge_bases.id
├── owner_id → users.id
├── filename
├── file_path
├── file_size
├── file_type
├── status (pending/processing/ready/failed)
├── chunk_count
└── indexed_at

chunks (在 ChromaDB，不在 PostgreSQL)
├── id = "kb_{kb_id}_doc_{doc_id}_chunk_{idx}"   ← 全局唯一
├── document (str)
├── metadata { kb_id, doc_id, chunk_index, ... }
└── embedding (vector)

evaluation_runs
├── id (UUID)
├── name
├── owner_id
├── status (pending/running/stopped/completed/completed_with_errors/failed)
├── config (JSONB)                  # {kb_ids, qa_sample_size, eval_top_k, ...}
├── summary (JSONB)                 # {metrics_avg, error_count, ...}
├── total_tasks / completed_tasks
├── progress (0-100)
├── resume_count
├── started_at / completed_at
└── created_at

evaluation_datasets
├── id (UUID)
├── name
├── kb_id → knowledge_bases.id     ← 数据集绑定 KB（用于 chunk_id 重映射）
├── qa_pairs (JSONB)               # [{question, answer, source_chunk_ids, is_multihop, is_out_of_scope}, ...]
└── created_at

evaluation_results
├── id (UUID)
├── run_id → evaluation_runs.id
├── qa_index
├── question / ground_truth
├── embedding_model
├── retrieval_strategy
├── rerank_model (nullable)
├── generation_model
├── retrieved_chunks (JSONB)        # 检索结果
├── retrieval_metrics (JSONB)       # 5 检索指标
├── generated_answer
├── generation_scores (JSONB)       # 3 LLM 指标
├── error_message
├── judge_error (boolean)           # LLM judge 是否失败
├── is_multihop / is_out_of_scope
├── created_at
└── UNIQUE (run_id, qa_index, embedding_model, retrieval_strategy,
           rerank_model, generation_model) NULLS NOT DISTINCT
           ↑ rerank_model=NULL 时也参与唯一判定（PostgreSQL 15+ 特性）

conversations / messages
├── conversations: {id, user_id, title, kb_id, created_at}
└── messages: {id, conversation_id, role, content, retrieved_chunks, created_at}
```

### 3.2 数据生命周期

| 实体 | 何时创建 | 何时删 | 何时迁移 |
|------|---------|--------|---------|
| user | 首次注册 / 管理员创建 | 管理员禁用 | 不需要 |
| KB | 用户在 UI 创建 | 用户删除 / 管理员 | 切 embedding = 新建 |
| document | 上传 | KB 删除级联 / 单删 | 不需要 |
| chunks | 文档上传时自动生成 | 文档删除级联 | 切 embedding 需重传 |
| eval run | UI 创建 | **永不删**（永久）| 升级 schema 需 alembic |
| eval dataset | UI 创建 | **永不删** | 同上 |
| eval result | 评估运行时 | 同 run | 同上 |
| conversation | 第一次发消息 | 用户删 / 30 天无活动清 | 不需要 |

---

## 4. 关键流程

### 4.1 文档上传 → 入库

```
User upload ──► POST /api/documents (multipart)
                       │
                       ▼
              save to backend/data/uploads/{kb_id}/{filename}
                       │
                       ▼
              parser.py ── extract text (pdf/docx/md/txt)
                       │
                       ▼
              chunking.chunk_text(strategy, size, overlap)
                       │
                       ▼
              embedding.embed_chunks(model, texts)
                       │
                       ▼
              vectorstore.add_to_collection(kb_id, embedding_model,
                                            ids, docs, metadatas, embeddings)
                       │
                       ▼
              update Document.status = "ready", chunk_count
```

### 4.2 用户提问 → 流式回答（SSE）

```
User input ──► POST /api/chat/stream (SSE)
                       │
                       ▼
              save user message ──► conversations/messages
                       │
                       ▼
              retrieval_pipeline.retrieve(query, kb_id, strategy, top_k)
                       │
                       ▼
              chunk_text into 1500-char context window
                       │
                       ▼
              LLM.stream(prompt + context + history)
                       │
                       ▼
              SSE: token chunks
                       │
                       ▼
              on done: save assistant message
```

### 4.3 创建评估 → 跑完 → 出报告

```
User clicks "创建评估" ──► POST /api/eval/runs
                                  │
                                  ▼
                          INSERT evaluation_runs (status=pending)
                          INSERT evaluation_datasets (auto-gen QA if needed)
                                  │
                                  ▼
                          asyncio.create_task(runner.start())
                                  │
       ┌──────────────────────────┴──────────────────────────┐
       │  runner._run():                                       │
       │  1. expand all tasks (KB × retrieval × rerank × gen) │
       │  2. get completed_keys from DB                       │
       │  3. pending = all - completed                          │
       │  4. asyncio.gather(*[_run_with_limit(t) for t in pending])│
       │  5. _finalize_run()                                    │
       │     - aggregate metrics                               │
       │     - mark status = completed / completed_with_errors │
       │     - ReportGenerator.generate() → .json + .md        │
       └──────────────────────────────────────────────────────────┘
```

### 4.4 断点续传（核心算法）

```python
# 1. 计算 "已完成 task keys"
#    完成定义（同时满足）：
#    - judge_error = False
#    - error_message IS NULL
#    - retrieved_chunks IS NOT NULL
completed_keys = await self._get_completed_task_keys()

# 2. 计算 pending
pending = [t for t in all_tasks if self._task_key(t) not in completed_keys]

# 3. 并发跑 pending
await asyncio.gather(*[self._run_with_limit(t) for t in pending])

# 4. _save_result 用 UPSERT（防止重复行）
stmt = pg_insert(EvaluationResult).values(...).on_conflict_do_update(
    constraint="uq_eval_result",
    set_=update_cols,
)
```

**前提**：
- 续跑 API 允许 `status IN (stopped, failed, completed_with_errors)` 续跑
- `uq_eval_result` 是 `UNIQUE NULLS NOT DISTINCT`（rerank_model=NULL 也触发冲突）

---

## 5. 关键决策记录（ADR）

### ADR-001：选 LangChain 1.x 不用 0.x

**决策**：使用 LangChain 1.x（`langchain>=0.3`），所有 LLM/Embedding 走 `ChatOpenAI` + `RunnableParallel`。

**理由**：
- LangChain 1.x 统一了 `langchain-openai` 接入层，**所有 OpenAI-compatible API 一行代码接入**
- `Runnable` 抽象让 RAG pipeline 组合简单（`prompt | llm | parser`）
- 0.x 的 `LLMChain` 已弃用

**代价**：
- LangChain 抽象偶尔有 bug（wrapper 层抛错不直观）
- 部分 RAG 模式（multi-vector, agent）需要自己写

### ADR-002：ChromaDB collection 按 embedding 分库

**决策**：每个 KB 用一个独立 collection，命名 `kb_emb_{safe_model_name}`，**不**共享。

**理由**：
- ChromaDB collection 锁定 embedding 维度，**多模型混用必然冲突**
- 切换 embedding 模型 = 重建 collection，**语义上正确**（旧 embedding 向量不该被新模型检索）

**代价**：
- 多 embedding 模型时磁盘占用 × N
- 删除 KB 时 collection 不自动删除（需要清理脚本）

### ADR-003：评估用 PG 存 OLTP + ChromaDB 存向量

**决策**：
- `evaluation_runs` / `evaluation_datasets` / `evaluation_results` 全部在 PostgreSQL
- ChromaDB 仅存 chunks 向量

**理由**：
- 评估数据是高度结构化的，**PG 的 JSONB + 索引强过 ChromaDB 的 metadata filter**
- 评估结果要 JOIN 检索、过滤、分组 → SQL 比 metadata filter 直观
- 评估查询路径不命中向量检索

**代价**：
- 评估跨 KB 复制数据集时需要重映射 `chunk_id`（用 `copy_dataset_to_other_kb.py`）

### ADR-004：5 大 Strategy 走 Factory 模式

**决策**：5 个能力域（LLM/Embedding/Rerank/Retrieval/Chunking）都走 `factory.py` + 注册表。

**理由**：
- 加新 Provider = 写 1 个类 + 1 行注册（Open/Closed 原则）
- 业务代码不 `if/else` 判断"用什么模型" → 通过配置切换
- 易测试（mock 一个 Provider 即可）

**代价**：
- 小项目初期稍显"过度设计"（但加 provider 时回报巨大）

### ADR-005：评估 LLM judge 默认用 MiMo（与生成模型同账户）

**决策**：默认 LLM judge = `mimo-v2.5`（=默认生成模型）。

**理由**：
- 用户预算考虑
- 评估整套在一个账户内计费

**已知问题**（[OPERATIONS.md#常见错误](./OPERATIONS.md#常见错误)）：
- 大数据集 + LLM 指标全开 → 余额快速耗尽
- **改进方向**：LLM judge 改 deepseek-v4-flash，mimo 余额只够生成（下次新建 run 实施）

---

## 6. 可扩展点

### 6.1 加新 LLM Provider

```python
# 1. 在 services/llm_provider/ 下新建文件
# services/llm_provider/anthropic.py
from .openai_compatible import OpenAICompatibleProvider

class AnthropicProvider(OpenAICompatibleProvider):
    _base_url = "https://api.anthropic.com/v1"  # 注: Anthropic 实际不是 OpenAI 协议，仅示意
    _api_key = settings.ANTHROPIC_API_KEY
    _model = "claude-sonnet-4-5"

# 2. 在 factory.py 注册
LLM_REGISTRY["claude-"] = AnthropicProvider

# 3. .env.example 加 ANTHROPIC_API_KEY

# 完成。业务代码零改动，UI 可选。
```

### 6.2 加新 Embedding

类似 6.1，实现 `EmbeddingProvider` 基类 + 在 `services/embedding/factory.py` 注册。

### 6.3 加新检索 Strategy

```python
# services/retrieval/strategies/graph_retrieval.py
class GraphRetrieval:
    async def retrieve(self, query, top_k, **kwargs):
        # 你的图检索实现
        return chunks

# services/retrieval/factory.py
RETRIEVAL_REGISTRY["graph"] = GraphRetrieval
```

### 6.4 加新评估指标

在 `services/eval/metrics.py` 加函数，在 `services/eval/runner.py` 调度点调用，UI 在 `EvaluationView.vue` 加 checkbox。

### 6.5 切换 Embedding 模型

**必须新建 KB**（不能改），然后用新 KB 重新上传文档。详见 [OPERATIONS.md#切换-embedding-模型](./OPERATIONS.md#切换-embedding-模型)。

---

## 7. 性能 & 扩展性

| 维度 | 当前限制 | 应对 |
|------|---------|------|
| 单 KB 文档数 | 10w chunks | 超出考虑切 KB |
| 评估任务数 | 无硬限，受 `DEFAULT_EVAL_CONCURRENCY=4` 限制 | 改 env |
| 检索 top-K | K≤50 | UI 限制 |
| ChromaDB 单 collection | 100w+ 向量性能下降 | 切 KB |
| PostgreSQL 连接池 | 5 + 10 overflow | `db/database.py` 自动适配 |
| SSE 并发 | 100 连接（uvicorn 默认）| 改 `uvicorn --workers` |

---

## 8. 进一步阅读

- [API.md](./API.md) — 所有 REST 端点 + 请求/响应
- [OPERATIONS.md](./OPERATIONS.md) — 部署、备份、监控
- [README.md](../README.md) — 快速开始

---

**文档维护**：每次加新模块 / 改数据流必须更新对应章节。
