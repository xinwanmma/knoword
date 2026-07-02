# Knoword REST API 文档

> 适合：前端开发者、API 集成方
> 配套：[README.md](../README.md)（项目入口）· [ARCHITECTURE.md](./ARCHITECTURE.md) · [OPERATIONS.md](./OPERATIONS.md)
> **OpenAPI 交互文档**：`http://localhost:8000/docs`（Swagger UI，实时反映代码）

---

## 0. 通用约定

### 0.1 Base URL

```
http://localhost:8000                    # 开发
https://your-domain.com                  # 生产
```

### 0.2 认证

- **JWT Bearer Token**：除 `/api/auth/register` 和 `/api/auth/login` 外，**所有**端点需要 `Authorization: Bearer <token>`
- **Admin 守卫**：路径 `/api/admin/*` 需要管理员 token（`is_admin=true`）
- Token 过期时间：24 小时（在 `core/security.py`）

### 0.3 响应格式

成功：
```json
{ "data": {...} }                  // 单个
[ {...}, {...} ]                    // 列表
```

错误：
```json
{
  "detail": "错误信息"             // FastAPI 默认
}
```

### 0.4 分页

当前**未实现分页**。如果列表很大（如评估结果），考虑：
- 用 `qa_sample_size` 限制数据量
- 用 PostgreSQL 直接查询（不通过 API）

### 0.5 SSE（Server-Sent Events）

仅 `/api/chat/stream` 使用。详见 [§2.1](#21-post-apichatstream-sse)。

---

## 1. 认证 `/api/auth`（3 端点）

### 1.1 `POST /api/auth/register`

注册新用户（普通用户，**不是管理员**）。

**Request Body**:
```json
{
  "username": "zhangsan",
  "password": "YourStrongPassword123",
  "email": "zhang@example.com"
}
```

**Response 201**:
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer"
}
```

**Errors**:
- `400` 用户名已存在 / 邮箱格式错 / 密码弱

---

### 1.2 `POST /api/auth/login`

登录获取 JWT。

**Request Body**:
```json
{ "username": "zhangsan", "password": "YourStrongPassword123" }
```

**Response 200**:
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer"
}
```

**Errors**:
- `401` 用户名或密码错误
- `403` 账号被禁用

---

### 1.3 `GET /api/auth/me`

获取当前登录用户信息。

**Response 200**:
```json
{
  "id": "uuid",
  "username": "zhangsan",
  "email": "zhang@example.com",
  "is_admin": false,
  "is_active": true,
  "created_at": "2026-07-01T10:00:00Z"
}
```

---

## 2. 对话 `/api/chat`（4 端点）

### 2.1 `POST /api/chat/stream` (SSE)

**流式对话**，返回 SSE 事件流。

**Request Body**:
```json
{
  "kb_id": 6,
  "query": "什么是 RAG?",
  "conversation_id": "uuid-or-null",        // 传 null = 新建对话
  "top_k": 5,                                // 检索 top-K
  "retrieval_strategy": "hybrid",            // "vector" | "hybrid" | "rerank"
  "rerank_model": "Qwen/Qwen3-Reranker-4B",  // 仅 rerank 策略需要
  "temperature": 0.5
}
```

**SSE 事件流**：

```
event: chunk
data: {"content": "RAG 是"}

event: chunk
data: {"content": " 一种"}

...

event: sources
data: {"chunks": [{"id": "kb_6_doc_3_chunk_12", "content": "...", "metadata": {...}}, ...]}

event: done
data: {"conversation_id": "uuid", "message_id": "uuid", "usage": {"prompt_tokens": 1234, "completion_tokens": 567}}
```

**事件类型**：
- `chunk` — 增量 token（流式）
- `sources` — 检索到的 chunks（一次性，生成开始时）
- `done` — 结束（含 token 统计）
- `error` — 错误（如 LLM 调用失败）

**Errors**：
- `404` KB 不存在
- `503` LLM 不可达

---

### 2.2 `GET /api/chat/history`

获取当前用户的对话列表。

**Response 200**:
```json
[
  {
    "id": "uuid",
    "title": "什么是 RAG?",
    "kb_id": 6,
    "created_at": "2026-07-01T10:00:00Z"
  }
]
```

---

### 2.3 `GET /api/chat/history/{conversation_id}`

获取某个对话的所有消息。

**Response 200**:
```json
[
  {
    "id": "uuid",
    "role": "user",
    "content": "什么是 RAG?",
    "retrieved_chunks": null,
    "created_at": "..."
  },
  {
    "id": "uuid",
    "role": "assistant",
    "content": "RAG 是...",
    "retrieved_chunks": [...],
    "created_at": "..."
  }
]
```

---

### 2.4 `DELETE /api/chat/history/{conversation_id}`

删除对话（级联删除 messages）。

**Response**: `204 No Content`

---

## 3. 知识库 `/api/knowledge-base`（5 端点）

### 3.1 `POST /api/knowledge-base`

创建知识库。

**Request Body**:
```json
{
  "name": "产品手册 v2",
  "description": "2026 年新版产品手册",
  "embedding_model": "Qwen/Qwen3-Embedding-8B",     // 必须与现有 ChromaDB 维度匹配
  "chunking_strategy": "recursive",                  // "fixed" | "recursive" | "semantic"
  "chunk_size": 500,
  "chunk_overlap": 50,
  "retrieval_strategy": "hybrid"                     // 默认检索策略
}
```

**可用的 `embedding_model`**（`/api/system/available-models` 返回）：
- Ollama：`qwen3-embedding:0.6b`
- HuggingFace：`Qwen/Qwen3-Embedding-8B`、`shibing624/text2vec-base-chinese`
- SiliconFlow：`Qwen/Qwen3-Embedding-8B`

**Response 201**: 完整 KB 对象（见 3.3）

---

### 3.2 `GET /api/knowledge-base`

获取当前用户的所有 KB。

**Response 200**: `[KnowledgeBaseOut, ...]`

---

### 3.3 `GET /api/knowledge-base/{kb_id}`

获取 KB 详情。

**Response 200**:
```json
{
  "id": 6,
  "name": "产品手册 v2",
  "description": "...",
  "owner_id": "uuid",
  "embedding_model": "Qwen/Qwen3-Embedding-8B",
  "chunking_strategy": "recursive",
  "chunk_size": 500,
  "chunk_overlap": 50,
  "retrieval_strategy": "hybrid",
  "created_at": "..."
}
```

---

### 3.4 `PUT /api/knowledge-base/{kb_id}`

更新 KB 配置（**不能改 embedding_model**，需要新建）。

**Request Body**: 同创建，可只传要改的字段。

---

### 3.5 `DELETE /api/knowledge-base/{kb_id}`

删除 KB（**级联删除所有 documents + ChromaDB collection**）。

**Response**: `204 No Content`

⚠️ **危险操作**：不可恢复，ChromaDB collection 不自动清理磁盘，需手动删 `backend/data/chromadb/kb_emb_*/`。

---

## 4. 文档 `/api/documents`（5 端点）

### 4.1 `POST /api/documents/upload`

**Query 参数**：
- `kb_id` (int, **必填**) — 目标 KB

**Request**: `multipart/form-data`
- `files` (List[UploadFile]) — 一个或多个文件

**支持格式**：`.pdf` `.docx` `.md` `.txt` `.html`

**Response 201**:
```json
[
  {
    "id": 17,
    "filename": "manual.pdf",
    "file_type": "pdf",
    "file_size": 1234567,
    "status": "processing",         // pending → processing → ready | failed
    "chunk_count": null,
    "indexed_at": null
  }
]
```

⚠️ 上传是**异步处理**的，初始 status=`processing`。轮询 4.2 看完成。

---

### 4.2 `GET /api/documents/{doc_id}/status`

查询文档处理状态。

**Response 200**:
```json
{
  "id": 17,
  "status": "ready",        // pending / processing / ready / failed
  "chunk_count": 247,
  "indexed_at": "2026-07-01T10:05:00Z",
  "error_message": null
}
```

---

### 4.3 `DELETE /api/documents/{doc_id}`

删除文档（**级联删除 ChromaDB 中所有 chunks**）。

**Response**: `204 No Content`

---

### 4.4 `POST /api/documents/{doc_id}/reindex`

强制重新索引（重新分块 + 重新 embedding）。

⚠️ 会**删除**原 ChromaDB 记录，再重建。**保留** DB 行。

**Response 200**: 更新后的 Document 对象。

---

### 4.5 `GET /api/documents/kb/{kb_id}`

列出某 KB 下所有文档。

**Response 200**: `[DocumentOut, ...]`

---

## 5. 评估中心 `/api/eval`（13 端点）

### 5.1 `GET /api/eval/models`

获取系统当前可用的模型列表（**动态**根据 .env 配置 + Ollama/HF 检测）。

**Response 200**:
```json
{
  "embedding": [
    {"name": "qwen3-embedding:0.6b", "source": "ollama", "available": true, "dim": 1024},
    {"name": "Qwen/Qwen3-Embedding-8B", "source": "siliconflow", "available": true, "dim": 4096, "api_key_configured": true}
  ],
  "llm": [
    {"name": "mimo-v2.5", "available": true},
    {"name": "deepseek-v4-flash", "available": true, "api_key_configured": true},
    {"name": "GLM-4.5-flash", "available": false, "reason": "GLM_API_KEY not configured"}
  ],
  "rerank": [...]
}
```

---

### 5.2 数据集（5 端点）

#### 5.2.1 `POST /api/eval/datasets`

创建数据集。

**Request Body**:
```json
{
  "name": "testdata-100-8b",
  "kb_id": 6,
  "qa_pairs": [                      // 可选：不传 = 自动从 KB 生成
    {
      "question": "什么是 RAG?",
      "answer": "RAG 是检索增强生成...",
      "source_chunk_ids": ["kb_6_doc_3_chunk_12", "kb_6_doc_5_chunk_8"],
      "is_multihop": false,
      "is_out_of_scope": false
    }
  ],
  "auto_generate": true,             // 是否自动从 KB 生成 QA
  "auto_generate_config": {          // auto_generate=true 时生效
    "target_qa_count": 100,
    "include_multihop": true,
    "include_out_of_scope": true
  }
}
```

**Response 201**: DatasetDetailOut（含完整 qa_pairs）

---

#### 5.2.2 `GET /api/eval/datasets`

列出所有数据集。

**Response 200**: `[DatasetOut, ...]`

---

#### 5.2.3 `GET /api/eval/datasets/{dataset_id}`

获取数据集详情（含完整 qa_pairs）。

---

#### 5.2.4 `DELETE /api/eval/datasets/{dataset_id}`

删除数据集。

**Response**: `204 No Content`

---

### 5.3 Run（7 端点）

#### 5.3.1 `POST /api/eval/runs`

创建评估 run 并启动。**需要 admin 权限**。

**Request Body**:
```json
{
  "name": "eval-8B-vs-0.6B",
  "dataset_id": "uuid",
  "retrieval_strategies": ["vector", "hybrid", "rerank"],
  "rerank_models": ["Qwen/Qwen3-Reranker-4B"],      // 仅 rerank 策略用
  "generation_models": ["mimo-v2.5", "mimo-v2.5-pro", "deepseek-v4-flash"],
  "concurrency": 4,
  "qa_sample_size": 30,                              // 从数据集里取前 N 个
  "enabled_metrics": [                               // 不传 = 全 8 个
    "recall_at_k", "precision_at_k", "hit_at_k", "mrr", "ndcg_at_k",
    "faithfulness", "answer_relevancy", "answer_correctness"
  ],
  "llm_metric_model": "mimo-v2.5",                   // LLM judge 用的模型
  "eval_top_k": 10                                   // 检索 K，1-50，默认 10
}
```

**可用 metric keys**：
- 检索：`recall_at_k` / `precision_at_k` / `hit_at_k` / `mrr` / `ndcg_at_k`
- LLM：`faithfulness` / `answer_relevancy` / `answer_correctness`

**任务数计算**：
```
total = qa_sample_size × retrieval_strategies 数
        × (rerank_models 数 if "rerank" in retrieval_strategies else 1)
        × generation_models 数
```

**Response 201**: EvalRunProgress

---

#### 5.3.2 `GET /api/eval/runs`

列出所有 run（按时间倒序）。

---

#### 5.3.3 `GET /api/eval/runs/{run_id}`

获取 run 详情（含 progress / status / summary）。

**Response 200**:
```json
{
  "id": "uuid",
  "name": "eval-8B-vs-0.6B",
  "status": "completed_with_errors",
  "progress": 96,
  "total_tasks": 270,
  "completed_tasks": 270,
  "started_at": "...",
  "completed_at": "...",
  "resume_count": 5,
  "config": {...},
  "summary": {
    "metrics_avg": {
      "recall_at_k": 0.81,
      "mrr": 0.84,
      ...
    },
    "error_count": 10,
    "judge_error_count": 0
  },
  "report_json_path": "backend/reports/eval_xxx_xxx.json",
  "report_md_path": "backend/reports/eval_xxx_xxx.md"
}
```

---

#### 5.3.4 `GET /api/eval/runs/{run_id}/progress`

轻量级轮询接口（前端每 2 秒调一次），返回数据同 5.3.3。

---

#### 5.3.5 `POST /api/eval/runs/{run_id}/resume`

续跑。**允许状态**：`stopped` / `failed` / `completed_with_errors`。

**算法**：
- 计算 completed_keys（DB 里有完整数据的 task）
- pending = all_tasks - completed_keys
- 跑 pending → 完成后跑 `_finalize_run()` → 重新生成报告

**Response 200**: EvalRunProgress（status 短暂变 `running`）

---

#### 5.3.6 `POST /api/eval/runs/{run_id}/stop`

主动停止。

**Response 200**: EvalRunProgress

**注意**：停止后**不生成报告**（任务部分写入 DB）。再次 resume 即可。

---

#### 5.3.7 `GET /api/eval/runs/{run_id}/results`

获取所有 task 的明细结果（用于前端表格 / 调试）。

**Response 200**:
```json
[
  {
    "id": "uuid",
    "qa_index": 0,
    "question": "...",
    "ground_truth": "...",
    "embedding_model": "Qwen/Qwen3-Embedding-8B",
    "retrieval_strategy": "rerank",
    "rerank_model": "Qwen/Qwen3-Reranker-4B",
    "generation_model": "deepseek-v4-flash",
    "retrieved_chunks": [...],
    "retrieval_metrics": {"recall_at_k": 1.0, "mrr": 1.0, ...},
    "generated_answer": "...",
    "generation_scores": {"faithfulness": 0.85, "answer_relevancy": 1.0, "answer_correctness": 0.71},
    "judge_error": false,
    "is_multihop": false,
    "is_out_of_scope": false
  }
]
```

---

#### 5.3.8 `DELETE /api/eval/runs/{run_id}`

删除 run（级联删除 results）。**慎用**（报告不删，但 DB 数据没了）。

**Response**: `204 No Content`

---

## 6. 管理后台 `/api/admin/*`（8 端点）

**所有端点需要 `is_admin=true` 的 JWT**。

### 6.1 统计

#### 6.1.1 `GET /api/admin/stats`

**Response 200**:
```json
{
  "total_users": 5,
  "total_kbs": 12,
  "total_documents": 47,
  "total_eval_runs": 23,
  "active_users_30d": 3
}
```

---

### 6.2 用户管理（5 端点）

#### 6.2.1 `GET /api/admin/users`

列出所有用户。

#### 6.2.2 `GET /api/admin/users/{user_id}`

获取用户详情。

#### 6.2.3 `POST /api/admin/users/{user_id}/toggle-admin`

切换用户的 admin 权限。

**限制**：
- ❌ 不能撤销自己的 admin 权限
- ❌ 不能撤销最后一个 admin

#### 6.2.4 `DELETE /api/admin/users/{user_id}`

删除用户（**级联删 KB、documents、eval runs**）。

**限制**：
- ❌ 不能删除自己
- ❌ 不能删除最后一个 admin

#### 6.2.5 用户注册

管理员可通过 `POST /api/auth/register` 创建普通用户，或直接在数据库插入 admin 标记。

---

### 6.3 KB 管理（3 端点）

#### 6.3.1 `GET /api/admin/kbs`

列出**所有用户**的 KB（管理员视图）。

#### 6.3.2 `GET /api/admin/kbs/{kb_id}/documents`

列出某 KB 下所有文档（管理员视图，跨用户）。

#### 6.3.3 `DELETE /api/admin/kbs/{kb_id}`

删除任意用户的 KB（管理员特权）。

---

## 7. 系统 `/api/system`（1 端点）

### 7.1 `GET /api/system/health`

**无需认证**。健康检查。

**Response 200**:
```json
{
  "status": "ok",
  "db": "ok",
  "chromadb": "ok",
  "llm_providers": {
    "mimo-v2.5": "ok",
    "deepseek-v4-flash": "ok"
  }
}
```

**Response 503**（部分依赖不可达）：
```json
{
  "status": "degraded",
  "db": "ok",
  "chromadb": "failed: Connection refused",
  ...
}
```

---

## 8. 端点总览表

| 路径 | 方法 | 鉴权 | 说明 |
|------|------|------|------|
| `/api/auth/register` | POST | ❌ | 注册 |
| `/api/auth/login` | POST | ❌ | 登录 |
| `/api/auth/me` | GET | ✅ | 当前用户 |
| `/api/chat/stream` | POST | ✅ | SSE 流式对话 |
| `/api/chat/history` | GET | ✅ | 对话列表 |
| `/api/chat/history/{id}` | GET | ✅ | 消息详情 |
| `/api/chat/history/{id}` | DELETE | ✅ | 删除对话 |
| `/api/knowledge-base` | POST | ✅ | 创建 KB |
| `/api/knowledge-base` | GET | ✅ | 列出我的 KB |
| `/api/knowledge-base/{id}` | GET | ✅ | KB 详情 |
| `/api/knowledge-base/{id}` | PUT | ✅ | 更新 KB |
| `/api/knowledge-base/{id}` | DELETE | ✅ | 删除 KB |
| `/api/documents/upload?kb_id=` | POST | ✅ | 上传文档 |
| `/api/documents/{id}/status` | GET | ✅ | 文档状态 |
| `/api/documents/{id}` | DELETE | ✅ | 删除文档 |
| `/api/documents/{id}/reindex` | POST | ✅ | 重新索引 |
| `/api/documents/kb/{kb_id}` | GET | ✅ | KB 下文档列表 |
| `/api/eval/models` | GET | ✅ | 可用模型 |
| `/api/eval/datasets` | POST | ✅ | 创建数据集 |
| `/api/eval/datasets` | GET | ✅ | 列出数据集 |
| `/api/eval/datasets/{id}` | GET | ✅ | 数据集详情 |
| `/api/eval/datasets/{id}` | DELETE | ✅ | 删除数据集 |
| `/api/eval/runs` | POST | 🔒 admin | 创建 run |
| `/api/eval/runs` | GET | ✅ | 列出 runs |
| `/api/eval/runs/{id}` | GET | ✅ | run 详情 |
| `/api/eval/runs/{id}/progress` | GET | ✅ | 轻量轮询 |
| `/api/eval/runs/{id}/resume` | POST | ✅ | 续跑 |
| `/api/eval/runs/{id}/stop` | POST | ✅ | 停止 |
| `/api/eval/runs/{id}/results` | GET | ✅ | 任务明细 |
| `/api/eval/runs/{id}` | DELETE | 🔒 admin | 删除 run |
| `/api/admin/stats` | GET | 🔒 admin | 系统统计 |
| `/api/admin/users` | GET | 🔒 admin | 列出用户 |
| `/api/admin/users/{id}` | GET | 🔒 admin | 用户详情 |
| `/api/admin/users/{id}/toggle-admin` | POST | 🔒 admin | 切换 admin |
| `/api/admin/users/{id}` | DELETE | 🔒 admin | 删除用户 |
| `/api/admin/kbs` | GET | 🔒 admin | 列出所有 KB |
| `/api/admin/kbs/{id}/documents` | GET | 🔒 admin | 跨用户查文档 |
| `/api/admin/kbs/{id}` | DELETE | 🔒 admin | 删除任意 KB |
| `/api/system/health` | GET | ❌ | 健康检查 |

**合计 39 端点**（3+4+5+5+13+8+1）

---

**文档维护**：每次改 endpoint 路径、参数、错误码必须同步本文件。
