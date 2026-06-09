# RAG 知识库系统 — 分层实现计划

## 技术栈总览

| 组件 | 技术选择 | 备注 |
|------|---------|------|
| 后端框架 | FastAPI | 全异步，自带 OpenAPI 文档 |
| 数据库 | PostgreSQL + SQLAlchemy async | Alembic 管理迁移 |
| 向量库 | ChromaDB | 统一一个 collection，metadata 过滤 kb_id |
| LLM | Ollama 本地 (qwen3.5:2b) | HTTP API 调用 |
| Embedding | Ollama 本地 (qwen3-embedding:0.6b) | 同上 |
| 文档解析 | PyMuPDF, python-docx, openpyxl 等 | 按文件类型分发 |
| 前端 | Vue3 + Vite + Element Plus | 中文生态好，开箱即用 |
| 认证 | JWT + bcrypt | 角色区分 admin/user |
| 容器化 | Docker Compose | PostgreSQL + ChromaDB 挂载卷 |

---

## 1. 项目初始化与基础架构搭建

- 初始化项目结构：`backend/`（FastAPI）和 `frontend/`（Vue3 + Vite + Element Plus）目录分离
- 配置 `requirements.txt`，锁定后端依赖：
  - FastAPI、uvicorn[standard]、SQLAlchemy[asyncio]、asyncpg、alembic
  - chromadb、httpx（调用 Ollama API）
  - tiktoken（精确 token 计数，中文分块核心依赖）
  - python-multipart、python-jose[cryptography]、passlib[bcrypt]、bcrypt
  - PyMuPDF、python-docx、openpyxl、python-pptx、beautifulsoup4、lxml
- 配置 `.env` 文件模板：
  ```
  DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/rag_kb
  CHROMADB_PATH=./data/chromadb
  OLLAMA_BASE_URL=http://localhost:11434
  JWT_SECRET_KEY=your-secret-key
  JWT_ALGORITHM=HS256
  JWT_EXPIRE_MINUTES=1440

  # 分块配置
  CHUNK_TARGET_TOKENS=300
  CHUNK_MAX_TOKENS=512
  CHUNK_OVERLAP_SENTENCES=2
  ```
- 搭建 FastAPI 应用骨架：app factory、CORS 中间件、路由挂载、全局异常处理、日志配置
- 初始化 Alembic 迁移工具，连接 PostgreSQL
- 编写 `Docker Compose`：PostgreSQL + ChromaDB 服务，数据卷持久化
- 编写 `GET /api/health` 健康检查接口，检测 PostgreSQL、ChromaDB、Ollama（llm + embedding）连通性

---

## 2. 数据模型与认证系统

### 数据库表设计

- **User 表**
  ```
  id          UUID (PK)
  username    String (unique)
  email       String (unique)
  hashed_password  String
  is_admin    Boolean (default False)
  created_at  DateTime
  ```

- **Category 表**
  ```
  id          SERIAL (PK)
  name        String (unique)
  ```

- **KnowledgeBase 表**
  ```
  id          SERIAL (PK)
  name        String
  description Text (nullable)
  category_id Integer (FK → categories.id, nullable)
  owner_id    UUID (FK → users.id, nullable)  — null = 管理员全局库
  is_global   Boolean (default False)
  created_at  DateTime
  ```

- **Document 表**
  ```
  id          SERIAL (PK)
  kb_id       Integer (FK → knowledge_bases.id)
  filename    String
  file_path   String
  file_type   String
  chunk_count Integer (default 0)
  status      String (processing / ready / failed)
  error       Text (nullable)
  created_at  DateTime
  ```

- **Conversation 表**（拆分自原 ChatHistory）
  ```
  id          UUID (PK)              — UUID 防遍历
  user_id     UUID (FK → users.id)
  title       String                 — 自动取第一条消息前 20 字
  kb_ids      ARRAY(Integer)         — 关联的知识库 ID 列表
  created_at  DateTime
  ```

- **Message 表**
  ```
  id              UUID (PK)
  conversation_id UUID (FK → conversations.id, CASCADE)
  role            String (user / assistant / system)
  content         Text
  sources         JSONB               — 引用来源：[{doc_id, filename, page, content, score}]
  created_at      DateTime
  ```

### 认证与权限

- 实现 JWT 认证：登录 / 注册接口、token 签发与校验依赖（`get_current_user`）
- 实现角色权限：
  - admin：可创建全局知识库、管理所有知识库、管理用户
  - 普通用户：只能创建私有知识库、操作自己的知识库、访问全局知识库
- Alembic 生成并执行首次迁移

---

## 3. 文档解析与向量化管道

### 文档解析器（`backend/services/parser.py`）

| 文件格式 | 解析库 | 说明 |
|---------|--------|------|
| `.pdf` | PyMuPDF (fitz) | 逐页提取文本 |
| `.docx` | python-docx | 段落级提取 |
| `.xlsx` | openpyxl | 逐行提取，拼为文本 |
| `.pptx` | python-pptx | 逐页 slide 文本 |
| `.txt` / `.md` | 直接读取 | — |
| `.csv` | csv 模块 | 逐行读取 |
| `.json` | json 模块 | 格式化后读取 |
| `.html` | BeautifulSoup | 提取纯文本 |

### 文本分块策略（中文优化）

> **核心问题**：固定 512 字符切分会把完整中文句子切成两半，破坏语义完整性，导致 embedding 质量下降、检索结果不连贯。

#### 分块流程

```
原始文本
  ↓  1. 段落预分割（按 \n\n 或空行切分为段落段落列表）
段落列表
  ↓  2. 句子分割（按中文句末标点切分）
句子列表
  ↓  3. 合并句子为 chunk（按 token 数上限合并，不跨句切割）
chunk 列表
  ↓  4. 重叠处理（相邻 chunk 保留 1-2 句重叠，保证上下文连贯）
最终 chunks + metadata
```

#### 具体规则

- **步骤 1 — 段落预分割**：按连续空行（`\n\n`）或文档原生段落（DOCX paragraph）切分，保留段落边界
- **步骤 2 — 句子分割**：在段落内部按中文句末标点切分：`。！？；
` 以及英文标点 `.!?;`，同时保留引号内的完整句子不拆分
- **步骤 3 — 合并为 chunk**：
  - 目标 chunk 大小：**~300 tokens**（约 450-600 中文字符，因为中文 1 字 ≈ 1.5-2 tokens）
  - 最大 chunk 大小：**512 tokens**（硬上限，超过则强制独立成 chunk）
  - 合并时按句子顺序累加，**绝不跨句切割**
  - 单个句子超过 512 tokens 时：按逗号/顿号降级切分，仍保持子句完整
- **步骤 4 — 重叠处理**：相邻两个 chunk 之间保留 **前 1-2 句重叠**（约 50-100 tokens），保证跨 chunk 的语义连贯性
- **Token 计算**：使用 `tiktoken` 库（cl100k_base 编码器）做精确 token 计数，不依赖字符数估算

#### Chunk 结构

每个 chunk 保留元数据：
```json
{
  "text": "chunk 正文内容...",
  "metadata": {
    "doc_id": 5,
    "filename": "员工手册.pdf",
    "kb_id": 1,
    "chunk_index": 3,
    "page": 2,
    "start_char": 1024,
    "end_char": 1536
  }
}
```

#### 分块策略配置项（可调参数）

在 `backend/config.py` 中集中配置，方便后续调优：
```python
# 分块配置
CHUNK_TARGET_TOKENS = 300      # 目标 chunk token 数
CHUNK_MAX_TOKENS = 512         # 硬上限
CHUNK_OVERLAP_SENTENCES = 2    # 重叠句数
CHUNK_SEPARATORS = ["\n\n", "。", "！", "？", "；", ".", "!", "?"]  # 分割优先级
```

### ChromaDB 集成

- **统一一个 collection**：`collection_name = "all_documents"`
- 每条向量带 metadata：`{kb_id, doc_id, chunk_index, filename, page}`
- 通过 Ollama HTTP API (`POST http://localhost:11434/api/embeddings`) 调用 `qwen3-embedding:0.6b` 生成 embedding
- 删除知识库时：`collection.delete(where={"kb_id": 1})`

### 异步文档处理

- 上传接口：`POST /api/documents/upload`（支持多文件）
- **异步处理**：上传后立即返回 `{"status": "processing", "doc_id": id}`，后台 `BackgroundTasks` 执行解析 → 分块 → 向量化
- 状态流转：`processing` → `ready` / `failed`（含 error 信息）
- 前端通过轮询 `GET /api/documents/{id}/status` 跟踪进度

### 文件限制

- 最大上传大小：**50MB**
- 允许格式：`.pdf`, `.docx`, `.txt`, `.md`, `.xlsx`, `.pptx`, `.csv`, `.json`, `.html`
- 上传时校验文件大小和格式，不合法直接返回 400

### Ollama 调用容错

- Ollama 服务不可用时返回友好错误提示（非 500 堆栈），前端展示“LLM 服务未启动，请检查 Ollama”
- embedding 请求失败时自动重试 1 次（间隔 2 秒）
- 超时控制：embedding 请求 30s 超时，chat 请求 120s 超时（2b 模型生成较慢）

---

## 4. 知识库管理 API

### 知识库 CRUD

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/kb` | POST | 创建知识库（用户创建私有 / admin 创建全局） |
| `/api/kb` | GET | 列出可访问的知识库（用户：自己的 + 全局的；admin：全部） |
| `/api/kb/{id}` | GET | 知识库详情（含文档列表） |
| `/api/kb/{id}` | PUT | 更新知识库信息 |
| `/api/kb/{id}` | DELETE | 删除知识库（级联删除文档 + ChromaDB 中的向量） |

### 文档管理

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/kb/{id}/documents` | GET | 文档列表（含 status） |
| `/api/documents/{id}/status` | GET | 查询文档处理状态 |
| `/api/documents/{id}` | DELETE | 删除文档（同步删除 ChromaDB 中的向量） |
| `/api/documents/{id}/reindex` | POST | 重新向量化 |

### 分类管理

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/categories` | GET | 获取所有分类 |
| `/api/categories` | POST | admin 添加分类 |

---

## 5. RAG 对话核心

### 检索管道

- 用户输入 → Ollama embedding → ChromaDB similarity search（top_k=5）
- 结果过滤：通过 metadata 的 `kb_id` 只检索用户有权访问的知识库
- 支持 `search_all` 模式：搜索当前用户有权限的所有知识库

### 对话接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/chat` | POST | 发送消息并获取回答 |
| `/api/chat/history` | GET | 获取当前用户的会话列表 |
| `/api/chat/history/{conversation_id}` | GET | 获取某次对话的消息详情 |
| `/api/chat/history/{conversation_id}` | DELETE | 删除某次对话 |

### 对话请求结构

```json
{
  "query": "年假有几天？",
  "kb_ids": [1, 3],
  "search_all": false,
  "conversation_id": "uuid-xxx"
}
```

### 对话响应结构

```json
{
  "conversation_id": "uuid-xxx",
  "answer": "根据文档规定，正式员工入职满1年后享有5天带薪年假...",
  "sources": [
    {
      "doc_id": 1,
      "filename": "员工手册.pdf",
      "page": 3,
      "content": "正式员工入职满1年后，享有5天带薪年假...",
      "score": 0.87
    }
  ]
}
```

### 对话逻辑

- 调用 Ollama API (`POST http://localhost:11434/api/chat`) 使用 `qwen3.5:2b` 生成回答
- Ollama 请求开启 `stream: true`，逐 token 流式接收
- **多轮上下文**：保留最近 5 轮对话历史拼进 Prompt
- **Prompt 模板**：
  ```
  你是一个知识库问答助手。根据以下参考资料回答用户问题。如果资料中没有相关信息，请如实说明。

  参考资料：
  {检索到的 chunks + 来源标注}

  历史对话：
  {最近5轮对话}

  用户问题：{query}
  ```
- 同时记录到 Conversation + Message 两张表，Message.sources 存引用来源 JSONB

### 流式输出（SSE）

#### 后端实现

- 使用 FastAPI `StreamingResponse` + SSE（Server-Sent Events）协议
- 响应 Content-Type: `text/event-stream`
- 流式流程：
  ```
  1. [SSE] sources 事件  →  先返回引用来源（前端立即展示引用卡片）
     event: sources
     data: [{"doc_id":1, "filename":"员工手册.pdf", ...}]

  2. [SSE] token 事件    →  逐 token 流式返回 AI 回答
     event: token
     data: "根据"
     event: token
     data: "文档"
     ...

  3. [SSE] done 事件     →  标记回答结束，附带 conversation_id
     event: done
     data: {"conversation_id": "uuid-xxx"}
  ```
- **为什么 sources 先发**：前端可以在 AI 还在打字时就渲染引用来源卡片，用户体验更好
- 后端在流式结束后异步写入 Message 表（role=assistant, content=完整回答, sources=JSONB）

#### 前端实现

- 使用 `fetch` + `ReadableStream` 读取 SSE（不用 EventSource，因为需要 POST 请求）
- 解析 SSE 事件流，按 event 类型分发：
  - `sources`：渲染引用来源卡片
  - `token`：逐字追加到对话气泡，实现打字机效果
  - `done`：结束流式，启用输入框
- 打字机效果：每收到一个 token，追加到当前回答文本并自动滚动到底部
- 引用来源卡片：显示文件名 + 页码 + 原文摘要，点击可展开完整原文

#### SSE 事件格式总结

| 事件类型 | data 内容 | 触发时机 |
|---------|----------|----------|
| `sources` | `[{doc_id, filename, page, content, score}]` | 检索完成后立即发送 |
| `token` | 单个 token 字符串 | LLM 每生成一个 token |
| `done` | `{conversation_id}` | 回答生成完毕 |
| `error` | `{message}` | 检索/生成过程出错 |

---

## 6. 前端界面开发

### 技术选型

- Vue3 + Vite + Element Plus
- Axios 封装 API 调用层（统一错误处理、token 自动刷新）
- Markdown 渲染：`markdown-it` 或 `marked`

### 页面规划

- **登录 / 注册页**
  - 表单验证、JWT 存 localStorage

- **知识库管理页**
  - 列表展示（区分全局 / 个人标签）
  - 创建 / 编辑 / 删除知识库
  - 分类筛选
  - 上传文档：拖拽上传 + 文件列表 + 处理状态跟踪（processing → ready）
  - 分块参数提示：上传页显示当前分块策略（目标 300 tokens / 最大 512 tokens），让管理员了解切分逻辑

- **对话页**
  - 知识库选择器：多选指定知识库 / 搜索全部知识库
  - 对话界面：**流式打字效果**（逐 token 追加，自动滚动）
  - **引用来源展示**：每条 AI 回答上方显示 📎 引用来源卡片列表，可展开查看原文
  - **思考过程指示**：AI 生成中显示“正在思考...”动画，生成完毕后消失
  - 历史对话列表（左侧栏）
  - Markdown 渲染回答内容

- **管理员面板**（admin only）
  - 用户管理（查看用户列表、设置/取消管理员）
  - 全局知识库管理
  - 系统统计（知识库数量、文档数量、对话数量）

- **系统状态页**
  - 显示 Ollama、PostgreSQL、ChromaDB 是否在线及响应延迟
  - 调用 `/api/health` 接口展示

### 响应式布局

- 支持移动端基本访问

---

## 开发顺序（落地执行）

### Week 1：跑通核心链路
- Day 1-2：Docker Compose + FastAPI 骨架 + `/api/health`
- Day 3-4：文档上传 → 解析 → 切分 → ChromaDB 入库
- Day 5-7：RAG 检索 → LLM 生成 → 流式返回（无认证，无前端，用 curl 测）

### Week 2：补全后端
- Day 1-2：PostgreSQL 模型 + Alembic 迁移
- Day 3-4：JWT 认证 + 权限
- Day 5-7：知识库 CRUD + 对话历史保存（Conversation + Message）

### Week 3：前端 + 联调
- Day 1-3：Vue3 脚手架 + 对话页 + 文档上传页
- Day 4-5：联调 + 引用来源展示
- Day 6-7：管理员面板 + 细节打磨

> **原则：先跑通核心 RAG 链路，再补全认证和前端。**

---

## 关键设计决策记录

| 决策点 | 选择 | 理由 |
|--------|------|------|
| ChromaDB 映射 | 统一一个 collection + metadata 过滤 | 跨库检索高效，删库方便，减少管理开销 |
| ChatHistory | 拆为 Conversation + Message | 查询方便，CASCADE 删除，Message 支持 JSONB sources |
| 文档处理 | 异步 BackgroundTasks | 大文件不阻塞请求，前端可跟踪状态 |
| 引用来源 | 必须做 | RAG 无引用 = 黑盒，用户无法判断可信度 |
| 多轮上下文 | 保留最近 5 轮 | 够用且不浪费 token |
| Docker Compose | 包含 PostgreSQL + ChromaDB | 本地开发环境统一，避免手动安装 |
| 健康检查 | `/api/health` | 前端启动时确认服务可用，提前报错 |
| 文本分块 | 中文句子级分块 + tiktoken | 避免固定字符切分破坏语义，保证 embedding 质量 |
| 流式输出 | SSE + sources 先发 | 打字机体验，引用卡片先行渲染 |
| Ollama 容错 | 超时 + 重试 + 友好错误 | 本地模型服务不稳定时用户体验兜底 |
