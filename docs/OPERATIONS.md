# Knoword 运维指南

> 适合：运维、DBA、部署到生产的人
> 配套：[README.md](../README.md)（项目入口）· [ARCHITECTURE.md](./ARCHITECTURE.md) · [API.md](./API.md)

---

## 1. 环境要求

### 1.1 软件版本

| 软件 | 最低 | 推荐 | 备注 |
|------|------|------|------|
| Python | 3.10 | 3.11+ | 项目用 `from __future__ import annotations` 风格 |
| Node.js | 18 | 20 LTS | Vite 5 要求 |
| PostgreSQL | 14 | 16 | 用了 `NULLS NOT DISTINCT`（PG 15+）|
| Ollama | 0.3+ | latest | 本地 embedding 才需要 |
| Git | 2.30+ | latest | |
| 磁盘 | 20 GB | 100 GB+ | 每 GB 文档约 100-200 MB 向量库 |
| 内存 | 4 GB | 8 GB+ | 本地 HF embedding + rerank 推理时占内存 |

### 1.2 网络要求

**出站**：
- `https://api.xiaomimimo.com` — MiMo LLM（默认）
- `https://api.deepseek.com` — DeepSeek（可选）
- `https://open.bigmodel.cn` — GLM 智谱（可选）
- `https://api.siliconflow.cn` — SiliconFlow（可选）
- `https://huggingface.co` — HF 模型下载（首次）

**入站**：仅 8000（后端）+ 5173（前端开发）。

---

## 2. 环境变量完整说明

> 完整模板：[backend/.env.example](../backend/.env.example)
> 复制：`cp backend/.env.example backend/.env`

### 2.1 必填

| 变量 | 默认 | 影响 | 备注 |
|------|------|------|------|
| `MIMO_API_KEY` | — | LLM 默认 + LLM judge | 小米 MiMo（https://api.xiaomimimo.com）|
| `JWT_SECRET_KEY` | 启动时随机生成 | 全部 JWT 签名 | **生产必改**：32+ 字符随机 |
| `ADMIN_USERNAME` | `admin` | 首次启动创建管理员 | 改后只影响新部署 |
| `ADMIN_PASSWORD` | `admin123` | 首次启动创建管理员 | **生产必改** |
| `ADMIN_EMAIL` | `admin@local` | 管理员邮箱 | |
| `HF_CACHE_DIR` | `C:\Users\<user>\.cache\huggingface\hub` | 本地 HF 模型缓存 | 多机共享见 §5 |
| `DATABASE_URL` | `postgresql+asyncpg://rag_user:rag_password@localhost:5432/rag_kb` | SQLAlchemy 连接 | |

### 2.2 推荐

| 变量 | 默认 | 说明 |
|------|------|------|
| `DEEPSEEK_API_KEY` | — | DeepSeek（性能比 MiMo 好，Cost 更低）|
| `SILICONFLOW_API_KEY` | — | 云端 embedding + rerank，免本地推理 |
| `HF_OFFLINE` | `0` | 设 `1` 强制离线（多机部署时用共享缓存）|
| `HF_ENDPOINT` | `https://huggingface.co` | 镜像可设 `https://hf-mirror.com` |
| `DEFAULT_EVAL_CONCURRENCY` | `4` | 评估并发数；调高加速但容易触发 LLM rate limit |
| `CORS_ORIGINS` | `http://localhost:5173,http://localhost:3000` | 生产改成实际前端域名 |

### 2.3 可选 / 高级

| 变量 | 默认 | 说明 |
|------|------|------|
| `MIMO_BASE_URL` | `https://api.xiaomimimo.com/v1` | |
| `MIMO_MODEL` | `mimo-v2.5-pro` | 默认生成模型 |
| `MIMO_LITE_MODEL` | `mimo-v2.5` | LLM judge 默认 |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com/v1` | |
| `DEEPSEEK_MODEL` | `deepseek-v4-flash` | |
| `GLM_API_KEY` | — | 智谱 |
| `GLM_BASE_URL` | `https://open.bigmodel.cn/api/paas/v4` | |
| `GLM_MODEL` | `GLM-4.5-flash` | ⚠️ 此模型名可能不存在，建议改 `glm-4-flash` |
| `EMBEDDING_DEFAULT_OLLAMA` | `qwen3-embedding:0.6b` | Ollama embedding 默认 |
| `EMBEDDING_DEFAULT_HF` | `Qwen/Qwen3-Embedding-8B` | HF embedding 默认 |
| `EMBEDDING_DEFAULT_SF` | `Qwen/Qwen3-Embedding-8B` | SiliconFlow embedding 默认 |
| `RERANK_DEFAULT_LOCAL` | `BAAI/bge-reranker-base` | 本地 rerank 默认 |
| `RERANK_DEFAULT_SF` | `Qwen/Qwen3-Reranker-4B` | SiliconFlow rerank 默认 |
| `LOG_LEVEL` | `INFO` | Python logging |
| `CHROMA_PERSIST_DIR` | `backend/data/chromadb` | ChromaDB 持久化目录 |
| `UPLOAD_DIR` | `backend/data/uploads` | 上传文件目录 |

---

## 3. 数据库操作

### 3.1 首次部署

```bash
# 1. 创建数据库
psql -U postgres
postgres=# CREATE USER rag_user WITH PASSWORD 'rag_password';
postgres=# CREATE DATABASE rag_kb OWNER rag_user;
postgres=# GRANT ALL PRIVILEGES ON DATABASE rag_kb TO rag_user;
postgres=# \q

# 2. 跑迁移
cd backend
alembic upgrade head

# 3. 验证
psql -U rag_user -d rag_kb -c "\dt"
# 应输出 7-8 张表（users, knowledge_bases, documents, ...）
```

### 3.2 升级 schema

```bash
cd backend
alembic upgrade head
```

⚠️ **必看**：[Alembic 操作 SOP](#6-ormigrations-升级)。

### 3.3 备份

```bash
# 每日凌晨 cron：保留 30 天
pg_dump -U rag_user -h localhost -d rag_kb -F c -f /backup/rag_kb_$(date +%Y%m%d).dump
```

### 3.4 恢复

```bash
# ⚠️ 恢复会覆盖现有数据
pg_restore -U rag_user -h localhost -d rag_kb --clean --if-exists /backup/rag_kb_20260701.dump
```

### 3.5 SQLite 模式（仅测试）

```bash
# 测试用：自动用 sqlite+aiosqlite:///./test.db
# database.py 自动检测 URL 并适配 NullPool
# 不需要装 PG
```

---

## 4. ChromaDB 操作

### 4.1 数据位置

```
backend/data/chromadb/
├── kb_emb_qwen3_embedding_0_6b/   # KB 用 qwen3-embedding:0.6b 的 collection
│   └── chroma.sqlite3 + 向量索引
├── kb_emb_qwen3_embedding_8b/     # KB 用 8B 的 collection
│   └── ...
└── kb_emb_bge_base_zh_v1_5/
    └── ...
```

### 4.2 备份

```bash
# 必须先停后端（避免写入冲突）
# 后端在运行时直接 copy 可能损坏
tar czf chromadb_$(date +%Y%m%d).tar.gz backend/data/chromadb/
```

### 4.3 迁移到新机器

```bash
# 1. 停后端
# 2. 整个 chromadb 目录 copy 过去
scp -r backend/data/chromadb/ user@newserver:/path/to/backend/data/
# 3. .env 保持一致
# 4. 启动后端，验证
```

### 4.4 切换 Embedding 模型

**必须新建 KB**，不能改：

1. UI 创建新 KB，选新 embedding 模型
2. 重新上传所有文档
3. 评估时用新 KB（如果旧 KB 上的评估还在跑，独立完成）

**不推荐**：手动改 collection 名称，**会破坏一致性**。

### 4.5 清理孤立 collection

KB 删除时 ChromaDB collection 不会自动删除磁盘。

```bash
# 列出所有 collection 目录
ls backend/data/chromadb/

# 跟 DB 对比：UI/API 显示的 KB 数量
# 不在 KB 列表里的目录可以手动删
rm -rf backend/data/chromadb/kb_emb_xxx/
```

---

## 5. HF 模型缓存

### 5.1 默认路径

- Windows：`C:\Users\<user>\.cache\huggingface\hub\`
- Linux：`~/.cache/huggingface/hub/`

### 5.2 多机共享（NFS / 软链）

```bash
# NFS mount 后
ln -s /mnt/nfs/huggingface ~/.cache/huggingface

# .env
HF_CACHE_DIR=/mnt/nfs/huggingface/hub
HF_OFFLINE=1   # 强制本地读
```

### 5.3 镜像加速

```bash
# .env
HF_ENDPOINT=https://hf-mirror.com
```

### 5.4 常用模型

| 模型 | 大小 | 用途 |
|------|------|------|
| `Qwen/Qwen3-Embedding-8B` | ~16 GB | 8B embedding（精度高）|
| `qwen3-embedding:0.6b` (Ollama) | ~1.2 GB | 0.6B embedding（速度快）|
| `BAAI/bge-reranker-base` | ~1.1 GB | 本地 rerank（280M）|
| `shibing624/text2vec-base-chinese` | ~400 MB | 中文 base embedding |
| `Qwen/Qwen3-Reranker-4B` | — | **云端** rerank（不走本地）|

---

## 6. ORMigrations 升级

### 6.1 升级步骤

```bash
cd backend
git pull
pip install -r requirements.txt
alembic upgrade head
# 重启后端
```

### 6.2 历史 migration 列表

```bash
alembic history
```

### 6.3 创建新 migration

```bash
# 改完 models/ 后
alembic revision --autogenerate -m "add new column"
# 检查生成的 .py 文件（autogenerate 偶尔漏）
alembic upgrade head
```

⚠️ **autogenerate 不是万能的**：
- enum 改动经常漏
- 复杂 default 表达式需要手动写
- 大表 ALTER TABLE 会锁表（生产谨慎）

### 6.4 回滚

```bash
# 危险：可能丢数据
alembic downgrade -1
```

---

## 7. 生产部署

### 7.1 后端：uvicorn + systemd

```ini
# /etc/systemd/system/knoword-backend.service
[Unit]
Description=Knoword FastAPI
After=network.target postgresql.service

[Service]
Type=simple
User=knoword
WorkingDirectory=/opt/knoword/backend
Environment="PATH=/opt/knoword/backend/venv/bin"
ExecStart=/opt/knoword/backend/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now knoword-backend
sudo systemctl status knoword-backend
```

### 7.2 前端：Vite build + nginx

```bash
cd frontend
npm install
npm run build
# 产物在 dist/
```

```nginx
# /etc/nginx/conf.d/knoword.conf
server {
    listen 80;
    server_name your-domain.com;

    # 前端
    location / {
        root /opt/knoword/frontend/dist;
        try_files $uri $uri/ /index.html;
    }

    # 后端 API 代理
    location /api/ {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # SSE 关键：禁用 buffering
    location /api/chat/stream {
        proxy_pass http://localhost:8000;
        proxy_buffering off;
        proxy_cache off;
        proxy_set_header Connection '';
        proxy_http_version 1.1;
        chunked_transfer_encoding off;
    }
}
```

### 7.3 HTTPS

```bash
sudo certbot --nginx -d your-domain.com
```

### 7.4 防火墙

```bash
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
# 8000 端口不外暴露
```

---

## 8. 监控 & 排查

### 8.1 关键日志位置

```
backend/logs/
├── access_YYYYMMDD.log      # 所有 HTTP 请求（middleware 写）
├── all_YYYYMMDD.log         # access + 业务日志
├── eval.log                 # 评估事件（task 完成/失败、续跑）
├── error_YYYYMMDD.log       # ERROR 级及以上
├── llm.log                  # LLM provider 创建记录
└── migration_*.log          # 评估数据集生成（如果有）
```

### 8.2 实时监控

```bash
# 评估进行中
tail -f backend/logs/eval.log

# LLM 错误
tail -f backend/logs/error_*.log

# 数据库慢查询（需 postgresql.conf 设 log_min_duration_statement=1000）
```

### 8.3 常见错误

#### 8.3.1 `Collection expecting embedding with dimension of 1024, got 4096`

**原因**：ChromaDB collection 与 embedding 模型维度不匹配。

**排查**：
```sql
-- 查 KB 的 embedding_model
SELECT id, name, embedding_model FROM knowledge_bases;
```

```bash
# 查 ChromaDB collection 维度
ls backend/data/chromadb/
```

**修复**：**新建 KB**（不能改），重新上传文档。

#### 8.3.2 `402 Insufficient account balance`

**原因**：MiMo / DeepSeek 余额耗尽。

**解决**：
1. 充值对应账户
2. 后端已经做了断点续传，**无需重启**——点 UI 的「续跑」即可
3. 长期方案：把 LLM judge 改 deepseek（更便宜）

#### 8.3.3 `StringDataRightTruncationError: value too long for type character varying(20)`

**原因**：评估 run 状态字段长度不够（已修，2026-07 commit `11d6f55` + migration `a8b9c0d1e2f3`）。

**解决**：
```bash
cd backend
alembic upgrade head
# 重启后端
```

#### 8.3.4 评估卡在 `progress=0, status=running`

**原因 1**：MiMo 余额耗尽，每个 task 快速 402 失败但没记日志。
**原因 2**：MiMo API 限流，所有并发请求在排队。

**排查**：
```bash
tail -f backend/logs/eval.log
# 应该有 "Task 失败: X, err=..." 行
```

**解决**：停 → 充值 → 续跑。

#### 8.3.5 Vite HMR 改路由不生效

**解决**：`router/index.js` 改动 Vite HMR 不可靠，**Ctrl+C 重启 `npm run dev`**。

#### 8.3.6 ChromaDB 数据写入失败

**排查**：
```bash
# 1. 看磁盘
df -h backend/data/

# 2. 看 ChromaDB 锁文件
ls -la backend/data/chromadb/kb_emb_*/
```

**解决**：删锁文件 `*.lock`（确认没进程在用），重启后端。

#### 8.3.7 HF 模型下载慢 / 失败

```bash
# 1. 镜像
echo 'HF_ENDPOINT=https://hf-mirror.com' >> backend/.env

# 2. 重试
rm -rf $HF_CACHE_DIR/  # 删未完成的
python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('Qwen/Qwen3-Embedding-8B')"
```

#### 8.3.8 PostgreSQL 连接耗尽

```sql
SELECT count(*) FROM pg_stat_activity;
```

如果 > 90% of `max_connections`（默认 100）：
- 评估并发改小：`DEFAULT_EVAL_CONCURRENCY=2`
- 改 PostgreSQL：`max_connections = 200`

#### 8.3.9 JWT 401 但 token 没过期

**原因**：改了 `JWT_SECRET_KEY` 但前端 token 还是旧的。

**解决**：前端重新登录。

---

## 9. 性能调优

### 9.1 评估并发

`.env`：
```bash
DEFAULT_EVAL_CONCURRENCY=4    # 默认
# 高配机器：8
# MiMo 免费账户：2（避免 rate limit）
```

### 9.2 检索 K 值

| 场景 | 建议 K |
|------|--------|
| 单 chunk 答案 | 3-5 |
| 多 chunk 综合答案 | 5-10 |
| 评估指标对比 | 10-20（避免 ceiling effect）|
| 最大 | 50（UI 限制）|

### 9.3 Embedding 模型选择

| 模型 | 维度 | 速度 | 精度 | 适用 |
|------|------|------|------|------|
| `qwen3-embedding:0.6b` (Ollama) | 1024 | ⚡ 快 | 一般 | 大数据量、实时性优先 |
| `Qwen/Qwen3-Embedding-8B` (SiliconFlow) | 4096 | 🐢 慢（云端）| **高** | 精度优先 |

**对比建议**：建 2 个 KB（不同 embedding），跑同一数据集，对比评估。

### 9.4 Chunking 调优

| 场景 | chunk_size | chunk_overlap |
|------|-----------|---------------|
| 长文档综合问答 | 500-1000 | 100-200 |
| 短 QA 对应 | 200-300 | 50 |
| 代码/表格 | 800-1500 | 100-150 |

⚠️ **chunking 策略切换要重新上传所有文档**（chunk_id 改了就映射不上）。

---

## 10. 备份与恢复演练

### 10.1 每周自动备份脚本

```bash
#!/bin/bash
# /opt/knoword/scripts/backup.sh
set -e

BACKUP_DIR=/backup/knoword
DATE=$(date +%Y%m%d)

mkdir -p $BACKUP_DIR/$DATE

# 1. PostgreSQL
pg_dump -U rag_user -d rag_kb -F c \
  -f $BACKUP_DIR/$DATE/rag_kb.dump

# 2. ChromaDB
tar czf $BACKUP_DIR/$DATE/chromadb.tar.gz \
  /opt/knoword/backend/data/chromadb/

# 3. 上传文件（可选，占空间）
tar czf $BACKUP_DIR/$DATE/uploads.tar.gz \
  /opt/knoword/backend/data/uploads/

# 4. 评估报告（重要，不入库但要备份）
tar czf $BACKUP_DIR/$DATE/reports.tar.gz \
  /opt/knoword/backend/reports/

# 5. 清理 30 天前
find $BACKUP_DIR -maxdepth 1 -type d -mtime +30 -exec rm -rf {} \;
```

```bash
chmod +x /opt/knoword/scripts/backup.sh
# crontab -e
0 3 * * 0 /opt/knoword/scripts/backup.sh
```

### 10.2 恢复演练

每季度：
```bash
# 1. 在新机器恢复
mkdir -p /opt/knoword-test
cd /opt/knoword-test

# 2. 拉代码
git clone <repo-url> .
cd backend
pip install -r requirements.txt

# 3. 恢复 PostgreSQL
createdb -U postgres rag_kb_test
pg_restore -U rag_user -d rag_kb_test /backup/20260701/rag_kb.dump

# 4. 恢复 ChromaDB
tar xzf /backup/20260701/chromadb.tar.gz -C /opt/knoword-test/backend/data/

# 5. 启动并验证
cp /backup/knoword-prod.env .env
alembic upgrade head
uvicorn app.main:app --port 8001 &

# 6. 跑健康检查
curl http://localhost:8001/api/system/health
# 验证 KB / 评估结果
```

---

## 11. 安全 checklist

- [ ] `JWT_SECRET_KEY` 用 32+ 字符随机（**不要用默认**）
- [ ] `ADMIN_PASSWORD` 已改（**不要用 admin123**）
- [ ] `CORS_ORIGINS` 改成生产域名
- [ ] `MIMO_API_KEY` 等不进 git（已在 .gitignore）
- [ ] HTTPS 启用（certbot）
- [ ] 后端端口（8000）**不**对外暴露
- [ ] PostgreSQL 密码强（不要 rag_password）
- [ ] HF 模型缓存目录权限 700
- [ ] 评估报告不包含敏感数据（用户可读）

---

## 12. 进一步阅读

- [ARCHITECTURE.md](./ARCHITECTURE.md) — 系统设计、ADR
- [API.md](./API.md) — REST 接口
- [README.md](../README.md) — 项目入口
- HF 文档：https://huggingface.co/docs
- LangChain 文档：https://python.langchain.com/
- ChromaDB 文档：https://docs.trychroma.com/

---

**文档维护**：每次发现新 SOP / 新踩坑必加。
