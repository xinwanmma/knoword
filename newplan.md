# 📋 评估指标全面重构 — newplan.md

> **最后更新**：2026-06-26
> **状态**：⏸ 等待用户确认后实施
> **目标**：8 个标准指标全部默认启用，推翻原 LLM-as-Judge 3 维度，全部基于 LangChain

---

## 1. 🎯 背景与目标

### 现状问题
- 检索指标：只有 `hit_at_5` / `mrr` / `ndcg_at_5` / `recall_at_5`（4 个，recall 定义不标准）
- 生成指标：LLM-as-Judge 3 维度（faithfulness / relevance / completeness）
  - **错把 LLM 看 answer 和 ground_truth 简单对比**，不基于 retrieved contexts 验证忠实度
  - **不分检索/生成责任**：错答是检索问题还是生成问题分不清
  - **没有 RAGAS 风格的 grounding 验证**
- RAGAS 0.4.3 改 API，0.1.x 跟 langchain 1.x 不兼容 → 自实现 RAGAS 指标反而可控

### 目标
**8 个标准指标，每次评估都跑，无开关**：

#### 🔍 检索指标（5 个，纯算法，无 LLM 介入）
| 指标 | 公式 | 作用 |
|---|---|---|
| **Recall@K** | `|retrieved_k ∩ relevant| / |relevant|` | 所有相关 chunk 中召回多少 |
| **Precision@K** | `|retrieved_k ∩ relevant| / K` | 前 K 个里相关比例 |
| **Hit@K** | `1 if any(retrieved_k ∩ relevant) else 0` | 是否有至少一个相关 |
| **MRR** | `1 / rank_of_first_relevant` | 第一个正确答案排第几 |
| **NDCG@K** | `DCG@K / IDCG@K` | 排序质量综合（用 binary relevance 0/1） |

#### 🤖 生成指标（3 个，固定用 `settings.MIMO_LITE_MODEL`，基于 LangChain）
| 指标 | 评估依据 | 0-1 范围 |
|---|---|---|
| **Faithfulness / Groundedness** | 拆 answer → statements → 每个是否能从 retrieved contexts 推出 | 1=完全 grounded，0=纯幻觉 |
| **Answer Relevancy** | LLM 判 answer 跟 question 的相关性（0/1 二元，N 次取平均） | 1=完全切题，0=答非所问 |
| **Answer Correctness** | F1(answer, ground_truth) + 0.5 × cos_sim(embed(answer), embed(gt)) | 1=完全正确，0=完全错误 |

### 关键约束
- ✅ **每次都默认跑全部 8 个指标**（无 `use_ragas` 开关）
- ✅ **必须基于 LangChain**：用 `langchain_openai.ChatOpenAI` + `ChatPromptTemplate` + `RunnableParallel`
- ✅ **模型可配置**：默认 mimo-v2.5，用户可在 `.env` 改 `MIMO_LITE_MODEL`

---

## 2. 📁 文件改动清单

### 新建
| 文件 | 作用 |
|---|---|
| `backend/app/services/eval/llm_metrics.py` | 3 个生成指标（Faithfulness / Answer Relevancy / Answer Correctness），LangChain RunnableParallel 风格 |
| `backend/app/services/eval/prompts.py` | 3 个评估 prompt 模板（中文） |

### 重写
| 文件 | 改动 |
|---|---|
| `backend/app/services/eval/metrics.py` | 5 个标准检索指标（recall_at_k / precision_at_k / hit_at_k / mrr / ndcg_at_k），用 `dict` 返回 |
| `backend/app/services/eval/runner.py` | 改 `__init__`（删 `use_ragas`），改 `_run_single_task` 调 5 检索 + 3 LLM 指标 |
| `backend/app/services/eval/report.py` | 改表头（4 列→5 列检索、3 列 LLM 改 faithfulness/relevancy/correctness），删 RAGAS 块 |
| `backend/app/services/eval/ragas_eval.py` | **删除**（自实现替代） |

### 保留不动
| 文件 | 原因 |
|---|---|
| `backend/app/services/eval/judge.py` | ❌ 删除（被 llm_metrics 替代） |
| `backend/app/services/eval/eval_schemas.py` | Pydantic schema 跟数据库字段对齐，重写 metrics/runner 后再调整 |
| `backend/app/services/llm_provider/openai_compatible.py` | 已有 `ChatOpenAI` 包装 |
| `backend/requirements.txt` | 删 `ragas`, `datasets`，保留 `langchain`, `langchain-openai`, `langchain-community` |

---

## 3. 🛠️ 详细设计

### 3.1 检索指标（[metrics.py](file:///d:/HHHUBS/clone/knoword/backend/app/services/eval/metrics.py)）

**输入**：`retrieved_ids: list[str]`（按 rank 排序的 chunk_id）、`source_chunk_ids: list[str]`（相关 chunk_id 集合）、`k: int = 5`

**输出**：`dict[str, float]`，key 统一为：
```python
{
    "recall_at_k":     float,  # Recall@K
    "precision_at_k":  float,  # Precision@K
    "hit_at_k":        float,  # Hit@K
    "mrr":             float,  # MRR（@k，标准做法）
    "ndcg_at_k":       float,  # NDCG@K
}
```

**算法**：
```python
def compute_retrieval_metrics(retrieved, source, k=5):
    relevant = set(source)
    retrieved_k = retrieved[:k]

    # Recall@K
    recall = len(set(retrieved_k) & relevant) / len(relevant) if relevant else 0.0

    # Precision@K
    precision = len(set(retrieved_k) & relevant) / k if k > 0 else 0.0

    # Hit@K
    hit = 1.0 if (set(retrieved_k) & relevant) else 0.0

    # MRR
    mrr = 0.0
    for i, cid in enumerate(retrieved_k, start=1):
        if cid in relevant:
            mrr = 1.0 / i
            break

    # NDCG@K（binary relevance）
    import math
    dcg = sum(
        (1.0 if retrieved_k[i] in relevant else 0.0) / math.log2(i + 2)
        for i in range(len(retrieved_k))
    )
    ideal_count = min(len(relevant), k)
    idcg = sum(1.0 / math.log2(i + 2) for i in range(ideal_count))
    ndcg = dcg / idcg if idcg > 0 else 0.0

    return {
        "recall_at_k": round(recall, 4),
        "precision_at_k": round(precision, 4),
        "hit_at_k": hit,
        "mrr": round(mrr, 4),
        "ndcg_at_k": round(ndcg, 4),
    }
```

### 3.2 LLM 指标（[llm_metrics.py](file:///d:/HHHUBS/clone/knoword/backend/app/services/eval/llm_metrics.py)）

**基础架构**：所有 LLM 指标用 LangChain 风格
```python
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableParallel
```

**3 个指标类**（统一接口）：

```python
class BaseLLMMetric:
    """LLM 指标基类。"""
    name: str
    def compute(self, *, question, answer, contexts, ground_truth) -> float:
        """返回 0-1 分数。"""

class Faithfulness(BaseLLMMetric):
    """拆 answer → statements → 验证每个是否 grounded。"""
    def compute(self, *, answer, contexts, **_) -> float:
        # Step 1: 拆 statements
        statements = self._extract_statements(answer)
        # Step 2: 每个 statement 验证（Verdict: 1=supported, 0=hallucinated）
        verdicts = self._verify_statements(statements, contexts)
        # Score = supported / total
        return sum(verdicts) / len(verdicts) if verdicts else 0.0

class AnswerRelevancy(BaseLLMMetric):
    """LLM 判 answer 是否切题（多次采样取平均）。"""
    def compute(self, *, question, answer, **_) -> float:
        # 1 次 LLM 调用，0/1 二元
        # 也可以 N 次反向问 AI（用 RAGAS 风格），但简化为 1 次 LLM judge
        score = self._judge_relevancy(question, answer)
        return score  # 0-1

class AnswerCorrectness(BaseLLMMetric):
    """F1 文本相似 + embedding 语义相似（0.5 + 0.5 加权）。"""
    def compute(self, *, answer, ground_truth, **_) -> float:
        if not ground_truth:
            return 0.0
        f1 = self._token_f1(answer, ground_truth)
        sem_sim = self._embedding_similarity(answer, ground_truth)
        return round(0.5 * f1 + 0.5 * sem_sim, 4)

    def _token_f1(self, a, b) -> float:
        # 标准 token F1（中文按字符 / 英文按 word）
        ta = set(self._tokenize(a))
        tb = set(self._tokenize(b))
        if not ta or not tb:
            return 0.0
        common = ta & tb
        precision = len(common) / len(ta)
        recall = len(common) / len(tb)
        return 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

    def _embedding_similarity(self, a, b) -> float:
        # 用 settings.OLLAMA_EMBED_MODEL 算 cos sim
        from app.services.embedding import get_embedding_provider
        provider = get_embedding_provider(settings.OLLAMA_EMBED_MODEL)
        import numpy as np
        va = provider.embed_query(a)
        vb = provider.embed_query(b)
        a_vec, b_vec = np.array(va), np.array(vb)
        return float(np.dot(a_vec, b_vec) / (np.linalg.norm(a_vec) * np.linalg.norm(b_vec)))
```

**LangChain RunnableParallel 批量调用**（3 个指标并发）：
```python
async def compute_all_metrics(*, question, answer, contexts, ground_truth) -> dict:
    from langchain_core.runnables import RunnableParallel
    metrics = [Faithfulness(llm), AnswerRelevancy(llm), AnswerCorrectness()]
    chain = RunnableParallel(**{m.name: m.as_runnable() for m in metrics})
    return await chain.ainvoke({
        "question": question,
        "answer": answer,
        "contexts": contexts,
        "ground_truth": ground_truth,
    })
```

### 3.3 Runner 改造（[runner.py](file:///d:/HHHUBS/clone/knoword/backend/app/services/eval/runner.py)）

**改动点**：
1. `__init__` 删 `use_ragas` 参数
2. `_run_single_task` 改成：
   ```python
   # 1. 检索（保留）
   chunks = await strategy.retrieve(...)

   # 2. 5 检索指标
   ret_metrics = compute_retrieval_metrics(
       [c["chunk_id"] for c in chunks],
       task["source_chunk_ids"],
       k=5,
   )

   # 3. 生成（保留）
   response = await llm.ainvoke(...)

   # 4. 3 LLM 指标（LangChain RunnableParallel 并发）
   llm_scores = await compute_all_metrics(
       question=task["question"],
       answer=answer,
       contexts=[c["content"] for c in chunks[:5]],
       ground_truth=task["ground_truth"],
   )
   ```
3. `_finalize_run` 删 RAGAS 回填代码
4. `_aggregate` 用新 key：`retrieval` 包含 5 个新指标，`generation` 包含 3 个新指标

### 3.4 报告改造（[report.py](file:///d:/HHHUBS/clone/knoword/backend/app/services/eval/report.py)）

**检索指标表头**（5 列）：
```markdown
| Embedding | Retrieval | Rerank | Recall@5 | Precision@5 | Hit@5 | MRR | NDCG@5 |
```

**生成指标表头**（3 列，改名）：
```markdown
| Generation | Faithfulness | Answer Relevancy | Answer Correctness |
```

**删 RAGAS 块**（第 194-231 行整段删）

---

## 4. ✅ 实施步骤（按顺序）

| 步骤 | 内容 | 验证 |
|---|---|---|
| 1 | 改 `metrics.py`（5 个标准指标） | 单测：retrieved=['a','b','c','d','e'], source=['a','c'], k=5 → recall=0.5, precision=0.4, hit=1, mrr=1.0, ndcg=... |
| 2 | 新建 `prompts.py`（3 个 LLM 评估 prompt） | 单元检查 prompt 格式 |
| 3 | 新建 `llm_metrics.py`（3 个指标 + RunnableParallel） | 单测：跑 1 样本，看 3 个分数都返回 |
| 4 | 改 `runner.py`（删 use_ragas，集成 5+3 指标） | 跑 1 个 task 看 result dict 有 8 个指标 |
| 5 | 改 `report.py`（改表头、删 RAGAS 块） | 跑 1 次评估看 markdown 输出 |
| 6 | 删 `judge.py` 和 `ragas_eval.py` | git status 确认 |
| 7 | 改 `requirements.txt`（删 ragas、datasets） | pip list 确认 |
| 8 | 跑完整评估（5 qa × 3 ret × 2 gen = 30 task） | 看报告数据合理 |
| 9 | commit | `feat/refactor: 8 指标全面重构，删 LLM-as-Judge/RAGAS` |

---

## 5. 🧪 验证标准

### 5.1 检索指标单元测试
```python
# 场景 1：完美召回
retrieved = ['a', 'b', 'c', 'd', 'e']
source = ['a', 'c']
metrics = compute_retrieval_metrics(retrieved, source, k=5)
# 预期：recall=0.5, precision=0.4, hit=1, mrr=1.0, ndcg>0

# 场景 2：完全不召回
retrieved = ['x', 'y', 'z', 'p', 'q']
source = ['a', 'c']
metrics = compute_retrieval_metrics(retrieved, source, k=5)
# 预期：recall=0, precision=0, hit=0, mrr=0, ndcg=0

# 场景 3：source 为空
retrieved = ['a', 'b']
source = []
metrics = compute_retrieval_metrics(retrieved, source, k=5)
# 预期：recall=0, precision=0, hit=0, mrr=0, ndcg=0
```

### 5.2 LLM 指标单元测试
```python
# Faithfulness: answer 完全 grounded
answer = "巴黎是法国首都"
contexts = ["巴黎是法国首都。法国在欧洲西部。"]
faith = Faithfulness(llm).compute(answer=answer, contexts=contexts)
# 预期：1.0

# Faithfulness: answer 有幻觉
answer = "巴黎人口 5000 万，是亚洲城市"  # 全部是错的
contexts = ["巴黎是法国首都。"]
faith = Faithfulness(llm).compute(answer=answer, contexts=contexts)
# 预期：< 0.5
```

### 5.3 端到端验证
- 跑 1 次评估（5 qa × 3 retrieval × 2 gen = 30 task）
- 看 report JSON：
  - 8 个指标都有值
  - 检索指标在不同 strategy 下数值不同（区分度）
  - LLM 指标分布在 0.3-0.9 之间
- 看 report MD：
  - 检索表有 5 列
  - 生成表有 3 列（faithfulness/relevancy/correctness）
  - 没有 RAGAS 段

---

## 6. 📊 预期效果

| 项目 | 旧 | 新 |
|---|---|---|
| 检索指标数 | 4（hit@5, mrr, ndcg@5, recall@5） | 5（+ precision_at_5）|
| 生成指标数 | 3（LLM-as-Judge faithfulness/relevance/completeness） | 3（faithfulness/answer_relevancy/answer_correctness）|
| 指标一致性 | LLM-as-Judge 不基于 context | Faithfulness **基于 context 验证 groundedness** |
| 实现 | LangChain + RAGAS 0.4.3 + 降级冲突 | 纯 LangChain + 自实现 |
| 开关 | use_ragas | ❌ 全部默认跑 |
| LangChain 风格 | 6 处底层库 | 评估层也用 LangChain RunnableParallel |

---

## 7. ⚠️ 风险与回滚

### 风险
- **LLM 指标单样本慢**（3 个指标并发 ~10-20s）→ 已有 4 并发，可接受
- **embed_query 多 2 次**（Answer Correctness 算 2 次 embedding）→ 可缓存，但目前不用
- **Faithfulness LLM 调用 2 次**（拆 statements + 验证）→ 必要时合并为 1 次

### 回滚
- 老 `judge.py` / `ragas_eval.py` 先 git stash 备份
- 评估报告永久保留，老报告不受影响

---

## ❓ 待用户确认

1. **8 个指标全用** ✓ 用户明确说
2. **Faithfulness 算法**：拆 statements 逐个验（2 次 LLM 调用）or 单次 LLM 直接评 0-1（1 次 LLM 调用）？
3. **Answer Relevancy 算法**：用 RAGAS 风格（embed N 个反向问题）or 简单 LLM judge（1 次调用）？
4. **Answer Correctness** 权重：F1 0.5 + embedding 0.5 ✓
5. **指标 key 命名**：`recall_at_5` / `precision_at_5` / `hit_at_5` / `mrr` / `ndcg_at_5` ✓

确认后开始实施。
