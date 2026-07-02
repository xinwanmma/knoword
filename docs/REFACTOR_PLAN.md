# 重构计划：文档体系 + .gitignore

> 用户已确认：
> - 范围：仅文档 + .gitignore（不动业务代码）
> - 文档：README / ARCHITECTURE / API / OPERATIONS 四份
> - .gitignore 重点：reports/、临时脚本、.env/缓存、AI 工具痕迹
> - 不为这次重构生成代码内 docstring

---

## Phase 0：先确认 1 个细节（执行前问）

**Q：评估报告 `backend/reports/` 是否继续 gitignore？**
- 选项 A：完全 ignore（现状）— reports/ 下的所有 eval_*.json/md 永远不入库
- 选项 B：选择性入库 — 比如 `reports/samples/` 入库，运行时产生的 reports/ ignore
- 选项 C：完全入库 — 把所有历史报告都 commit，便于回顾（但 reports/ 会越来越胖）

> 默认建议 **A（保持现状）**。若选 B 我会调整目录结构。

---

## Phase 1：清理 + .gitignore 增强

### 1.1 新建 `docs/` 目录

```
docs/
├── README.md              # docs 索引（指向四个主文档）
├── ARCHITECTURE.md        # 架构说明
├── API.md                 # REST 接口文档
└── OPERATIONS.md          # 运维 / 部署 / 迁移
```

### 1.2 重写 `.gitignore`（按用户勾选重点扩写）

新增/调整条目：

```gitignore
# ====== 运行时数据 ======
backend/data/              # chromadb 持久化、uploads（已有）
backend/reports/           # 评估报告（保留 ignore）
backend/logs/              # 日志（已有）

# ====== 后端 ======
# 临时 / 一次性脚本（已存在部分，扩展）
backend/diag_*.py
backend/tmp_*.py
backend/debug_*.py
backend/test_*.py          # 根目录的测试脚本（不是 tests/ 单元测试）
backend/scripts/temp/

# 缓存
.mypy_cache/
.ruff_cache/
.pytest_cache/
backend/.coverage
htmlcov/
*.egg-info/

# ====== 前端 ======
frontend/node_modules/     # 已有
frontend/dist/             # 已有
frontend/.vite/            # 已有
frontend/.env
frontend/.env.local
frontend/.env.*.local

# ====== AI 助手 / 编辑器 ======
.cursor/                   # Cursor
.aider*                    # Aider
.trae/                     # Trae IDE（如果出现）
.trae-cn/                  # Trae-CN
.continue/                 # Continue.dev
.windsurf/                 # Windsurf
.cody/                     # Sourcegraph Cody
.codeium/                  # Codeium
.copilot/                  # GitHub Copilot 缓存（本地）
# 已有：.vscode/ .idea/ *.code-workspace

# ====== 操作系统 / 杂项 ======
.DS_Store Thumbs.db desktop.ini  # 已有
*.swp *.swo *~             # 已有

# ====== 私有/敏感 ======
.env .env.local .env.*.local       # 已有
!.env.example                       # 已有

# ====== 数据库 ======
*.db *.sqlite *.sqlite3            # 已有
backend/test_chromadb/             # 已有
```

### 1.3 检查现状中可能误入的"一次性脚本"（仅记录，不动）

> 这部分**仅作为文档备份**，不删除任何文件（用户没要求）：
> - `backend/migrate_*.py`（4 个）— 历史迁移，建议未来归档到 alembic versions
> - `backend/fix_*.py` / `backend/restore_*.py` / `backend/copy_*.py` / `backend/add_*.py` / `backend/debug_*.py` — 都是手动一次性脚本
> - 决定**保留**这些文件在 git 里（已经是历史），但在新文档里**明确标注"已废弃，仅留档"**。

---

## Phase 2：重写 `README.md`

**结构调整**（基于现状 README，去掉过期内容，补充 2026-07 新增功能）：

1. 顶部：项目简介 + 核心特性 + 状态徽章
2. 快速开始（基于 `start.py` 的 --check 模式）
3. 技术栈（含 HF、Ollama、SiliconFlow、MiMo/DeepSeek/GLM）
4. **评估指标章节**：保留 8 指标表格，**新增"评估断点续传"**说明
5. 项目结构（基于 ls 真实树形图，**补 backend/scripts/**）
6. 必填环境变量（精简表，详细见 OPERATIONS.md）
7. 测试说明
8. 评估中心使用流程
9. 文档导航：链接到 docs/{ARCHITECTURE,API,OPERATIONS}.md
10. 已知限制 / FAQ
11. License

**新增要点**（2026-07 期间出现的）：
- 多 embedding 模型对比（已支持，按 KB 绑定）
- ChromaDB collection 按 embedding 模型分库（`kb_emb_{name}`）
- 断点续传 + 评估空状态补跑
- judge_error task 也能续跑
- status String(30) 修复

---

## Phase 3：新建 `docs/ARCHITECTURE.md`

**目标读者**：新加入的开发者、要做二次开发的人

**结构**：

1. **系统总览**（一张 ASCII 流程图）
   ```
   Browser ──► Vue3 (Element Plus) ──► FastAPI ──► LangChain
                                            ├── ChromaDB
                                            ├── PostgreSQL (Alembic)
                                            └── LLM Providers
                                                 ├── MiMo
                                                 ├── DeepSeek
                                                 └── GLM
   ```

2. **后端模块图**（按 `app/services/*/` 5 大 factory）
   - Embedding Factory
   - LLM Provider Factory
   - Rerank Factory
   - Retrieval Strategy Factory
   - Chunking Strategy Factory

3. **数据模型**（关键表 ER 简图）
   - users / knowledge_bases / documents / chunks（隐式，在 ChromaDB）
   - evaluation_runs / evaluation_datasets / evaluation_results

4. **关键流程**（4 个序列图）
   - 文档上传 → 分块 → embedding → 存 ChromaDB
   - 用户提问 → retrieval → rerank → generation → SSE 流式
   - 创建评估 → 展开 task → 并发跑 → 报告生成
   - 续跑逻辑：completed_keys 计算 + UPSERT

5. **关键决策记录（ADR）**
   - 选 LangChain 1.x 不用 0.x
   - ChromaDB collection 按 embedding 分库
   - 评估用 PG 写 OLTP + ChromaDB 读向量
   - 5 个 Strategy 走 Factory 模式而不是注册中心

6. **可扩展点**
   - 加新 LLM provider：实现 `LLMProvider` + 在 factory.py 加一行
   - 加新 embedding：实现 `EmbeddingProvider` + factory.py
   - 加新评估指标：在 `eval/metrics.py` 注册

---

## Phase 4：新建 `docs/API.md`

**目标读者**：前端开发、API 集成方

**结构**（按 7 个 router 分组）：

| 路由前缀 | 端点数 | 说明 |
|---|---|---|
| `/api/auth` | 3 | 注册 / 登录 / 当前用户 |
| `/api/chat` | 4 | SSE 流式对话 + 历史 |
| `/api/knowledge-base` | 5 | KB CRUD |
| `/api/documents` | 5 | 文档上传/重索引/删除 |
| `/api/eval` | 11 | 评估中心全套 |
| `/api/admin/*` | 7 | 管理后台（需 admin JWT）|
| `/api/system` | (待查) | 健康检查 / 可用模型 |

**每个端点文档格式**：
```markdown
### POST /api/auth/login
登录获取 JWT

**Request Body**:
```json
{ "username": "admin", "password": "..." }
```

**Response 200**:
```json
{ "access_token": "eyJ...", "token_type": "bearer" }
```

**Errors**:
- 401 用户名或密码错误
- 403 账号被禁用
```

**特别说明**：
- SSE 端点 (`POST /api/chat`)：请求格式 + SSE 事件类型
- 评估端点：列出 query 参数 + 响应字段（如 `enabled_metrics` 数组结构）
- Admin 端点：强调 `requiresAdmin` 守卫

---

## Phase 5：新建 `docs/OPERATIONS.md`

**目标读者**：运维、DBA、部署到生产的人

**结构**：

1. **环境要求**
   - Python 3.10+, Node 18+
   - PostgreSQL 14+ (推荐 16)
   - 4 GB+ RAM（HF embedding + rerank 本地推理）
   - 磁盘：每 GB 文档约 100-200 MB 向量库

2. **环境变量完整说明**（基于 `.env.example` 每项展开）
   - 必填项 + 可选项 + 默认值
   - 各项的影响范围（哪段代码会读）

3. **数据库操作**
   - 首次部署：`alembic upgrade head`
   - 创建 rag_user 和 rag_kb 库（带 SQL 示例）
   - 备份：`pg_dump` SOP
   - 恢复：`pg_restore` SOP

4. **ChromaDB 操作**
   - 数据位置：`backend/data/chromadb/`
   - 备份：直接 copy 目录（关后端时）
   - 迁移到新机器：copy + verify
   - 按 embedding 模型分库（`kb_emb_*` 目录）的迁移 SOP

5. **HF 模型缓存**
   - 默认路径：`<user_home>/.cache/huggingface/hub/`
   - 多机共享：NFS / 软链
   - 离线模式：`HF_OFFLINE=1`

6. **生产部署**
   - 后端：uvicorn + gunicorn / 直接 systemd
   - 前端：vite build + nginx
   - 反向代理示例
   - HTTPS 建议

7. **监控 & 排查**
   - 关键日志位置（`backend/logs/{eval,llm,access,error}_*.log`）
   - 常见错误及解法（基于本项目实际踩过的坑）：
     - "Collection expecting embedding with dimension of 1024" → 检查 KB embedding 是否一致
     - "402 Insufficient account balance" → 充值或换 LLM judge
     - "status StringDataRightTruncationError" → 已修，升级即可
     - "Vite HMR 路由不刷新" → 重启前端

8. **数据迁移 / 升级**
   - 跨版本升级步骤
   - 评估数据从 1.0 升到 1.1 时的字段兼容
   - 一次性迁移脚本列表（`backend/migrate_*.py`）

9. **性能调优**
   - 评估并发 `DEFAULT_EVAL_CONCURRENCY`
   - 检索 K 值与精度的 tradeoff
   - Embedding 模型选择（0.6B vs 8B）

10. **备份 / 恢复演练**
    - 每周一次：pg_dump + chromadb tar
    - 季度一次：完整恢复演练

---

## Phase 6：验证 + 提交

1. **目录结构**（执行后应一致）：
   ```
   /
   ├── README.md
   ├── .gitignore
   ├── start.py
   ├── docs/
   │   ├── README.md
   │   ├── ARCHITECTURE.md
   │   ├── API.md
   │   └── OPERATIONS.md
   ├── backend/
   │   └── ...（不变）
   └── frontend/
       └── ...（不变）
   ```

2. **交叉链接检查**：
   - README.md → docs/ARCHITECTURE.md / API.md / OPERATIONS.md
   - docs/README.md → 各文档
   - OPERATIONS.md → FAQ 链回 README

3. **commit message**：
   ```
   docs: comprehensive README + 4 docs + tightened .gitignore
   
   - Rewrite README.md to reflect 2026-07 features
   - Add docs/ARCHITECTURE.md (system design, 5 factories, key flows)
   - Add docs/API.md (all 39 endpoints with examples)
   - Add docs/OPERATIONS.md (deploy, backup, troubleshooting)
   - Add docs/README.md (index)
   - Tighten .gitignore (AI tools, .trae-cn, frontend .env, etc.)
   ```

---

## 工作量估算

| Phase | 内容 | 时间 |
|---|---|---|
| 0 | 确认 reports/ 策略 | 1 个问题 |
| 1 | .gitignore + docs/ 目录 | 10 min |
| 2 | README.md | 20 min |
| 3 | ARCHITECTURE.md | 30 min |
| 4 | API.md（39 端点）| 40 min |
| 5 | OPERATIONS.md | 30 min |
| 6 | 验证 + commit | 10 min |
| **合计** | | **~2.5 小时** |

---

## 不在本次范围

- ❌ 不重构 backend/app/services/ 的模块边界
- ❌ 不删除任何文件
- ❌ 不写代码内 docstring
- ❌ 不改 backend/scripts/ 目录结构
- ❌ 不改 start.py

---

请确认：
1. Phase 0 的 Q（reports/ 策略）选择 A/B/C？
2. 是否同意按上述 6 阶段执行？
3. 是否有想加 / 想去掉的内容？
