# 项目清理与模块化计划

> 待用户确认后再开始执行

## 1. 现状概览

### 项目规模
- 后端 Python 文件：**74 个**（含 alembic 迁移、tests、根目录脚本）
- 前端 Vue/JS 文件：**11 个**
- 总代码量约 **5500 行**

### 已有架构
- **后端**：FastAPI + SQLAlchemy(async) + Alembic + ChromaDB
- **前端**：Vue3 + Pinia + Element Plus + Vite
- **核心模式**：Strategy + Factory（5 个能力点：embedding/llm/rerank/retrieval/chunking）
- **评估系统**：8 个指标（5 检索 + 3 LLM），基于 LangChain

---

## 2. 待删除文件清单

### 2.1 后端 — 完全无用的死代码（**8 个**）

| # | 文件 | 引用数 | 原因 | 风险 |
|---|------|--------|------|------|
| 1 | `backend/app/core/embeddings.py` | 0 | LangChain Embeddings 兼容层，无人调用 | 无 |
| 2 | `backend/app/core/llm.py` | 1 | 只被 `chat.py:202` 用 1 次作为兼容入口 | 中（需改 chat.py） |
| 3 | `backend/app/services/retrieval/graph_retrieval.py` | 1 | Microsoft GraphRAG 占位，fallback 到 vector | 中（需改 factory.py + __init__.py） |
| 4 | `backend/app/api/__init__.py` | 0 | 空文件 | 无 |
| 5 | `backend/app/core/__init__.py` | 0 | 空文件 | 无 |
| 6 | `backend/app/services/__init__.py` | 0 | 空文件 | 无 |
| 7 | `backend/app/db/__init__.py` | 0 | 空文件 | 无 |
| 8 | `backend/app/middleware/__init__.py` | 0 | 空文件 | 无 |
| 9 | `backend/app/models/__init__.py` | 0 | 空文件 | 无 |
| 10 | `backend/app/schemas/__init__.py` | 0 | 空文件 | 无 |

### 2.2 后端 — 待合并/移除（**2 个**）

| # | 文件 | 处理 | 原因 |
|---|------|------|------|
| 11 | `backend/app/services/retrieval_pipeline.py` | 合并进 `retrieval/` 目录或 inline 到 `chat.py` | 只是 `get_retrieval_strategy` 的薄包装 |
| 12 | `backend/app/services/vectorstore.py` | 移入 `services/vectorstore/` 包（与 retrieval 风格统一） | 顶级散文件 |

### 2.3 测试 — 已损坏（**1 个**）

| # | 文件 | 处理 | 原因 |
|---|------|------|------|
| 13 | `backend/tests/test_chat.py` | 重写或删除 | 引用了不存在的模块 `app.services.ollama_service`、`app.services.reranker`，跑必报错 |

### 2.4 配置 — 残留项（**2 处**）

| # | 位置 | 处理 |
|---|------|------|
| 14 | `config.py` `USE_RAGAS` 字段 | 删除（RAGAS 已弃用） |
| 15 | `.env.example` 的 `USE_RAGAS` / `MIMO_LITE_MODEL` RAGAS 相关注释 | 清理 |

### 2.5 文档 — 已过时（**1 个**）

| # | 文件 | 处理 |
|---|------|------|
| 16 | `README.md` | 重写（见 §5） |

### 2.6 前端 — 无用依赖（**1 个**）

| # | 位置 | 处理 |
|---|------|------|
| 17 | `frontend/package.json` `markdown-it: ^14.1.0` | 删除（项目实际用 `marked` + `dompurify`） |

### 2.7 未跟踪但应清理的临时文件（**2 个**）

| # | 文件 | 处理 |
|---|------|------|
| 18 | `backend/test_metrics.py` | 保留作为开发工具（不 commit），或移动到 `backend/tests/test_metrics.py` |
| 19 | `newplan.md` | 保留作为内部文档，或归档到 `docs/` |

---

## 3. DB Schema 残留（**不动**，只标注）

| 表.列 | 当前状态 | 建议 |
|------|----------|------|
| `evaluation_results.ragas_scores` | 不再写入，但列还在 | 保留（向后兼容，查询历史数据） |
| `evaluation_results.ragas_error` | 不再写入，但列还在 | 保留（向后兼容） |

> 真正清理需要写新 alembic 迁移 + 备份，风险较高，**本次不做**

---

## 4. .gitignore 重写

### 当前问题
- 缺 `*.sqlite3` / `*.db`（部分）
- 缺 `*.pyo` / `*.pyd`
- 缺 `*.bak` / `*.tmp` / `*.swp`（部分）
- 缺 `.env.*.local`（多个本地 env 变体）
- 缺 `backend/data/uploads/`（用户上传文件）
- 缺 `backend/data/chromadb/`（ChromaDB 持久化数据）
- 缺 `*.log` 已存在但位置不好
- 没排除 `__pycache__/` 在所有子目录
- `.codegraph/`、`.reasonix/` 不知道是不是真的用

### 重写后（最终版 .gitignore）
```gitignore
# ============================================
# 操作系统
# ============================================
.DS_Store
Thumbs.db
desktop.ini
ehthumbs.db
*.swp
*.swo
*~

# ============================================
# IDE / 编辑器
# ============================================
.idea/
.vscode/
*.iml
*.code-workspace
.cursor/
.aider*

# ============================================
# Python 编译/缓存
# ============================================
__pycache__/
**/__pycache__/
*.py[cod]
*.pyo
*.pyd
*$py.class
*.so
*.egg-info/
.eggs/
dist/
build/
*.egg
*.whl
.pytest_cache/
.mypy_cache/
.ruff_cache/

# ============================================
# 虚拟环境
# ============================================
venv/
.venv/
env/
.python-version

# ============================================
# 环境变量（含密钥，禁止提交）
# ============================================
.env
.env.local
.env.*.local
backend/.env
backend/.env.local
backend/.env.*.local
!.env.example

# ============================================
# 数据库 / SQLite
# ============================================
*.db
*.sqlite
*.sqlite3
*.sql
backend/test.db
backend/test_chromadb/

# ============================================
# 后端运行时数据（用户上传 / 向量库 / 报告）
# ============================================
backend/data/
backend/reports/
backend/uploads/
!backend/data/.gitkeep
!backend/reports/.gitkeep

# ============================================
# 临时文件 / 备份
# ============================================
*.bak
*.tmp
*.orig
*.rej
*.log
logs/

# ============================================
# 迁移脚本临时产物（运行时生成，已在 gitignore）
# ============================================
backend/test_metrics.py
backend/diag_*.py

# ============================================
# 前端
# ============================================
frontend/node_modules/
frontend/dist/
frontend/.vite/
frontend/.cache/
frontend/.nuxt/
frontend/.next/
frontend/.env
frontend/.env.local

# ============================================
# 覆盖率 / 文档构建
# ============================================
.coverage
htmlcov/
coverage.xml
.tox/
docs/_build/

# ============================================
# 工具生成
# ============================================
.codegraph/
.reasonix/
reasonix.toml
*.local.json
```

---

## 5. 模块结构重构

### 5.1 目标结构（删除 + 移动后）

```
d:\HHHUBS\clone\knoword\
├── README.md                    # 重写
├── newplan.md                   # 保留（历史计划）
├── start.py                     # 保留（启动脚本）
├── .gitignore                   # 重写
├── .gitattributes
│
├── backend/
│   ├── .env.example             # 清理 RAGAS 注释
│   ├── requirements.txt         # (不动)
│   ├── alembic.ini              # (不动)
│   ├── alembic/                 # (不动)
│   │   ├── env.py
│   │   ├── script.py.mako
│   │   └── versions/
│   ├── app/
│   │   ├── main.py              # (不动)
│   │   ├── config.py            # 删 USE_RAGAS
│   │   ├── __init__.py          # (空，删或留)
│   │   │
│   │   ├── api/                 # 路由（保留）
│   │   │   ├── auth.py
│   │   │   ├── chat.py          # 改：去 core.llm 依赖
│   │   │   ├── documents.py
│   │   │   ├── knowledge_base.py
│   │   │   ├── admin.py
│   │   │   ├── eval.py
│   │   │   └── health.py
│   │   │
│   │   ├── core/                # **瘦身**：只剩 security
│   │   │   └── security.py      # (不动)
│   │   │
│   │   ├── db/                  # (不动)
│   │   │   └── database.py
│   │   │
│   │   ├── middleware/          # (不动)
│   │   │   └── logging.py
│   │   │
│   │   ├── models/              # (不动)
│   │   │   ├── models.py
│   │   │   └── eval_models.py
│   │   │
│   │   ├── schemas/             # (不动)
│   │   │   ├── schemas.py
│   │   │   └── eval_schemas.py
│   │   │
│   │   └── services/
│   │       ├── chunking/        # ★ Factory（保留）
│   │       ├── embedding/       # ★ Factory（保留）
│   │       ├── llm_provider/    # ★ Factory（保留）
│   │       ├── rerank/          # ★ Factory（保留）
│   │       ├── eval/            # ★ 评估系统（保留）
│   │       │
│   │       ├── retrieval/       # **删 graph_retrieval.py**
│   │       │   ├── base.py
│   │       │   ├── vector_retrieval.py
│   │       │   ├── bm25_retrieval.py
│   │       │   ├── rerank_retrieval.py
│   │       │   ├── factory.py   # 删 graph 注册
│   │       │   └── pipeline.py  # **新建**：合并原 retrieval_pipeline.py
│   │       │
│   │       ├── vectorstore/     # **新建目录**：把 vectorstore.py 移入
│   │       │   ├── __init__.py  # 导出旧函数
│   │       │   └── client.py    # 原 vectorstore.py 内容
│   │       │
│   │       ├── parser.py        # (不动)
│   │       ├── document_processor.py  # (不动)
│   │       │
│   │       └── retrieval_pipeline.py  # **删除**（合并到 retrieval/pipeline.py）
│   │
│   ├── data/                    # 用户上传 + ChromaDB（gitignore）
│   ├── reports/                 # 评估报告（gitignore）
│   ├── tests/
│   │   ├── conftest.py          # (不动)
│   │   ├── test_auth.py         # (不动)
│   │   ├── test_chat.py         # **重写**：去掉不存在的引用
│   │   └── test_metrics.py      # **新增**：从 backend/test_metrics.py 移入
│   ├── test_metrics.py          # **删除**（移到 tests/）
│   └── migrate_eval_data.py     # **保留**（一次性脚本，已 git tracked）
│
└── frontend/
    ├── package.json             # 删 markdown-it
    ├── package-lock.json
    ├── vite.config.js
    ├── index.html
    └── src/
        ├── App.vue              # (不动)
        ├── main.js              # (不动)
        ├── api/index.js         # (不动)
        ├── router/index.js      # (不动)
        ├── stores/user.js       # (不动)
        ├── styles/global.css    # (不动)
        └── views/               # (不动)
```

### 5.2 关键变化

| 变化 | 说明 |
|------|------|
| `app/core/` 只剩 `security.py` | 删 `llm.py` / `embeddings.py` |
| `app/services/retrieval_pipeline.py` 删除 | 逻辑合并到 `app/services/retrieval/pipeline.py` |
| `app/services/vectorstore.py` → `app/services/vectorstore/client.py` | 风格统一（包式） |
| `app/services/retrieval/graph_retrieval.py` 删除 | factory 不再注册 graph |
| `app/services/retrieval/factory.py` 简化 | 去掉 graph import |
| `app/api/chat.py` 改 1 行 | 删 `from app.core.llm import get_llm`，改用 `get_llm_provider` |
| `app/api/eval.py` 改 import | `vectorstore` 改从 `services.vectorstore` 导入 |
| `app/api/health.py` 改 import | 同上 |
| `app/api/knowledge_base.py` 改 import | 同上 |
| `app/api/admin.py` 改 import | 同上 |
| `app/main.py` 改 import | 同上 |
| `app/services/eval/runner.py` 改 import | 同上 |
| `app/services/eval/dataset_builder.py` 改 import | 同上 |
| `app/services/retrieval/vector_retrieval.py` 改 import | 同上 |
| `app/services/retrieval/rerank_retrieval.py` 改 import | 同上 |
| `app/services/retrieval/bm25_retrieval.py` 改 import | 同上 |

---

## 6. 实施步骤

### Phase 1：删死代码（无风险）
1. 删除 §2.1 列表中的 10 个空文件 / 完全无引用文件
2. 删除 §2.6 的 `markdown-it` 依赖
3. 删除 §2.4 的 `USE_RAGAS` 配置
4. 清理 §2.4 的 `.env.example` 注释
5. 删除 §2.3 的损坏测试 `test_chat.py`（或先备份为 `test_chat.py.bak`）
6. 删除 `app/services/retrieval/graph_retrieval.py`
7. 修改 `app/services/retrieval/factory.py` + `__init__.py` 去掉 graph
8. 修改 `app/api/chat.py` 去掉 `from app.core.llm import get_llm` → 用 `get_llm_provider`
9. 删除 `app/core/llm.py` 和 `app/core/embeddings.py`
10. 跑一遍 `python -c "from app.main import app"` + `pytest tests/test_auth.py` 验证

### Phase 2：模块结构重构（中等风险）
11. 新建 `app/services/vectorstore/__init__.py` + `client.py`（内容从 `vectorstore.py` 搬）
12. 改所有引用 `app.services.vectorstore` 的文件为 `app.services.vectorstore`
13. 删除 `app/services/vectorstore.py`
14. 把 `app/services/retrieval_pipeline.py` 内容合并到 `app/services/retrieval/pipeline.py`
15. 改 `app/api/chat.py` 的 `from app.services.retrieval_pipeline import prepare_sources` → `from app.services.retrieval.pipeline import prepare_sources`
16. 删除 `app/services/retrieval_pipeline.py`
17. 跑全套验证

### Phase 3：清理 gitignore + 临时文件
18. 重写 `.gitignore`
19. 把 `backend/test_metrics.py` 移到 `backend/tests/test_metrics.py`
20. 把 `backend/diag_*.py` 等临时脚本删除（如有）

### Phase 4：文档更新
21. 重写 `README.md`（移除 RAGAS 相关 / LLM-as-Judge 内容 / 改文件树 / 改依赖列表）
22. 更新 `start.bat` 引用（不存在 → 改用 `python start.py`）

### Phase 5：验证 + Commit
23. 完整 import 测试：`from app.main import app`
24. 跑 `pytest backend/tests/test_auth.py` 验证认证
25. 跑 `pytest backend/tests/test_metrics.py` 验证评估
26. 分 3 次 commit：
    - Commit 1: 删死代码（Phase 1）
    - Commit 2: 模块结构重构（Phase 2）
    - Commit 3: gitignore + 文档（Phase 3+4）

---

## 7. 风险评估

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| 删 `core/llm.py` 后某处还在 import | 低 | 中 | 全局 grep 验证（已做） |
| `vectorstore` 路径迁移漏改一处 | 中 | 高 | 改前 grep 所有 import |
| `retrieval_pipeline` 合并后逻辑丢失 | 低 | 中 | 行为对比验证 |
| 删 graph_retrieval 后 UI 上仍可选 | 中 | 低 | 前端 `graph` 选项也要删 |
| 测试 `test_chat.py` 重写引入新 bug | 中 | 低 | 只删坏 case，留 happy path |

---

## 8. 不在本次范围

- DB 迁移清理（`ragas_scores` / `ragas_error` 列删除）
- 前端 UI 全面重写
- 增加新功能
- 添加新测试覆盖率（auth + metrics 已够）

---

## 9. 等用户确认

**请告诉我**：
- ✅ 计划是否同意
- ⚙️ 有没有想调整的范围
- 🚦 下达"开始"指令
