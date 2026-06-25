# 📋 RAG 评估系统改造 — newplan.md

> **最后更新**：2026-06-25
> **状态**：⏸ 等待用户最终确认（评估系统优化版）

---

## 1. 🎯 总体目标

将当前 RAG 项目改造为**可配置、可对比、可评估**的研究/实验平台。

### 五大目标

| # | 目标 | 状态 |
|---|------|------|
| 1 | 从 LangGraph 改为 LangChain | 🔜 待执行 |
| 2 | 代码模块化（Provider/Strategy 模式） | 🔜 待执行 |
| 3 | 知识库配置增强 + 权限调整 | 🔜 待执行 |
| 4 | 多 Provider 接入（Embedding × 4 / LLM × 3） | 🔜 待执行 |
| 5 | 评估系统（数据集 + 多维度 + 报告） | 🔜 待执行 |

---

## 2. 📦 Phase 1: LangGraph → LangChain

### 目标
删除 LangGraph 依赖，改用 LangChain Expression Language (LCEL)。

### 改动

| 文件 | 改动 |
|------|------|
| `services/agent_graph.py` | 简化为 retrieval 编排函数，删除 StateGraph |
| `api/chat.py` | 改用 LCEL `Runnable` 链：`retriever \| prompt \| llm` |
| `requirements.txt` | 移除 `langgraph`，保留 `langchain-core` |

### 验证
- 重启后端，对话功能完整
- SSE 流式仍正常
- 历史对话仍可加载

---

## 3. 📦 Phase 2: 代码模块化

### 3.1 Embedding 模块化

#### 目录结构
```
app/services/embedding/
├── __init__.py
├── base.py                  # EmbeddingProvider 抽象基类
├── factory.py               # 根据 model 字符串创建实例
├── ollama_provider.py       # 现有：qwen3-embedding:0.6b
├── huggingface_provider.py  # 新：shibing624/text2vec-base-chinese (本地离线)
└── siliconflow_provider.py  # 新：Qwen3-Embedding-8B/4B (API)
```
> 不再在项目内创建 `text2vec_local/` 目录，模型统一缓存在
> `C:\Users\13596\.cache\huggingface\hub\`（HF 官方默认缓存目录）

#### 抽象基类 `base.py`
```python
from abc import ABC, abstractmethod
from typing import Protocol

class EmbeddingProvider(ABC):
    """Embedding 提供方统一接口。"""
    
    @property
    @abstractmethod
    def model_name(self) -> str: ...
    
    @property
    @abstractmethod
    def dimension(self) -> int: ...
    
    @abstractmethod
    async def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    
    @abstractmethod
    async def embed_query(self, text: str) -> list[float]: ...
```

#### HuggingFace Provider（**关键：离线加载**）

**问题**：默认 `sentence-transformers` 会从 HuggingFace 下载，首次使用卡死。

**解决方案**：
1. 模型统一缓存在 `C:\Users\13596\.cache\huggingface\hub\`（HF 官方默认缓存目录）
2. 启动时检查该目录是否有 `models--shibing624--text2vec-base-chinese` 子目录
3. 若不存在 → 自动下载到该目录（一次性）
4. 之后**始终从本地加载**，不联网
5. 设置环境变量 `TRANSFORMERS_OFFLINE=1` / `HF_DATASETS_OFFLINE=1`（加载后强制离线）

```python
# huggingface_provider.py
class HuggingFaceProvider(EmbeddingProvider):
    # HF 官方默认缓存目录（Windows）
    HF_CACHE_DIR = Path("C:/Users/13596/.cache/huggingface/hub")
    # 模型在该目录下的子目录名
    LOCAL_DIR = HF_CACHE_DIR / "models--shibing624--text2vec-base-chinese"

    def __init__(self, model_id: str = "shibing624/text2vec-base-chinese"):
        # 1. 确保本地有模型（首次自动下载到 HF 缓存目录）
        if not self.LOCAL_DIR.exists():
            self._download_model(model_id)

        # 2. 强制 HF 走本地缓存 + 离线模式
        os.environ["HF_HOME"] = str(self.HF_CACHE_DIR.parent)
        os.environ["TRANSFORMERS_CACHE"] = str(self.HF_CACHE_DIR)
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        os.environ["HF_DATASETS_OFFLINE"] = "1"
        os.environ["HF_HUB_OFFLINE"] = "1"

        # 3. 从本地加载（不再联网）
        from sentence_transformers import SentenceTransformer
        self._model = SentenceTransformer(str(self.LOCAL_DIR))
        self._model_name = "shibing624/text2vec-base-chinese"
        self._dimension = self._model.get_sentence_embedding_dimension()

    def _download_model(self, model_id: str):
        """首次下载到 HF 官方缓存目录（仅一次）。"""
        # 下载前先关闭离线模式
        os.environ.pop("TRANSFORMERS_OFFLINE", None)
        os.environ.pop("HF_HUB_OFFLINE", None)
        from huggingface_hub import snapshot_download
        snapshot_download(
            repo_id=model_id,
            cache_dir=str(self.HF_CACHE_DIR),
        )

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._model.encode(texts, normalize_embeddings=True).tolist()

    async def embed_query(self, text: str) -> list[float]:
        return self._model.encode([text], normalize_embeddings=True)[0].tolist()
```

#### Factory `factory.py`
```python
EMBEDDING_REGISTRY = {
    "qwen3-embedding:0.6b": OllamaProvider,
    "shibing624/text2vec-base-chinese": HuggingFaceProvider,
    "Qwen/Qwen3-Embedding-8B": SiliconFlowProvider,  # 8B 版本
    "Qwen/Qwen3-Embedding-4B": SiliconFlowProvider,  # 4B 版本
}

def get_embedding_provider(model_id: str) -> EmbeddingProvider:
    if model_id not in EMBEDDING_REGISTRY:
        raise ValueError(f"Unknown embedding model: {model_id}")
    return EMBEDDING_REGISTRY[model_id]()
```

### 3.2 LLM 模块化

#### 目录结构
```
app/services/llm_provider/
├── __init__.py
├── base.py                  # LLMProvider 抽象基类
├── factory.py               # 创建实例
├── mimo.py                  # mimo-v2.5 / mimo-v2.5-pro
├── deepseek.py              # deepseek-v4-flash
└── glm.py                   # GLM-4.5-flash
```

#### 接口
```python
class LLMProvider(ABC):
    @abstractmethod
    async def astream(self, messages: list) -> AsyncIterator[str]: ...
    
    @abstractmethod
    async def ainvoke(self, messages: list) -> str: ...
```

> 实现细节：三个 provider 实际上都是 `ChatOpenAI` 包装（OpenAI 兼容），所以工厂方法按 base_url 区分。

#### Factory
```python
LLM_REGISTRY = {
    "mimo-v2.5": (settings.MIMO_BASE_URL, settings.MIMO_API_KEY, settings.MIMO_MODEL),
    "mimo-v2.5-pro": (settings.MIMO_BASE_URL, settings.MIMO_API_KEY, "mimo-v2.5-pro"),
    "deepseek-v4-flash": (settings.DEEPSEEK_BASE_URL, settings.DEEPSEEK_API_KEY, settings.DEEPSEEK_MODEL),
    "GLM-4.5-flash": (settings.GLM_BASE_URL, settings.GLM_API_KEY, settings.GLM_MODEL),
}
```

### 3.3 Chunking 模块化

#### 目录结构
```
app/services/chunking/
├── __init__.py
├── base.py
├── factory.py
├── fixed_size.py           # 固定字符大小
├── recursive.py            # 递归字符（langchain RecursiveCharacterTextSplitter）
└── semantic.py             # langchain_experimental SemanticChunker
```

### 3.4 Retrieval 模块化

#### 目录结构
```
app/services/retrieval/
├── __init__.py
├── base.py
├── factory.py
├── vector_retrieval.py     # 纯向量
├── bm25_retrieval.py       # BM25（pickle 索引）
├── rerank_retrieval.py     # 向量 + Rerank（按 Rerank 重排）
└── graph_retrieval.py      # Microsoft GraphRAG
```

#### 3.4.1 Rerank Provider 模块化（**新增**）

> Rerank 不是检索的"一种"，而是检索流程的一个**后处理步骤**。
> `rerank_retrieval.py` 内部按用户选定的 rerank provider 排序。

```
app/services/rerank/
├── __init__.py
├── base.py                       # RerankProvider 抽象基类
├── factory.py                    # 根据 model 字符串创建实例
├── huggingface_provider.py       # 本地离线 rerank（HF 缓存目录）
└── siliconflow_provider.py       # Qwen/Qwen3-Reranker-4B（API）
```

**抽象基类 `base.py`**：
```python
from abc import ABC, abstractmethod
from typing import List, Tuple

class RerankProvider(ABC):
    """Rerank 提供方统一接口。"""

    @property
    @abstractmethod
    def model_name(self) -> str: ...

    @abstractmethod
    async def rerank(
        self,
        query: str,
        documents: List[str],
        top_k: int = 5,
    ) -> List[Tuple[int, float]]:
        """
        返回按相关度降序的 (原始 index, score) 列表。
        原始 index 是 documents 列表中的下标，便于回溯。
        """
        ...
```

**HuggingFace Provider（**本地离线**）**：

```python
# huggingface_provider.py
class HuggingFaceRerankProvider(RerankProvider):
    # 与 embedding 共享同一 HF 缓存目录
    HF_CACHE_DIR = Path("C:/Users/13596/.cache/huggingface/hub")
    # 默认本地 rerank 模型（用户可在 .env 中覆盖）
    DEFAULT_MODEL_ID = "BAAI/bge-reranker-base"

    def __init__(self, model_id: str = None):
        model_id = model_id or settings.HF_RERANK_MODEL
        # HF 缓存目录下的子目录名
        local_dir = self.HF_CACHE_DIR / f"models--{model_id.replace('/', '--')}"

        # 首次自动下载
        if not local_dir.exists():
            self._download_model(model_id)

        # 强制离线
        os.environ["HF_HOME"] = str(self.HF_CACHE_DIR.parent)
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        os.environ["HF_HUB_OFFLINE"] = "1"

        # 加载 cross-encoder
        from sentence_transformers import CrossEncoder
        self._model = CrossEncoder(str(local_dir))
        self._model_name = model_id

    async def rerank(self, query, documents, top_k=5):
        # CrossEncoder 一次性打分所有 (query, doc) 对
        pairs = [[query, d] for d in documents]
        scores = self._model.predict(pairs)  # numpy array
        # 按分数降序排序，取 top_k
        ranked = sorted(
            enumerate(scores),
            key=lambda x: float(x[1]),
            reverse=True,
        )[:top_k]
        return [(idx, float(score)) for idx, score in ranked]

    def _download_model(self, model_id):
        os.environ.pop("TRANSFORMERS_OFFLINE", None)
        os.environ.pop("HF_HUB_OFFLINE", None)
        from huggingface_hub import snapshot_download
        snapshot_download(repo_id=model_id, cache_dir=str(self.HF_CACHE_DIR))
```

**SiliconFlow Provider（`Qwen/Qwen3-Reranker-4B`）**：

```python
# siliconflow_provider.py
import httpx

class SiliconFlowRerankProvider(RerankProvider):
    """调用 SiliconFlow 官方的 rerank 接口。"""
    ENDPOINT = "https://api.siliconflow.cn/v1/rerank"

    def __init__(self, model_id: str = "Qwen/Qwen3-Reranker-4B"):
        self._model_id = model_id
        self._api_key = settings.SILICONFLOW_API_KEY
        self._model_name = model_id

    async def rerank(self, query, documents, top_k=5):
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                self.ENDPOINT,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self._model_id,
                    "query": query,
                    "documents": documents,
                    "top_n": top_k,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            # data["results"] = [{"index": 0, "relevance_score": 0.95}, ...]
            return [
                (r["index"], r["relevance_score"])
                for r in data["results"]
            ]
```

**Factory `factory.py`**：
```python
RERANK_REGISTRY = {
    "BAAI/bge-reranker-base": HuggingFaceRerankProvider,         # 本地默认
    "Qwen/Qwen3-Reranker-4B": SiliconFlowRerankProvider,         # 云端 API
}

def get_rerank_provider(model_id: str = None) -> RerankProvider:
    """model_id 为 None 时用 settings.HF_RERANK_MODEL（默认本地）。"""
    model_id = model_id or settings.HF_RERANK_MODEL
    if model_id not in RERANK_REGISTRY:
        raise ValueError(f"Unknown rerank model: {model_id}")
    return RERANK_REGISTRY[model_id]()
```

**在 `rerank_retrieval.py` 中使用**：
```python
from app.services.rerank.factory import get_rerank_provider

class RerankRetrieval:
    def __init__(self, rerank_model: str = None):
        self._reranker = get_rerank_provider(rerank_model)

    async def retrieve(self, query, vector_results, top_k=5):
        # vector_results: 来自 vector_retrieval 的候选 (chunk_id, content, score)
        documents = [r["content"] for r in vector_results]
        ranked = await self._reranker.rerank(query, documents, top_k=top_k)
        # ranked: [(original_index, score), ...] 按 rerank 分数降序
        return [
            {**vector_results[idx], "rerank_score": score}
            for idx, score in ranked
        ]
```

#### BM25 存储
```
backend/data/bm25_index/
├── {kb_id}_chunks.pkl      # chunk 列表
└── {kb_id}_index.pkl       # rank_bm25 索引
```

#### GraphRAG 存储
```
backend/data/graphrag/
└── {kb_id}/
    ├── entities.parquet
    ├── relationships.parquet
    └── communities.parquet
```

---

## 4. 📦 Phase 3: 知识库配置增强 + 权限调整

### 4.1 KB 模型新增字段

```python
class KnowledgeBase(Base):
    # 已有字段
    id, name, description, owner_id, created_at
    
    # 新增配置字段
    embedding_model = Column(String(100), default="qwen3-embedding:0.6b")
    chunking_strategy = Column(String(50), default="recursive")
    chunk_size = Column(Integer, default=500)
    chunk_overlap = Column(Integer, default=50)
    retrieval_strategy = Column(String(50), default="vector")
    # rerank 模型（仅在 retrieval_strategy="rerank" 时生效）
    rerank_model = Column(String(100), default="BAAI/bge-reranker-base")
    rerank_top_k = Column(Integer, default=20)  # 向量初筛多少个再 rerank
    graphrag_indexed = Column(Boolean, default=False)
```

### 4.2 权限调整

| 操作 | 普通用户 | 管理员 |
|------|---------|--------|
| 创建 KB | ❌ | ✅ |
| 上传文档 | ❌ | ✅ |
| 删除 KB | 仅自己创建 | ✅ 全部 |
| 设置 KB 策略 | ❌ | ✅ |
| 对话 | ✅ | ✅ |
| 查看 KB | 仅自己创建 | ✅ 全部 |

### 4.3 数据库迁移
新建 `alembic/versions/b2c3d4e5f6g7_add_kb_strategy_fields.py`

### 4.4 KB Pydantic Schema
```python
class KnowledgeBaseCreate(BaseModel):
    name: str
    description: Optional[str]
    embedding_model: str = "qwen3-embedding:0.6b"
    chunking_strategy: str = "recursive"
    chunk_size: int = 500
    chunk_overlap: int = 50
    retrieval_strategy: str = "vector"
    rerank_model: str = "BAAI/bge-reranker-base"
    rerank_top_k: int = 20
```

---

## 5. 📦 Phase 4: 多 Provider env 配置

### 5.1 完整 .env.example

```ini
# ============================================
# MiMo LLM（生成模型 + LLM-as-Judge）
# ============================================
MIMO_BASE_URL=https://api.xiaomimimo.com/v1
MIMO_API_KEY=                       # ← 用户填
MIMO_MODEL=mimo-v2.5-pro            # 默认生成模型（高级别）
MIMO_LITE_MODEL=mimo-v2.5            # LLM-as-Judge 固定使用 mimo-v2.5

# ============================================
# DeepSeek LLM
# ============================================
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
DEEPSEEK_API_KEY=                   # ← 用户填
DEEPSEEK_MODEL=deepseek-v4-flash

# ============================================
# GLM (智谱)
# ============================================
GLM_BASE_URL=https://open.bigmodel.cn/api/paas/v4
GLM_API_KEY=                        # ← 用户填
GLM_MODEL=GLM-4.5-flash

# ============================================
# Embedding - Ollama (本地)
# ============================================
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_EMBED_MODEL=qwen3-embedding:0.6b

# ============================================
# Embedding - HuggingFace 本地 (离线缓存)
# 模型统一缓存在 C:\Users\13596\.cache\huggingface\hub\
# ============================================
HF_EMBED_MODEL=shibing624/text2vec-base-chinese
HF_CACHE_DIR=C:\Users\13596\.cache\huggingface\hub
HF_OFFLINE=1                          # 1=强制离线（推荐），0=允许联网

# ============================================
# Embedding - SiliconFlow (云端 API)
# ============================================
SILICONFLOW_BASE_URL=https://api.siliconflow.cn/v1
SILICONFLOW_API_KEY=                # ← 用户填
SILICONFLOW_EMBED_8B=Qwen/Qwen3-Embedding-8B
SILICONFLOW_EMBED_4B=Qwen/Qwen3-Embedding-4B

# ============================================
# Rerank - HuggingFace 本地 (离线缓存)
# 与 embedding 共享同一 HF 缓存目录
# ============================================
HF_RERANK_MODEL=BAAI/bge-reranker-base        # 本地默认（用户可改）

# ============================================
# Rerank - SiliconFlow (云端 API)
# ============================================
SILICONFLOW_RERANK_MODEL=Qwen/Qwen3-Reranker-4B
SILICONFLOW_RERANK_URL=https://api.siliconflow.cn/v1/rerank

# ============================================
# 评估 (LLM-as-Judge) — 固定使用 mimo-v2.5
# ============================================
# 不再单独配置 EVAL_JUDGE_MODEL，统一从 MIMO_LITE_MODEL 读取
# 即：评估时永远用 settings.MIMO_LITE_MODEL（默认 mimo-v2.5）
# base_url 与 api_key 复用 MIMO_BASE_URL / MIMO_API_KEY

# ============================================
# 默认策略
# ============================================
DEFAULT_EMBEDDING=qwen3-embedding:0.6b
DEFAULT_CHUNKING=recursive
DEFAULT_RETRIEVAL=vector
DEFAULT_LLM=mimo-v2.5-pro
DEFAULT_EVAL_QA_COUNT=20            # 每次自动生成数据集默认 20 道题
DEFAULT_EVAL_CONCURRENCY=4          # 评估并行度（每个 run 内同时跑 N 个 task）
```

### 5.2 config.py 新增字段

```python
# MiMo
MIMO_BASE_URL: str = os.getenv("MIMO_BASE_URL", "https://api.xiaomimimo.com/v1")
MIMO_API_KEY: str = os.getenv("MIMO_API_KEY", "")
MIMO_MODEL: str = os.getenv("MIMO_MODEL", "mimo-v2.5-pro")
MIMO_LITE_MODEL: str = os.getenv("MIMO_LITE_MODEL", "mimo-v2.5")  # 评估 Judge 固定用

# DeepSeek
DEEPSEEK_BASE_URL: str = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
DEEPSEEK_API_KEY: str = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_MODEL: str = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")

# GLM
GLM_BASE_URL: str = os.getenv("GLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4")
GLM_API_KEY: str = os.getenv("GLM_API_KEY", "")
GLM_MODEL: str = os.getenv("GLM_MODEL", "GLM-4.5-flash")

# Embedding - HuggingFace 本地（统一缓存目录）
HF_EMBED_MODEL: str = os.getenv("HF_EMBED_MODEL", "shibing624/text2vec-base-chinese")
HF_CACHE_DIR: str = os.getenv("HF_CACHE_DIR", "C:\\Users\\13596\\.cache\\huggingface\\hub")
HF_OFFLINE: bool = os.getenv("HF_OFFLINE", "1") == "1"

# Embedding - SiliconFlow
SILICONFLOW_BASE_URL: str = os.getenv("SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1")
SILICONFLOW_API_KEY: str = os.getenv("SILICONFLOW_API_KEY", "")
SILICONFLOW_EMBED_8B: str = os.getenv("SILICONFLOW_EMBED_8B", "Qwen/Qwen3-Embedding-8B")
SILICONFLOW_EMBED_4B: str = os.getenv("SILICONFLOW_EMBED_4B", "Qwen/Qwen3-Embedding-4B")

# Rerank - HuggingFace 本地（与 embedding 共享同一缓存目录）
HF_RERANK_MODEL: str = os.getenv("HF_RERANK_MODEL", "BAAI/bge-reranker-base")

# Rerank - SiliconFlow
SILICONFLOW_RERANK_MODEL: str = os.getenv("SILICONFLOW_RERANK_MODEL", "Qwen/Qwen3-Reranker-4B")
SILICONFLOW_RERANK_URL: str = os.getenv(
    "SILICONFLOW_RERANK_URL", "https://api.siliconflow.cn/v1/rerank"
)

# 评估默认参数
DEFAULT_EVAL_QA_COUNT: int = int(os.getenv("DEFAULT_EVAL_QA_COUNT", "20"))
DEFAULT_EVAL_CONCURRENCY: int = int(os.getenv("DEFAULT_EVAL_CONCURRENCY", "4"))
EVAL_REPORT_DIR: str = os.getenv("EVAL_REPORT_DIR", "./reports")

# 评估 LLM-as-Judge 固定使用 MIMO_LITE_MODEL（代码中直接引用，不再单独配置）
# 在代码中：judge_llm = LLMFactory.create(settings.MIMO_LITE_MODEL)
```

---

## 6. 📦 Phase 5: 评估系统

### 6.1 数据库模型

```python
# app/models/eval_models.py

class EvaluationDataset(Base):
    __tablename__ = "evaluation_datasets"
    id = Column(UUID, primary_key=True, default=uuid.uuid4)
    kb_id = Column(Integer, ForeignKey("knowledge_bases.id"))
    name = Column(String(200))
    qa_pairs = Column(JSONB)  # [{question, ground_truth, source_chunk_ids, source_doc_ids}]
    created_at = Column(DateTime(timezone=True))
    created_by = Column(UUID, ForeignKey("users.id"))


class EvaluationRun(Base):
    __tablename__ = "evaluation_runs"
    id = Column(UUID, primary_key=True, default=uuid.uuid4)
    dataset_id = Column(UUID, ForeignKey("evaluation_datasets.id"))
    name = Column(String(200))
    config = Column(JSONB)
    # config 包含：
    #   embedding_models:     list[str]   - embedding 模型列表
    #   retrieval_strategies: list[str]   - 检索策略列表
    #   rerank_models:        list[str]   - rerank 模型列表（仅 rerank 策略生效）
    #   generation_models:    list[str]   - 生成模型列表
    #   chunking_strategies:  list[str]   - 切块策略列表（可选）
    # status: pending / running / stopped / completed / failed
    status = Column(String(20), default="pending")
    progress = Column(Integer, default=0)  # 0-100
    total_tasks = Column(Integer)
    completed_tasks = Column(Integer, default=0)
    summary = Column(JSONB)  # 汇总指标
    # 断点续传相关
    resume_count = Column(Integer, default=0)  # 被续跑的次数
    last_resumed_at = Column(DateTime(timezone=True))
    # 报告路径
    report_json_path = Column(String(500))
    report_md_path = Column(String(500))
    # 时间
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    created_by = Column(UUID, ForeignKey("users.id"))


class EvaluationResult(Base):
    __tablename__ = "evaluation_results"
    id = Column(UUID, primary_key=True, default=uuid.uuid4)
    run_id = Column(UUID, ForeignKey("evaluation_runs.id", ondelete="CASCADE"))
    qa_index = Column(Integer)  # 第几个问题
    question = Column(Text)
    ground_truth = Column(Text)
    embedding_model = Column(String(100))
    retrieval_strategy = Column(String(50))
    rerank_model = Column(String(100))  # 新增：rerank 模型（rerank 策略时使用）
    generation_model = Column(String(100))
    retrieved_chunks = Column(JSONB)
    generated_answer = Column(Text)
    retrieval_metrics = Column(JSONB)  # {hit_at_5, mrr, ndcg_at_5, recall_at_5}
    generation_scores = Column(JSONB)  # {faithfulness, relevance, completeness} (1-5)
    latency_ms = Column(Integer)
    # 错误处理（断点续传需要）
    error_message = Column(Text)  # 失败时记录错误
    judge_error = Column(Boolean, default=False)  # Judge 调用失败标记
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    __table_args__ = (
        UniqueConstraint(
            "run_id", "qa_index", "embedding_model",
            "retrieval_strategy", "rerank_model", "generation_model",
            name="uq_eval_result",
        ),
    )
```

### 6.2 服务模块

```
app/services/eval/
├── __init__.py
├── dataset_builder.py    # LLM 自动生成 QA 数据集
├── runner.py             # 评估运行器（后台任务）
├── metrics.py            # 检索指标计算
├── judge.py              # LLM-as-Judge 评分
└── report.py             # 报告生成（JSON + Markdown）
```

#### Dataset Builder
```python
class GoldenDatasetBuilder:
    """从 KB 文档 chunks 自动生成 QA 三元组（Question & Answer）。

    默认生成 20 道题，可在创建数据集时通过参数覆盖。
    """

    DEFAULT_QA_COUNT = 20  # ← 默认 20 道（来自 settings.DEFAULT_EVAL_QA_COUNT）

    async def generate(
        self,
        kb_id: int,
        n_questions: int = None,  # None 时用默认值
    ) -> list[dict]:
        """从 KB 文档 chunks 自动生成 QA 三元组。"""
        n = n_questions or settings.DEFAULT_EVAL_QA_COUNT
        # 1. 取 KB 所有 chunks
        chunks = get_chunks_by_kb(kb_id)

        # 2. 随机采样 n 个 chunks
        sampled = random.sample(chunks, min(n, len(chunks)))

        # 3. 用 LLM 生成 QA（并发加速）
        sem = asyncio.Semaphore(4)

        async def gen_one(chunk):
            async with sem:
                return await self._generate_qa_for_chunk(chunk)

        qa_pairs = await asyncio.gather(*[gen_one(c) for c in sampled])
        return [
            {
                "question": qa["question"],
                "ground_truth": qa["answer"],
                "source_chunk_ids": [chunk["id"]],
                "source_doc_ids": [chunk["doc_id"]],
            }
            for chunk, qa in zip(sampled, qa_pairs)
        ]
```

#### Runner（关键：**并行 + 断点续传 + 立即持久化**）

```python
# runner.py
import asyncio
import logging
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.config import settings
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class EvalRunner:
    """评估运行器。

    关键设计：
    1. **细粒度持久化**：每个 (qa_index, embedding, retrieval, generation) 组合
       一旦完成就立即写库，绝不在内存中累积
    2. **断点续传**：启动时先查询已完成 task，只跑未完成的
    3. **并行执行**：asyncio.Semaphore 控制并发（默认 4）
    4. **可取消**：用户停止时优雅退出，已完成的结果全部保留
    5. **独立 session**：每个 task 独立 session，避免连接池耗尽
    """

    def __init__(self, run_id: uuid.UUID):
        self.run_id = run_id
        self._stop_flag = asyncio.Event()
        self._semaphore = asyncio.Semaphore(settings.DEFAULT_EVAL_CONCURRENCY)

    def request_stop(self):
        """用户点击「停止评估」时调用。"""
        self._stop_flag.set()
        logger.info(f"EvalRun {self.run_id}: 收到停止信号")

    async def start(self):
        """由 API 层调用：asyncio.create_task(runner.run())。"""
        try:
            await self._run()
        except Exception as e:
            logger.exception(f"EvalRun {self.run_id} 异常: {e}")
            await self._mark_run_status("failed", error=str(e))

    async def _run(self):
        async with async_session_factory() as db:
            run = (await db.execute(
                select(EvaluationRun).where(EvaluationRun.id == self.run_id)
            )).scalar_one()

            dataset = (await db.execute(
                select(EvaluationDataset).where(
                    EvaluationDataset.id == run.dataset_id
                )
            )).scalar_one()

            # 展开所有 task 组合
            all_tasks = self._expand_tasks(dataset.qa_pairs, run.config)
            run.total_tasks = len(all_tasks)
            if run.status == "pending":
                run.status = "running"
                run.started_at = datetime.now(timezone.utc)
            await db.commit()

            # 关键：查询已完成的 task，实现断点续传
            completed_keys = await self._get_completed_task_keys(db)
            pending_tasks = [
                t for t in all_tasks
                if self._task_key(t) not in completed_keys
            ]
            logger.info(
                f"EvalRun {self.run_id}: 总 {len(all_tasks)}, "
                f"已完成 {len(all_tasks) - len(pending_tasks)}, "
                f"待跑 {len(pending_tasks)}"
            )

            # 并发执行（受 Semaphore 控制）
            coros = [self._run_with_limit(t) for t in pending_tasks]
            await asyncio.gather(*coros, return_exceptions=True)

            # 检查是否被停止
            if self._stop_flag.is_set():
                await self._mark_run_status("stopped")
                return

            # 汇总 + 生成报告
            await self._finalize_run(db, run)

    def _expand_tasks(self, qa_pairs, config) -> list[dict]:
        """展开笛卡尔积：每个 (qa × embedding × retrieval × generation) 一个 task。

        当 retrieval_strategy="rerank" 时，还要展开 rerank_model。
        """
        embed_models = config["embedding_models"]
        retrievals = config["retrieval_strategies"]
        generations = config["generation_models"]
        # rerank 模型列表（仅在 retrieval=rerank 时使用）
        rerank_models = config.get("rerank_models", [])

        tasks = []
        for qa_idx, qa in enumerate(qa_pairs):
            for em in embed_models:
                for rt in retrievals:
                    # rerank 策略要展开 rerank 模型维度
                    if rt == "rerank" and rerank_models:
                        for rm in rerank_models:
                            for gm in generations:
                                tasks.append({
                                    "qa_index": qa_idx,
                                    "question": qa["question"],
                                    "ground_truth": qa["ground_truth"],
                                    "source_chunk_ids": qa["source_chunk_ids"],
                                    "embedding_model": em,
                                    "retrieval_strategy": rt,
                                    "rerank_model": rm,
                                    "generation_model": gm,
                                })
                    else:
                        for gm in generations:
                            tasks.append({
                                "qa_index": qa_idx,
                                "question": qa["question"],
                                "ground_truth": qa["ground_truth"],
                                "source_chunk_ids": qa["source_chunk_ids"],
                                "embedding_model": em,
                                "retrieval_strategy": rt,
                                "rerank_model": None,
                                "generation_model": gm,
                            })
        return tasks

    @staticmethod
    def _task_key(t: dict) -> str:
        return (
            f"{t['qa_index']}|{t['embedding_model']}|"
            f"{t['retrieval_strategy']}|{t.get('rerank_model') or '-'}|"
            f"{t['generation_model']}"
        )

    async def _get_completed_task_keys(self, db: AsyncSession) -> set[str]:
        """查询已完成的 task keys。"""
        result = await db.execute(
            select(EvaluationResult).where(
                EvaluationResult.run_id == self.run_id
            )
        )
        rows = result.scalars().all()
        return {self._task_key(r) for r in rows}

    async def _run_with_limit(self, task: dict):
        """信号量保护 + 立即写库。"""
        if self._stop_flag.is_set():
            return
        async with self._semaphore:
            if self._stop_flag.is_set():
                return
            try:
                result = await self._run_single_task(task)
                await self._save_result(result)  # 立即写库
                await self._update_progress()
            except Exception as e:
                logger.exception(f"Task 失败: {task}, err={e}")
                await self._save_error_result(task, str(e))

    async def _run_single_task(self, task: dict) -> dict:
        """执行单个 task：检索 → 生成 → Judge。"""
        # 1. 检索（按 embedding_model + retrieval_strategy 路由）
        retrieved = await self._retrieve(task)
        # 2. 生成（按 generation_model 调用对应 LLM）
        answer = await self._generate(task, retrieved)
        # 3. Judge（固定 mimo-v2.5）
        scores = await self._judge(task, answer)
        # 4. 检索指标
        ret_metrics = self._compute_retrieval_metrics(
            task["source_chunk_ids"], retrieved
        )
        return {
            **task,
            "retrieved_chunks": retrieved,
            "generated_answer": answer,
            "retrieval_metrics": ret_metrics,
            "generation_scores": scores,
        }

    async def _save_result(self, result: dict):
        """每个 result 完成后立即 insert 数据库。"""
        async with async_session_factory() as db:
            row = EvaluationResult(
                id=uuid.uuid4(),
                run_id=self.run_id,
                **result,
            )
            db.add(row)
            await db.commit()

    async def _update_progress(self):
        """更新 run 进度。"""
        async with async_session_factory() as db:
            run = (await db.execute(
                select(EvaluationRun).where(EvaluationRun.id == self.run_id)
            )).scalar_one()
            run.completed_tasks = (run.completed_tasks or 0) + 1
            run.progress = int(
                run.completed_tasks / run.total_tasks * 100
            ) if run.total_tasks else 0
            await db.commit()

    async def _finalize_run(self, db: AsyncSession, run: EvaluationRun):
        """汇总结果 + 写报告文件。"""
        results = (await db.execute(
            select(EvaluationResult).where(
                EvaluationResult.run_id == self.run_id
            )
        )).scalars().all()

        summary = self._aggregate(results)
        run.summary = summary
        run.status = "completed"
        run.progress = 100
        run.completed_at = datetime.now(timezone.utc)
        await db.commit()

        # 生成报告文件（永久保留，不设过期）
        await ReportGenerator(self.run_id).generate()
```

**关键改进（相比之前的串行版）**：
- ❌ 旧版：所有结果先在内存中累积，最后一次性 commit → 崩溃/重启全丢
- ✅ 新版：每个 task 一完成就 commit → 永远丢不了多少
- ❌ 旧版：串行执行 → 100 个 task 要跑 100 × 平均时间
- ✅ 新版：4 路并发 → 约 1/4 时间
- ❌ 旧版：终止 = 全部丢
- ✅ 新版：终止 = 已完成的全部保留，下次再跑 = 断点续传

#### 检索指标
```python
# metrics.py
def hit_at_k(retrieved_ids: list, relevant_ids: list, k: int) -> float:
    return 1.0 if any(rid in retrieved_ids[:k] for rid in relevant_ids) else 0.0

def mrr(retrieved_ids: list, relevant_ids: list) -> float:
    for i, rid in enumerate(retrieved_ids, 1):
        if rid in relevant_ids:
            return 1.0 / i
    return 0.0

def ndcg_at_k(retrieved_ids: list, relevant_ids: list, k: int) -> float:
    dcg = sum(1.0 / math.log2(i + 2) for i, rid in enumerate(retrieved_ids[:k]) if rid in relevant_ids)
    idcg = sum(1.0 / math.log2(i + 2) for i in range(min(len(relevant_ids), k)))
    return dcg / idcg if idcg > 0 else 0.0
```

#### LLM-as-Judge（**固定使用 mimo-v2.5**）

> **术语说明**：QA = Question & Answer（问题与答案）。评估数据集的每一条记录就是一对 (question, ground_truth_answer)。

```python
# judge.py
from app.config import settings
from app.services.llm_provider.factory import LLMFactory

class LLMJudge:
    """LLM-as-Judge 评分器。固定使用 mimo-v2.5（settings.MIMO_LITE_MODEL）。"""

    def __init__(self):
        # 固定从 settings.MIMO_LITE_MODEL 创建，不接受外部覆盖
        self._llm = LLMFactory.create(settings.MIMO_LITE_MODEL)

    async def score(self, question: str, ground_truth: str, answer: str) -> dict:
        """调用 mimo-v2.5 对 AI 回答打分。"""
        prompt = JUDGE_PROMPT.format(
            question=question,
            ground_truth=ground_truth,
            answer=answer,
        )
        response = await self._llm.ainvoke([HumanMessage(content=prompt)])
        return self._parse_json(response)
```

```python
JUDGE_PROMPT = """你是 RAG 答案质量评估专家。请基于参考答案评估 AI 回答的质量。

【问题】
{question}

【参考答案】
{ground_truth}

【AI 回答】
{answer}

从三个维度打分（1-5 分）：
1. faithfulness (忠实度): AI 回答是否基于事实，无编造
2. relevance (相关性): AI 回答是否切题
3. completeness (完整度): AI 回答是否覆盖参考答案要点

输出 JSON: {{"faithfulness": x, "relevance": y, "completeness": z, "reason": "..."}}"""
```

**关键约束**：
- Judge 模型永远是 `mimo-v2.5`（即 `MIMO_LITE_MODEL`）
- base_url / api_key 复用 `MIMO_BASE_URL` / `MIMO_API_KEY`
- 不允许前端或 API 参数覆盖 Judge 模型
- 如果 mimo-v2.5 接口失败 → 该 task 标记 `judge_error: True`，但不阻塞整个 run

### 6.3 报告输出（**两者都要 + 永久保留 + 清晰命名**）

#### 文件命名规则

```
eval_{run_name_safe}_{YYYYMMDD_HHMMSS}_{run_id_short}.{ext}
```

- `run_name_safe`：把用户填的 run.name 清洗成文件名安全字符串（中文→拼音 or 仅保留 ASCII；空格→`_`；去掉 `/\:*?"<>|`）
- `YYYYMMDD_HHMMSS`：run 启动时间
- `run_id_short`：run UUID 的前 8 位
- `ext`：`json` 或 `md`

**示例**：
- `eval_test01_20260625_143000_a1b2c3d4.json`
- `eval_RAG效果对比_20260625_143000_a1b2c3d4.json`
- `eval_test01_20260625_143000_a1b2c3d4.md`

**优势**：
- 一眼看到运行名称 + 时间 + 简短 ID
- 多个 run 不会重名
- 按文件名排序 = 按时间排序
- 同一 run 的 json 和 md 可以通过前缀匹配

#### 输出目录

```
backend/reports/
├── eval_test01_20260625_143000_a1b2c3d4.json
├── eval_test01_20260625_143000_a1b2c3d4.md
├── eval_RAG效果对比_20260625_150000_e5f6g7h8.json
├── eval_RAG效果对比_20260625_150000_e5f6g7h8.md
└── ...
```

**保留策略**：
- ✅ **DB 永久保留**（除非用户主动 delete_run）
- ✅ **文件永久保留**（不设过期 / 不自动清理）
- 用户可随时通过 API `DELETE /runs/{run_id}` 同时删除 DB + 报告文件

#### ReportGenerator 伪代码

```python
# report.py
import re
import json
from datetime import datetime
from pathlib import Path

from app.config import settings


def _sanitize_name(name: str) -> str:
    """清洗 run.name → 文件名安全字符串。"""
    # 去掉 Windows/Linux 非法字符
    safe = re.sub(r'[\\/:\*\?"<>\|\r\n\t]', '', name)
    # 空格 → 下划线
    safe = safe.replace(' ', '_')
    # 截断长度
    return safe[:50] or "unnamed"


class ReportGenerator:
    def __init__(self, run_id: uuid.UUID):
        self.run_id = run_id
        self._dir = Path(settings.EVAL_REPORT_DIR)
        self._dir.mkdir(parents=True, exist_ok=True)

    async def generate(self):
        """同时生成 json 和 md，文件名带 run_name + 时间 + 短 ID。"""
        run = await self._fetch_run()
        results = await self._fetch_results()

        # 文件名前缀：eval_{name}_{ts}_{id8}
        ts = run.started_at.strftime("%Y%m%d_%H%M%S")
        id8 = str(self.run_id)[:8]
        prefix = f"eval_{_sanitize_name(run.name)}_{ts}_{id8}"

        # JSON
        json_path = self._dir / f"{prefix}.json"
        json_path.write_text(
            json.dumps(
                {
                    "run_id": str(self.run_id),
                    "name": run.name,
                    "config": run.config,
                    "summary": run.summary,
                    "results": [r.to_dict() for r in results],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        # Markdown
        md_path = self._dir / f"{prefix}.md"
        md_path.write_text(
            self._render_markdown(run, results),
            encoding="utf-8",
        )

        # 把报告路径写回 run 记录
        async with async_session_factory() as db:
            r = (await db.execute(
                select(EvaluationRun).where(EvaluationRun.id == self.run_id)
            )).scalar_one()
            r.report_json_path = str(json_path)
            r.report_md_path = str(md_path)
            await db.commit()
```

Markdown 示例：
```markdown
# 评估报告 - 2026-06-22 14:30

## 配置
- Embedding: qwen3-embedding:0.6b, shibing624/text2vec-base-chinese
- Retrieval: vector, bm25, rerank
  - Rerank: BAAI/bge-reranker-base, Qwen/Qwen3-Reranker-4B
- Generation: mimo-v2.5, deepseek-v4-flash, GLM-4.5-flash

## 检索指标汇总
| Embedding | Retrieval | Rerank | Hit@5 | MRR | NDCG@5 |
| --- | --- | --- | --- | --- | --- |
| qwen3-embedding | vector | - | 0.85 | 0.72 | 0.81 |
| qwen3-embedding | bm25 | - | 0.78 | 0.65 | 0.74 |
| qwen3-embedding | rerank | bge-reranker-base | 0.91 | 0.83 | 0.88 |
| qwen3-embedding | rerank | Qwen3-Reranker-4B | 0.93 | 0.86 | 0.90 |
| ... | | | | | |

## 生成质量汇总
| Generation | Faithfulness | Relevance | Completeness |
| --- | --- | --- | --- |
| mimo-v2.5 | 4.2 | 4.5 | 4.1 |
| deepseek-v4-flash | 4.0 | 4.3 | 3.9 |
| GLM-4.5-flash | 3.9 | 4.2 | 3.8 |
| ... | | | |
```

### 6.4 管理员自定义评估（关键需求）

管理员在前端评估页可以：
- 选择 KB
- 选择 embedding 模型（多选）
- 选择 retrieval 策略（多选，含 vector / bm25 / rerank / graphrag）
- **当选择 `rerank` 策略时，额外选择 rerank 模型**（多选）
- 选择 generation 模型（多选）
- 选择已有数据集 / 自动生成新数据集
- 设置每组合的题数
- 命名评估 + 启动

每次启动 = **一个独立的 EvaluationRun**，独立后台任务，可独立查看进度/结果。

### 6.5 后端 API

```python
# app/api/eval.py
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from app.core.security import get_current_user, require_admin

router = APIRouter(prefix="/eval", tags=["评估"])

# 内存中持有运行中的 EvalRunner，支持停止
_runners: dict[uuid.UUID, "EvalRunner"] = {}


@router.post("/datasets")
async def create_dataset(req: DatasetCreate, ...): ...
    # 管理员自动生成数据集，默认 20 道
    # n_questions 为 None 时用 settings.DEFAULT_EVAL_QA_COUNT (=20)

@router.get("/datasets")
async def list_datasets(...): ...

@router.post("/runs")                 # 启动评估
async def create_run(req: EvalRunCreate, background_tasks: BackgroundTasks, ...):
    """创建 run 记录 → 启动后台任务 → 立即返回 run_id。"""
    ...

@router.get("/runs")
async def list_runs(...): ...

@router.get("/runs/{run_id}")
async def get_run(run_id, ...):
    """返回 run 详情 + 进度 + 状态。"""
    # 包含：name, status, progress, total_tasks, completed_tasks,
    #       started_at, completed_at, report_json_path, report_md_path

@router.post("/runs/{run_id}/resume")    # 续跑（断点续传）
async def resume_run(run_id, ...):
    """如果 run 处于 stopped/failed 状态，重新启动后台任务。
    内部会查询已完成 task，只跑剩余的。"""
    runner = EvalRunner(run_id)
    _runners[run_id] = runner
    asyncio.create_task(runner.start())
    return {"resumed": True}

@router.post("/runs/{run_id}/stop")     # 停止（已完成的保留）
async def stop_run(run_id, ...):
    """标记 stop_flag = True，已在跑的 task 会尽快退出，未启动的不再启动。"""
    runner = _runners.get(run_id)
    if runner:
        runner.request_stop()
    return {"stopping": True}

@router.get("/runs/{run_id}/results")
async def get_results(run_id, ...): ...

@router.get("/runs/{run_id}/progress")  # 轻量级进度查询（SSE 替代品）
async def get_progress(run_id, ...):
    """前端每 2 秒轮询一次，返回 {progress, completed_tasks, total_tasks, status}。"""
    ...

@router.delete("/runs/{run_id}")
async def delete_run(run_id, ...):
    """删除 DB 记录 + 报告文件。"""
    ...
```

### 6.6 前端 EvaluationView.vue

**新建评估面板：**
```
┌─────────────────────────────────────────┐
│  评估中心                                │
├─────────────────────────────────────────┤
│  [新建评估]  [数据集管理]                  │
│                                          │
│  知识库: [KB1 ▼]                          │
│  Embedding 模型: ☑qwen3 ☑shibing624 ☑8B  │
│  Retrieval: ☑vector ☑bm25 ☑rerank        │
│    └ 选中 rerank 时，展开：              │
│      Rerank 模型: ☑bge-reranker-base      │
│                   ☑Qwen3-Reranker-4B     │
│  Generation: ☑mimo-v2.5 ☑deepseek ☑glm    │
│  数据集: [已有 20 题 ▼] [或自动生成]      │
│  QA 数量: [20]  （默认 20，可改）          │
│  并行度:  [4]   （1-8）                   │
│  评估名称: [测试1]                         │
│  [启动评估]                                │
└─────────────────────────────────────────┘
```

**历史运行面板：**
```
┌──────────────────────────────────────────────┐
│  ── 历史运行 ──                                │
│  ▸ 测试1              running  ▓▓▓▓▓░ 45%   │
│     162/360 完成        已耗时 12:34          │
│     [查看进度]  [停止评估]                    │
│                                               │
│  ▸ RAG效果对比_v2     stopped  ▓▓▓▓░░ 60%   │
│     216/360 完成        2026-06-25 14:30     │
│     [查看结果]  [续跑]  [删除]                │
│                                               │
│  ▸ RAG效果对比_v1     completed  ▓▓▓▓▓ 100%  │
│     360/360 完成        2026-06-25 10:15     │
│     📊 eval_RAG效果对比_v1_20260625_101500_  │
│        a1b2c3d4.json  /  .md                  │
│     [查看报告]  [下载]  [删除]                │
└──────────────────────────────────────────────┘
```

**关键交互**：
- 启动后立即显示在「历史运行」最上方，每 2 秒轮询一次 `/runs/{id}/progress`
- 进度条 + 实时耗时 + 已完成 / 总数
- 「停止」按钮调用 `POST /runs/{id}/stop` → 已完成的结果保留，run 状态变为 `stopped`
- `stopped` / `failed` 状态的 run 显示「续跑」按钮 → 调用 `POST /runs/{id}/resume` → 只跑未完成部分
- `completed` 状态显示报告文件名 + 「下载」/「查看」/「删除」按钮

---

## 6.7 ⚡ 性能与可靠性（高级优化）

> **目标**：让评估跑得快、跑得稳、不白跑。

### 6.7.1 速度优化（5 大策略）

#### ① 并行执行（**最大收益**）
- 评估 task 数 = `QA数 × embedding数 × retrieval数 × generation数`
- 20 题 × 2 emb × 2 ret × 3 gen = **240 个 task**
- 串行跑：240 × 平均 8s = 32 分钟
- 4 路并发：240 × 8 / 4 = **8 分钟**（提速 4 倍）

```python
# runner.py
self._semaphore = asyncio.Semaphore(settings.DEFAULT_EVAL_CONCURRENCY)  # 默认 4
```

#### ② LLM 批处理（节省 round-trip）
- 数据集生成时：20 道题的 Q+A 生成从 20 次 LLM 调用 → 1 次批量调用
- Judge 评分时：多个 task 的 Judge 可以打包成一次请求

```python
# judge.py 批量评分
async def score_batch(self, items: list[dict]) -> list[dict]:
    prompt = BATCH_JUDGE_PROMPT.format(
        items=json.dumps(items, ensure_ascii=False, indent=2)
    )
    response = await self._llm.ainvoke([HumanMessage(content=prompt)])
    return self._parse_json_array(response)
```

#### ③ Embedding 缓存（同一文本不重复算）
- KB 文档向量化结果已经存在 ChromaDB（KB 自己的 chunk）
- 评估时**优先复用**已存在的 embedding，**不重新算**
- 切换 embedding 模型时**才**重新算

```python
# vector_retrieval.py
async def get_or_compute_embedding(self, chunk_id: str, model: str):
    # 检查该 (chunk_id, model) 是否已有 embedding
    cached = await self._cache.get(f"{model}:{chunk_id}")
    if cached:
        return cached
    emb = await self._embedder.embed_query(chunk_text)
    await self._cache.set(f"{model}:{chunk_id}", emb)
    return emb
```

#### ④ GPU 加速（本地 embedding）
- shibing624/text2vec-base-chinese 跑在 CPU 上 OK（~50ms/句）
- 如果机器有 GPU，设置 `CUDA_VISIBLE_DEVICES=0` 自动使用
- sentence-transformers 检测到 CUDA 自动转 GPU

---

### 6.7.2 断点续传机制（**核心需求**）

#### 触发场景
- 用户主动点「停止」 → `status=stopped`
- 后端崩溃 / 容器重启 → `status=running` 但实际已死
- 网络中断 → 部分 task 失败

#### 实现原理
1. **每个 task 一完成就 commit** → 永远不丢已完成的结果
2. **启动时查询已完成 task** → 跳过已完成的
3. **续跑用同一个 run_id** → 历史不丢
4. **状态机清晰**：`pending → running → (stopped | failed) → (running via resume) → completed`

```python
# runner.py 启动逻辑
completed_keys = await self._get_completed_task_keys(db)
pending_tasks = [t for t in all_tasks if self._task_key(t) not in completed_keys]
# pending_tasks 可能是 0（全部已完成）→ 跳过执行，直接汇总
```

#### 用户操作流
```
[启动评估]  →  status=running, 进度 0%
[跑到 60%]  
[用户点停止] →  status=stopped, 进度 60%, DB 中保留 60% 的 results
[用户点续跑] →  status=running, 从 60% 继续（pending_tasks 已自动过滤）
[跑到 100%]  →  status=completed, 报告生成
```

#### Resume API
```python
@router.post("/runs/{run_id}/resume")
async def resume_run(run_id: UUID, ...):
    run = await _get_run(run_id)
    if run.status not in ("stopped", "failed"):
        raise 400, "Only stopped/failed runs can be resumed"
    
    runner = EvalRunner(run_id)
    _runners[run_id] = runner
    asyncio.create_task(runner.start())  # 内部会查已完成 task
    
    run.status = "running"
    run.resume_count += 1
    run.last_resumed_at = datetime.now(timezone.utc)
    await db.commit()
    
    return {"resumed": True, "resume_count": run.resume_count}
```

---

### 6.7.3 永久保留策略

| 数据类型 | 保留策略 | 删除方式 |
|---------|---------|---------|
| `evaluation_runs` 表 | **永久** | 用户主动 `DELETE /runs/{id}` |
| `evaluation_results` 表 | **永久** | 跟随 run 级联删除 |
| `evaluation_datasets` 表 | **永久** | 用户主动 `DELETE /datasets/{id}` |
| `reports/*.json` | **永久** | run 删除时同步删文件 |
| `reports/*.md` | **永久** | run 删除时同步删文件 |
| 失败 task 错误日志 | **永久**（存在 result.error_message 字段） | 跟随 run 删除 |

**绝不自动清理** — 由用户决定何时删除。

---

### 6.7.4 文件命名规范

```python
# report.py
def _build_filename(run) -> str:
    safe_name = _sanitize_name(run.name)
    ts = run.started_at.strftime("%Y%m%d_%H%M%S")
    id8 = str(run.id).replace("-", "")[:8]
    return f"eval_{safe_name}_{ts}_{id8}"

# 输出
# eval_test01_20260625_143000_a1b2c3d4.json
# eval_test01_20260625_143000_a1b2c3d4.md
```

**规则总结**：
- 前缀固定 `eval_`
- 第二段：清洗后的运行名（中文保留，非法字符替换）
- 第三段：启动时间戳（精确到秒）
- 第四段：run UUID 前 8 位（去横线）
- 扩展名：`.json`（结构化）/ `.md`（人类可读）

**好处**：
- 文件名一眼看清「跑了什么、什么时候跑的」
- 同名 run + 不同时间 → 文件名不会冲突
- 按文件名排序 = 按时间排序
- 删除 run 时根据 DB 存的 `report_json_path` 精确删除，不会误删

---

## 7. 📂 最终目录结构

```
backend/
├── app/
│   ├── api/
│   │   ├── auth.py
│   │   ├── chat.py                  # 改为 LCEL
│   │   ├── knowledge_base.py        # 权限收紧 + 策略字段
│   │   ├── documents.py
│   │   ├── admin.py
│   │   ├── health.py
│   │   └── eval.py                  # 🆕
│   ├── core/
│   │   ├── security.py
│   │   └── llm.py
│   ├── db/
│   │   └── database.py
│   ├── models/
│   │   ├── models.py                # KB 加字段
│   │   └── eval_models.py           # 🆕
│   ├── schemas/
│   │   ├── schemas.py
│   │   └── eval_schemas.py          # 🆕
│   ├── services/
│   │   ├── embedding/               # 🆕 模块化
│   │   │   ├── base.py
│   │   │   ├── factory.py
│   │   │   ├── ollama_provider.py
│   │   │   ├── huggingface_provider.py
│   │   │   └── siliconflow_provider.py
│   │   ├── llm_provider/            # 🆕 模块化
│   │   │   ├── base.py
│   │   │   ├── factory.py
│   │   │   ├── mimo.py
│   │   │   ├── deepseek.py
│   │   │   └── glm.py
│   │   ├── chunking/                # 🆕 模块化
│   │   │   ├── base.py
│   │   │   ├── factory.py
│   │   │   ├── fixed_size.py
│   │   │   ├── recursive.py
│   │   │   └── semantic.py
│   │   ├── retrieval/               # 🆕 模块化
│   │   │   ├── base.py
│   │   │   ├── factory.py
│   │   │   ├── vector_retrieval.py
│   │   │   ├── bm25_retrieval.py
│   │   │   ├── rerank_retrieval.py
│   │   │   └── graph_retrieval.py
│   │   ├── rerank/                   # 🆕 Rerank Provider 模块化
│   │   │   ├── base.py
│   │   │   ├── factory.py
│   │   │   ├── huggingface_provider.py    # 本地离线（HF 缓存）
│   │   │   └── siliconflow_provider.py    # Qwen3-Reranker-4B（API）
│   │   ├── eval/                    # 🆕
│   │   │   ├── dataset_builder.py
│   │   │   ├── runner.py
│   │   │   ├── metrics.py
│   │   │   ├── judge.py
│   │   │   └── report.py
│   │   ├── vectorstore.py
│   │   ├── ollama_service.py
│   │   ├── document_processor.py
│   │   ├── parser.py
│   │   └── reranker.py            # ⚠️ 旧文件，Phase 2.4 后被 services/rerank/ 替代
│   ├── middleware/
│   │   └── logging.py
│   ├── config.py                    # 🆕 大量新增
│   └── main.py
├── tests/
├── alembic/
│   └── versions/
│       ├── ... 旧迁移
│       └── b2c3d4e5f6g7_add_kb_strategy_fields.py  # 🆕
│       └── c3d4e5f6g7h8_add_eval_tables.py         # 🆕
├── reports/                         # 🆕 评估报告输出（永久保留）
│   ├── eval_test01_20260625_143000_a1b2c3d4.json
│   ├── eval_test01_20260625_143000_a1b2c3d4.md
│   ├── eval_RAG效果对比_20260625_150000_e5f6g7h8.json
│   └── eval_RAG效果对比_20260625_150000_e5f6g7h8.md
├── data/
│   ├── chromadb/
│   ├── bm25_index/                  # 🆕 BM25 索引
│   ├── graphrag/                    # 🆕 GraphRAG 索引
│   └── uploads/
├── requirements.txt
└── .env.example

frontend/src/
├── views/
│   ├── LoginView.vue
│   ├── RegisterView.vue
│   ├── ChatView.vue                 # 适配新 LLM provider
│   ├── KnowledgeBaseView.vue        # 管理员可见 + 策略选择
│   ├── AdminView.vue
│   └── EvaluationView.vue           # 🆕
├── api/index.js                     # 🆕 evalAPI
├── components/
│   └── ... (按需)
└── router/index.js                  # 🆕 /eval 路由
```

---

## 8. 🗓️ 执行顺序与时间预估

| 步骤 | 内容 | 依赖 | 预估 |
|------|------|------|------|
| **1** | Phase 1: 改 LangChain | - | 0.5 天 |
| **2** | Phase 2.1: Embedding 模块化 | 1 | 1 天 |
| **3** | Phase 2.2: LLM 模块化 | 1 | 0.5 天 |
| **4** | Phase 4: env 多 key 配置 | 2, 3 | 0.5 天 |
| **5** | Phase 2.3: Chunking 模块化 | 1 | 0.5 天 |
| **6** | Phase 2.4: Retrieval 模块化（vector/BM25/rerank） | 1, 2 | 1 天 |
| **7** | Phase 2.4: GraphRAG 集成 | 6 | 1 天 |
| **8** | Phase 3: KB 配置 + 权限调整 | 5, 6 | 0.5 天 |
| **9** | Phase 5.1-5.3: 评估核心 | 1-8 | 2 天 |
| **10** | Phase 5.4-5.5: 报告 + 前端 | 9 | 1 天 |

**总计：~8-9 天**

---

## 9. ⚠️ 风险与缓解

| 风险 | 影响 | 缓解 |
|------|------|------|
| GraphRAG 库依赖重 | 启动慢、内存大 | 单独 KB 启用，懒加载 |
| BM25 全量重建慢 | 评估启动延迟 | 增量更新 + 缓存 |
| HF 模型首次下载慢 | 卡死 | 自动下载到 `C:\Users\13596\.cache\huggingface\hub\`，之后强制离线 |
| 评估并发过高 | LLM API 限流 / 本地资源耗尽 | Semaphore 限制默认 4 路（可在 UI 调 1-8） |
| LLM-as-Judge 失败 | 单个 task 评分缺失 | 标记 `judge_error` 不阻塞 run |
| 评估中途崩溃 | 已完成结果丢失 | 每个 task 立即 commit；resume 时跳过已完成 |
| 报告文件堆积 | 磁盘占用 | DB 永久 / 文件永久（用户主动删） |
| 误删 run | 结果不可恢复 | 删除前前端二次确认 |

---

## 10. ✅ 验收标准

- [ ] 对话、登录、KB 基础功能未破坏
- [ ] 4 种 embedding 模型可切换使用
- [ ] 3 种 chunking 策略可切换
- [ ] 4 种 retrieval 策略可切换
- [ ] **2 种 rerank 模型可切换使用**（本地 `BAAI/bge-reranker-base` + 云端 `Qwen/Qwen3-Reranker-4B`）
- [ ] 3 种 generation 模型可切换
- [ ] 普通用户无法创建/上传 KB
- [ ] 管理员可配置 KB 的 embedding/chunking/retrieval/rerank
- [ ] 管理员可启动自定义评估（多模型组合，含 rerank 维度）
- [ ] **评估自动生成 QA 数据集默认 20 道**（可改）
- [ ] **LLM-as-Judge 固定使用 mimo-v2.5**（不可改）
- [ ] **评估并行运行（默认 4 路，可在 UI 调 1-8）**
- [ ] **评估中途停止后，已完成结果保留，可续跑**
- [ ] **评估崩溃/重启后可断点续传**（resume API）
- [ ] **每个 task 完成即写库，不会因崩溃丢数据**
- [ ] **历史运行记录永久保留**（DB + 报告文件）
- [ ] 报告文件命名清晰：`eval_{name}_{YYYYMMDD_HHMMSS}_{id8}.{json|md}`
- [ ] 每个评估独立运行，实时显示进度（轮询 /2s）
- [ ] 评估完成生成 JSON + Markdown 报告
- [ ] 前端展示历史评估记录和结果对比

---

## 11. ❓ 待用户最终确认

> 请逐条确认；任何一条有修改意见请直接说。

### A. 评估核心参数

1. ✅ **LLM-as-Judge 固定使用 `mimo-v2.5`**（即 `MIMO_LITE_MODEL`），不开放配置
   - 模型路径用默认 `MIMO_BASE_URL = https://api.xiaomimimo.com/v1`
   - API key 用 `MIMO_API_KEY`（和你对话用的同一个）
2. ✅ **默认生成 20 道 QA**（来自 `DEFAULT_EVAL_QA_COUNT=20`，UI 可改）
   - "QA" = Question & Answer（问题与答案对）
3. ✅ **评估默认 4 路并发**（来自 `DEFAULT_EVAL_CONCURRENCY=4`，UI 可调 1-8）

### B. 高级编程思路（速度优化）

4. ✅ 并行执行 + asyncio.Semaphore（最大收益，提速 ~4 倍）
5. ✅ LLM 批处理（数据集生成、Judge 评分都可批量化）
6. ✅ Embedding 缓存（同一文本不重复算）
7. ✅ GPU 加速（如有 GPU，本地 embedding 自动用）

### C. 断点续传 + 永久保留

9. ✅ **每个 task 一完成就 commit**（不丢已完成数据）
10. ✅ **停止评估后已完成的全部保留**（不白跑）
11. ✅ **`POST /runs/{id}/resume` 续跑**（自动跳过已完成）
12. ✅ **DB 永久保留**（除非主动 `DELETE /runs/{id}`）
13. ✅ **报告文件永久保留**（无过期 / 不自动清理）
14. ✅ 删除 run 时同步删 DB + 报告文件

### D. 文件命名

15. ✅ 命名规则：`eval_{run_name_safe}_{YYYYMMDD_HHMMSS}_{run_id_short}.{json|md}`
   - 示例：`eval_test01_20260625_143000_a1b2c3d4.json`
   - 示例：`eval_RAG效果对比_20260625_143000_e5f6g7h8.md`

### E. 本地模型缓存路径

16. **HF 模型统一缓存在 `C:\Users\13596\.cache\huggingface\hub\`**（HF 官方默认目录）
    - `shibing624/text2vec-base-chinese`（embedding）→ 该目录下子目录 `models--shibing624--text2vec-base-chinese`
    - 本地 rerank 模型（默认 `BAAI/bge-reranker-base`）→ 同样在该目录下
    - **首次启动时若不存在自动下载到该目录（只下一次）**，之后强制离线加载
    - 路径可通过 `HF_CACHE_DIR` 环境变量覆盖
    - 离线开关：`HF_OFFLINE=1`（默认强制离线，=0 时允许联网下载）

17. **Rerank 模型 2 种**：
    - **本地**：`BAAI/bge-reranker-base`（默认，离线；可在 .env 用 `HF_RERANK_MODEL` 改）
    - **云端**：`Qwen/Qwen3-Reranker-4B`（`SILICONFLOW_RERANK_URL=https://api.siliconflow.cn/v1/rerank`）
    - Factory 按模型名自动路由
    - **评估时 rerank 策略会自动展开 rerank_model 维度**（如果选 rerank + 2 个 rerank 模型，task 数会 ×2）

18. 评估运行：每个 run 一个后台任务；同一时间只跑 1 个 run（不并发 run）
    - 并发只在 **run 内部** 的 task 之间（4 路 Semaphore）

**确认后开始执行 Phase 1（LangGraph → LangChain）**。
