"""Golden Dataset 构建器 — 从 KB 文档 chunks 自动生成 QA。"""
import asyncio
import logging
import random
from typing import List

from app.config import settings
from app.services.llm_provider import get_llm_provider
from app.services.vectorstore import get_collection

logger = logging.getLogger(__name__)


QA_GENERATION_PROMPT = """你是一个高质量的问答数据集生成专家。请基于以下文档片段，生成一个有意义的问题和对应的简短答案。

【文档片段】
{chunk}

要求：
1. 问题必须能从文档片段中直接找到答案
2. 答案应该简洁、客观（1-3 句话）
3. 问题不要太简单（避免"是什么"类问题）

请严格输出 JSON（不要任何额外说明）：
{{"question": "...", "answer": "..."}}"""


# 合并版 prompt：1 次 LLM 调用同时生成 QA + 选 chunks
# 候选 = target 1 个 + 4 桶采样 20 个，下标 [0..20]
# 4 桶：embedding top-5（强相关）+ 21-100 随机 5（中等）+ BM25 top-5（关键词）+ 跨章节随机 5
COMBINED_QA_PROMPT = """你是问答数据集生成专家。请基于以下 21 个文档片段（[0] 是最相关的 target，[1..20] 是混合候选：可能强相关、可能只关键词命中、可能完全不相关），生成一个有意义的问题和答案，并标出"回答这个问题实际用到了哪几个片段"。

【文档片段】
{target_block}

{candidate_blocks}

要求：
1. 基于 [0] target 片段（最相关）生成 QA
2. 答案要忠实于片段内容，简短、客观（1-3 句话）
3. 关键：标出 used_chunks（回答这个问题真正用到的片段下标列表，按相关性从高到低排序），如 [0, 2, 5]
4. 候选里有"看起来像但内容无关"的片段（hard negative），不要被误导——只有真的支持答案的才标
5. 通常 1-5 个就够，没把握宁可少选
6. 问题不要太简单（避免"是什么"类问题），优先问"为什么/怎么/区别/包含哪些"类

请严格输出 JSON（不要任何额外说明）：
{{"question": "...", "answer": "...", "used_chunks": [0, 2, 5]}}"""


# P2 multi-hop prompt：要求 used_chunks 至少 2 个，target + 至少 1 个 peer
# 候选 = target 1 个 + 4 桶采样 20 个 + 2 个 peer（"同主题跨章节"），下标 [0..22]
MULTIHOP_QA_PROMPT = """你是问答数据集生成专家。这是一道 MULTI-HOP 题目：必须综合【主片段】+ 至少 1 个【peer】才能完整回答。请基于以下片段生成 QA，并标出 used_chunks（必须包含 [0] + 至少 1 个 peer）。

【主片段】
{target_block}

【混合候选（4 桶）】
{candidate_blocks}

【peer 片段（同主题跨章节）】
{peer_blocks}

要求：
1. 必须综合主片段 + 至少 1 个 peer 才能完整回答
2. 答案要忠实于片段内容，简短、客观（2-4 句话，可引用多片段）
3. used_chunks 至少 2 个：必须包含 [0]（主片段）+ 至少 1 个 peer
4. 候选里有"看起来像但内容无关"的片段（hard negative），不要被误导
5. 问题要"必须多片段综合"（如"为什么 A 会导致 B，B 又如何影响 C"、"A 和 B 的共同点 / 区别"）

请严格输出 JSON（不要任何额外说明）：
{{"question": "...", "answer": "...", "used_chunks": [0, 21, 22]}}"""


# embedding 召回候选数（不含 target）
SELECTION_CANDIDATES = 20


class GoldenDatasetBuilder:
    """从 KB 文档 chunks 自动生成 QA 三元组（Question & Answer）。

    默认生成 20 道题（来自 settings.DEFAULT_EVAL_QA_COUNT），可在创建时覆盖。
    """

    DEFAULT_QA_COUNT = 20

    def __init__(self, llm_model: str | None = None):
        # 用 mimo-v2.5 生成 QA（轻量即可）
        self._provider = get_llm_provider(llm_model or settings.MIMO_LITE_MODEL)
        self._llm = self._provider.get_chat_model(temperature=0.5)
        # embedding 缓存（按 KB）
        self._chunk_emb_cache: dict[str, list[list[float]]] = {}

    async def generate(
        self, kb_id: int, n_questions: int | None = None
    ) -> List[dict]:
        """从 KB 文档 chunks 自动生成 QA 三元组（合并版两阶段法）。

        流程：
        1. 算一次全 KB chunks embedding（缓存复用）
        2. 随机采样 N 个 target chunks
        3. 对每个 target：embedding 召回 top-20 候选 → 1 次 LLM 调用
           同时生成 QA + 标出 used_chunks（回答这个问题真正用到的 chunks）

        优势：
        - 距离不限（embedding 召回覆盖全 KB，跨章节 chunk 也能覆盖）
        - 数量灵活（LLM 自由挑 1-10 个）
        - 真正相关（不是机械填的）
        - 1 次 LLM 调用（不是 2 次，节省成本）
        - embedding 缓存（KB chunks 只算 1 次）
        """
        n = n_questions or settings.DEFAULT_EVAL_QA_COUNT
        logger.info(f"为 KB {kb_id} 生成 {n} 道 QA（合并版两阶段法）")

        # 0. 详细日志路径（同时输出到 logs/eval.log + logs/dataset_gen_detail.log）
        import os, traceback
        from datetime import datetime
        from app.utils.logging_setup import LOG_DIR
        log_path = os.path.join(
            LOG_DIR,
            f"dataset_gen_kb{kb_id}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')[:-3]}.log",
        )
        # 详情文件 handle（专用，不走主 logger）
        os.makedirs(LOG_DIR, exist_ok=True)
        detail_handler = logging.FileHandler(log_path, encoding="utf-8")
        detail_handler.setLevel(logging.DEBUG)
        detail_handler.setFormatter(
            logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s", "%H:%M:%S")
        )
        detail_logger = logging.getLogger(f"app.services.eval.dataset_builder.detail.{kb_id}.{datetime.now().strftime('%H%M%S%f')}")
        detail_logger.setLevel(logging.DEBUG)
        detail_logger.propagate = False
        detail_logger.addHandler(detail_handler)

        def _wlog(msg: str, level: str = "INFO") -> None:
            line = f"[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] [{level}] {msg}"
            print(line)
            getattr(detail_logger, level.lower(), detail_logger.info)(msg)

        _wlog(f"=== 开始生成 ===")
        _wlog(f"log file: {log_path}")
        _wlog(f"kb_id={kb_id}, n_questions={n}")

        # 1. 取 KB 表里的 embedding_model（按 KB 路由到正确的 ChromaDB collection）
        from app.db.database import async_session_factory
        from app.models.models import KnowledgeBase
        from sqlalchemy import select as sa_select

        async with async_session_factory() as db:
            result = await db.execute(
                sa_select(KnowledgeBase).where(KnowledgeBase.id == kb_id)
            )
            kb = result.scalar_one_or_none()
            if not kb:
                _wlog(f"KB {kb_id} 不存在", "ERROR")
                return []
            embedding_model = kb.embedding_model or "Qwen/Qwen3-Embedding-8B"
        _wlog(f"embedding_model={embedding_model}")

        # 2. 取 KB chunks（按 embedding_model 路由 collection）
        kb_data = self._get_kb_chunks(kb_id, embedding_model)
        chunks = kb_data["chunks"]
        if not chunks:
            _wlog(f"KB {kb_id} 在 collection {embedding_model} 里没有 chunks", "ERROR")
            return []
        _wlog(f"chunks 总数={len(chunks)}")

        # 3. 算一次全 KB chunks embedding（缓存）
        chunk_embs = await self._get_or_compute_chunk_embeddings(
            chunks, embedding_model
        )
        _wlog(f"chunk embedding 缓存完成，共 {len(chunk_embs)} 个")

        # 3. 随机采样
        sampled = random.sample(chunks, min(n, len(chunks)))
        _wlog(f"sampled targets={len(sampled)}")

        # 3.1 P2 multi-hop：30% 的 target 标记为 multi-hop，并预算 peers
        # peer 选法：从 sims[5:20] 选 2 个不同 doc_id 的（"同主题但跨章节"）
        #   这部分 0 次 LLM 调用，只用 chunk_embs 缓存 + 1 次 target embedding
        import math as _math
        def _cos(a, b):
            dot = sum(x * y for x, y in zip(a, b))
            na = _math.sqrt(sum(x * x for x in a))
            nb = _math.sqrt(sum(x * x for x in b))
            return dot / (na * nb) if na and nb else 0.0

        multihop_ratio = 0.3
        target_with_peers = []
        for tgt in sampled:
            is_multihop = random.random() < multihop_ratio
            target_with_peers.append({
                "target": tgt,
                "is_multihop": is_multihop,
                "extra_peer_ids": [],
            })
        n_mh = sum(1 for e in target_with_peers if e["is_multihop"])
        _wlog(f"multi-hop: 标记 {n_mh}/{len(target_with_peers)} 个 target 为 multi-hop（ratio={multihop_ratio}）")

        # 给 multi-hop 的 target 算 peer（每个 multi-hop target 1 次 embedding 调用）
        async def _compute_peers(entry: dict) -> None:
            if not entry["is_multihop"]:
                return
            try:
                from app.services.embedding import get_embedding_provider
                embedder = get_embedding_provider(embedding_model)
                tgt = entry["target"]
                # target 在 chunk_embs 里的 index
                tgt_idx = next(
                    (i for i, c in enumerate(chunks) if c["chunk_id"] == tgt["chunk_id"]),
                    None,
                )
                if tgt_idx is None:
                    return
                t_emb = chunk_embs[tgt_idx]  # 复用缓存，0 次额外 embedding 调用
                sims = []
                for i, (c, ce) in enumerate(zip(chunks, chunk_embs)):
                    if c["chunk_id"] == tgt["chunk_id"]:
                        continue
                    sims.append((_cos(t_emb, ce), i))
                sims.sort(reverse=True)
                # 跳过 top-5（已在 bucket A），从 [5..20] 选 2 个不同 doc_id
                seen_docs = {tgt["doc_id"]}
                picked = []
                for _, i in sims[5:20]:
                    if chunks[i]["doc_id"] not in seen_docs:
                        picked.append(i)
                        seen_docs.add(chunks[i]["doc_id"])
                    if len(picked) == 2:
                        break
                entry["extra_peer_ids"] = picked
            except Exception as e:
                logger.warning(f"multi-hop peer 计算失败: {e}")

        await asyncio.gather(*[_compute_peers(e) for e in target_with_peers])
        n_mh_done = sum(1 for e in target_with_peers if e["extra_peer_ids"])
        _wlog(f"multi-hop 完成：{n_mh_done}/{n_mh} 个 multi-hop target 找到 peers")

        _wlog(f"开始并发生成（concurrency=4）...")

        # 4. 并发生成 QA（每个 target 1 次 LLM 调用）
        sem = asyncio.Semaphore(4)

        async def gen_one(entry: dict, idx: int) -> dict | None:
            async with sem:
                try:
                    target = entry["target"]
                    extra_peer_ids = entry["extra_peer_ids"]
                    is_multihop = entry["is_multihop"]
                    result = await self._generate_qa_with_selection(
                        target, chunks, chunk_embs, embedding_model,
                        extra_peer_ids=extra_peer_ids,
                        is_multihop=is_multihop,
                    )
                    if result is None:
                        _wlog(f"target[{idx}] chunk_id={target['chunk_id']} → None（LLM 失败/解析失败）", "WARN")
                    else:
                        _wlog(
                            f"target[{idx}] chunk_id={target['chunk_id']} → OK "
                            f"(used {len(result['source_chunk_ids'])} chunks, multihop={is_multihop})"
                        )
                        _wlog(f"  Q: {result['question']}")
                        _wlog(f"  A: {result['ground_truth']}")
                        _wlog(f"  source_chunk_ids: {result['source_chunk_ids']}")
                    return result
                except Exception as e:
                    _wlog(f"target[{idx}] chunk_id={entry['target']['chunk_id']} → EXCEPTION: {e}", "ERROR")
                    _wlog(traceback.format_exc(), "ERROR")
                    return None

        results = await asyncio.gather(
            *[gen_one(e, i) for i, e in enumerate(target_with_peers)], return_exceptions=True
        )

        # 5. 过滤异常 + 记录 gather 层异常
        qa_pairs = []
        for i, r in enumerate(results):
            if isinstance(r, Exception):
                _wlog(
                    f"target[{i}] chunk_id={sampled[i]['chunk_id']} → GATHER EXCEPTION: {r}",
                    "ERROR",
                )
                _wlog(traceback.format_exc(), "ERROR")
                continue
            if not r:
                continue
            qa_pairs.append(r)

        # 5.1 P3 out-of-scope：每 10 道题加 1 道 KB 中无答案的题
        n_oos = max(1, len(qa_pairs) // 10) if qa_pairs else 0
        if n_oos > 0:
            _wlog(f"P3 out-of-scope: 追加 {n_oos} 道 KB 中无答案的题")
            oos_pairs = await self._generate_oos_questions(n_oos, kb_id, chunks)
            qa_pairs.extend(oos_pairs)
            _wlog(f"追加完成，最终 qa_pairs={len(qa_pairs)}（其中 {n_oos} 道 OOS）")

        # 6. 写汇总
        fail_count = len(sampled) - sum(1 for q in qa_pairs if not q.get("is_out_of_scope"))
        _wlog(f"=== 生成完成 ===")
        _wlog(f"成功: {len(qa_pairs) - n_oos}/{len(sampled)}（失败 {fail_count} 个）+ OOS {n_oos} 道")
        if qa_pairs:
            n_mh_done = sum(1 for q in qa_pairs if q.get("is_multihop"))
            _wlog(f"multi-hop: {n_mh_done}/{len(qa_pairs) - n_oos}（{n_mh_done/(len(qa_pairs)-n_oos or 1):.0%}）")
            avg_gt = sum(len(q["source_chunk_ids"]) for q in qa_pairs if not q.get("is_out_of_scope")) / max(1, len(qa_pairs) - n_oos)
            _wlog(f"平均 ground truth chunks（不含 OOS）: {avg_gt:.1f}")
            from collections import Counter
            dist = Counter(len(q["source_chunk_ids"]) for q in qa_pairs if not q.get("is_out_of_scope"))
            _wlog(f"chunk_ids 长度分布（不含 OOS）: {dict(sorted(dist.items()))}")
        _wlog(f"详细日志: {log_path}")
        logger.info(f"dataset generate log: {log_path}")
        return qa_pairs

    async def _generate_oos_questions(
        self, n: int, kb_id: int, chunks: list[dict]
    ) -> list[dict]:
        """P3：生成 n 道 out-of-scope 题（KB 中无答案）。

        策略：用 LLM 基于 KB 实际内容生成"明显不在 KB 主题内"的问题。
        ground_truth 固定为 "资料中未找到相关信息"，source_chunk_ids 为空。
        评估时 Recall@K 必然 = 0；Faithfulness 应该低（模型应拒绝答或答得不好）。
        """
        oos_pairs: list[dict] = []
        # 抽 3-5 个 chunk 的 title/doc_name 给 LLM 当 context
        sample_titles = []
        seen_titles = set()
        for c in chunks:
            # 取 chunk content 前 60 字符当"KB 主题" hint
            title = c.get("content", "")[:60].strip()
            if title and title not in seen_titles:
                sample_titles.append(title)
                seen_titles.add(title)
            if len(sample_titles) >= 5:
                break

        oos_prompt = """你是一个数据生成专家。知识库（KB）的内容主题大致是：

{topics}

请生成 {n} 道"明显不在这个 KB 主题范围内"的问题（out-of-scope）。要求：
1. 问题应该跟 KB 主题**完全不同领域**（如 KB 是游戏手册，OOS 问题可以问"怎么做红烧肉"、"Python 装饰器"、"北京到上海高铁时刻表"）
2. 问题要"看似合理但绝对无法从 KB 答出"
3. 每题 1 行，简洁自然，不要编号
4. 用 JSON 数组格式输出：["问题1", "问题2", "问题3"]"""

        try:
            topic_text = "\n".join(f"- {t}" for t in sample_titles)
            prompt = oos_prompt.format(topics=topic_text, n=n)
            response = await self._llm.ainvoke([{"role": "user", "content": prompt}])
            content = response.content if hasattr(response, "content") else str(response)

            # 解析 JSON 数组
            import json, re
            match = re.search(r"\[\s*[\s\S]*?\]", content)
            if match:
                arr = json.loads(match.group(0))
                for q in arr[:n]:
                    if isinstance(q, str) and q.strip():
                        oos_pairs.append({
                            "question": q.strip(),
                            "ground_truth": "资料中未找到相关信息",
                            "source_chunk_ids": [],   # ← 关键：空
                            "source_doc_ids": [],
                            "is_out_of_scope": True,  # ← 标识
                        })
            if not oos_pairs:
                # LLM 失败 / 解析失败，fallback 用通用 OOS 题
                _wlog("OOS LLM 生成失败，用 fallback 通用题", "WARN")
                for i in range(n):
                    oos_pairs.append({
                        "question": f"请介绍一下第 {i+1} 个常见编程语言的优缺点（与本知识库主题无关）",
                        "ground_truth": "资料中未找到相关信息",
                        "source_chunk_ids": [],
                        "source_doc_ids": [],
                        "is_out_of_scope": True,
                    })
        except Exception as e:
            logger.exception(f"OOS 生成失败: {e}")
            for i in range(n):
                oos_pairs.append({
                    "question": f"请回答一个与本知识库主题无关的问题（{i+1}）",
                    "ground_truth": "资料中未找到相关信息",
                    "source_chunk_ids": [],
                    "source_doc_ids": [],
                    "is_out_of_scope": True,
                })

        return oos_pairs[:n]

    def _get_kb_chunks(self, kb_id: int, embedding_model: str | None = None) -> dict:
        """从 ChromaDB 读取 KB 的所有 chunk。

        返回: {"chunks": [...], "embedding_model": "..."}

        embedding_model 必传：用于路由到正确的 collection（按 embedding_model 分 collection）。
        """
        try:
            collection = get_collection(embedding_model)
            data = collection.get(where={"kb_id": kb_id}, limit=1000)
            if not data.get("documents"):
                return {"chunks": [], "embedding_model": embedding_model}
            chunks = []
            for i, (doc, meta) in enumerate(zip(data["documents"], data["metadatas"])):
                chunks.append({
                    "chunk_id": meta.get("chunk_id") or meta.get("id", str(i)),
                    "doc_id": meta.get("doc_id", 0),
                    "chunk_index": meta.get("chunk_index", i),
                    "content": doc,
                })
            return {"chunks": chunks, "embedding_model": embedding_model}
        except Exception as e:
            logger.error(f"读取 KB chunks 失败: {e}")
            return {"chunks": [], "embedding_model": embedding_model}

    async def _get_or_compute_chunk_embeddings(
        self, chunks: list[dict], embedding_model: str
    ) -> list[list[float]]:
        """算 1 次全 KB chunks embedding 并缓存（按 embedding_model 分 key）。"""
        cache_key = embedding_model
        if cache_key in self._chunk_emb_cache:
            cached = self._chunk_emb_cache[cache_key]
            if len(cached) == len(chunks):
                return cached
        from app.services.embedding import get_embedding_provider
        embedder = get_embedding_provider(embedding_model)
        # 并发算所有 chunks embedding
        embs = await asyncio.gather(
            *[embedder.embed_query(c["content"][:1000]) for c in chunks]
        )
        self._chunk_emb_cache[cache_key] = list(embs)
        logger.info(f"已缓存 {len(chunks)} 个 chunk 的 embedding (model={embedding_model})")
        return self._chunk_emb_cache[cache_key]

    async def _generate_qa_with_selection(
        self,
        target: dict,
        all_chunks: list[dict],
        chunk_embs: list[list[float]],
        embedding_model: str,
        extra_peer_ids: list[int] | None = None,
        is_multihop: bool = False,
    ) -> dict | None:
        """合并版两阶段：1 次 LLM 调用同时生成 QA + 选 chunks。

        候选池（P1 改造：hard negatives 分桶采样）：
        - 5 个：embedding top-5（强相关，可能进 ground truth）
        - 5 个：embedding 21-100 中随机 5 个（中等距离，hard negative）
        - 5 个：BM25 top-5（关键词命中但语义不匹配，最难）
        - 5 个：跨章节随机 5 个（真正无关，验证模型不幻觉）

        P2 multi-hop（is_multihop=True 时）：
        - 多 2 个 extra_peer（"同主题跨章节"），下标 [21], [22]
        - 用 MULTIHOP_QA_PROMPT，要求 used_chunks 至少 2 个

        流程：
        1. 4 桶候选 → 20 个 + target = 21 个 chunks
           （multi-hop：再加 2 peer = 23 个）
        2. 把 chunks 喂给 LLM
        3. LLM 返回 {question, answer, used_chunks: [...]}
        4. used_chunks 映射回 chunk_ids
        """
        try:
            import math
            from app.services.embedding import get_embedding_provider

            def _cos_sim(a, b):
                """内联 cos 相似度（避免依赖外部 utils）。"""
                dot = sum(x * y for x, y in zip(a, b))
                na = math.sqrt(sum(x * x for x in a))
                nb = math.sqrt(sum(x * x for x in b))
                return dot / (na * nb) if na and nb else 0.0

            # 1. embedding 召回（按相似度，不含 target 自身）
            embedder = get_embedding_provider(embedding_model)
            target_emb = await embedder.embed_query(target["content"][:1000])

            sims = []
            for i, (c, ce) in enumerate(zip(all_chunks, chunk_embs)):
                if c["chunk_id"] == target["chunk_id"]:
                    continue
                sims.append((_cos_sim(target_emb, ce), i))
            sims.sort(reverse=True)

            # 2. P1 分桶采样：4 桶 × 5 个 = 20 个候选
            used_set = {target["chunk_id"]}
            # 桶 A：embedding top-5（强相关）
            bucket_a = [i for _, i in sims[:5]]
            # 桶 B：embedding 21-100 中随机 5 个（hard negative，中等距离）
            mid_pool = [i for _, i in sims[20:100]]
            bucket_b = self._sample(mid_pool, 5, used_set)
            # 桶 C：BM25 top-5（关键词命中但语义不匹配）
            excluded_c = used_set | {all_chunks[i]["chunk_id"] for i in bucket_a + bucket_b}
            bucket_c = self._bm25_top_k(target, all_chunks, k=5, exclude=excluded_c)
            # 桶 D：跨章节随机 5 个（真正无关）
            excluded_d = used_set | {all_chunks[i]["chunk_id"] for i in bucket_a + bucket_b + bucket_c}
            bucket_d = self._random_k(all_chunks, k=5, exclude=excluded_d)

            candidate_indices = bucket_a + bucket_b + bucket_c + bucket_d
            candidates = [all_chunks[i] for i in candidate_indices if 0 <= i < len(all_chunks)]

            # 3. P2 multi-hop：追加 2 个 peer（"同主题跨章节"）
            peer_chunks = []
            if is_multihop and extra_peer_ids:
                for pid in extra_peer_ids:
                    if 0 <= pid < len(all_chunks):
                        c = all_chunks[pid]
                        if c["chunk_id"] not in used_set:
                            peer_chunks.append(c)
                            used_set.add(c["chunk_id"])

            # 4. 构造 candidates 列表（target 排 [0]）
            ordered = [target] + candidates + peer_chunks  # [0]=target, [1..N]=候选, [N+1..]=peer

            # 5. 合并 prompt：1 次 LLM 调用
            if is_multihop and peer_chunks:
                prompt = self._build_multihop_prompt(ordered, len(candidates))
            else:
                prompt = self._build_combined_prompt(ordered)

            # 6. LLM 调用
            response = await self._llm.ainvoke([{"role": "user", "content": prompt}])
            content = response.content if hasattr(response, "content") else str(response)
            data = self._parse_combined_json(content)
            if not data:
                return None

            # 7. used_chunks 映射回 chunk_ids
            used_indices = data.get("used_chunks") or [0]  # fallback: 至少用 target
            used_chunks = []
            seen_ids = set()
            for idx in used_indices:
                if 0 <= idx < len(ordered):
                    c = ordered[idx]
                    if c["chunk_id"] not in seen_ids:
                        seen_ids.add(c["chunk_id"])
                        used_chunks.append(c)
            if not used_chunks:
                used_chunks = [target]

            return {
                "question": data["question"],
                "ground_truth": data["answer"],
                "source_chunk_ids": [c["chunk_id"] for c in used_chunks],
                "source_doc_ids": list({c["doc_id"] for c in used_chunks}),
                "is_multihop": is_multihop and len(used_chunks) >= 2,  # 标记是否真的 multi-hop
            }
        except Exception as e:
            logger.exception(f"合并版生成失败: {e}")
            return None

    @staticmethod
    def _sample(pool: list, k: int, exclude: set) -> list:
        """从 pool 随机抽 k 个 index。exclude 是 chunk_id 集合，用于过滤。"""
        import random
        filtered = [i for i in pool if i is not None]
        if len(filtered) <= k:
            return filtered
        return random.sample(filtered, k)

    @staticmethod
    def _random_k(all_chunks: list[dict], k: int, exclude: set) -> list:
        """从 all_chunks 随机抽 k 个 index，跳过 exclude 里的 chunk_id。"""
        import random
        valid_indices = [i for i, c in enumerate(all_chunks) if c["chunk_id"] not in exclude]
        if len(valid_indices) <= k:
            return valid_indices
        return random.sample(valid_indices, k)

    @staticmethod
    def _bm25_top_k(target: dict, all_chunks: list[dict], k: int, exclude: set) -> list:
        """BM25 top-k（关键词命中 hard negative）。

        使用 rank_bm25 算 target content vs all_chunks 的 BM25 分数，
        返回 BM25 分数 top-k 的 index（已排除 exclude）。
        依赖 rank_bm25 + jieba（requirements.txt 已声明）。
        """
        try:
            from rank_bm25 import BM25Okapi
            import jieba
        except ImportError:
            # 没装 BM25 就退化（不影响其他 3 桶）
            return []

        def _tokenize(text: str) -> list[str]:
            text = (text or "")[:1000]
            if any("\u4e00" <= ch <= "\u9fff" for ch in text):
                return [w for w in jieba.cut(text) if w.strip()]
            return text.lower().split()

        target_tokens = _tokenize(target["content"])
        corpus = [_tokenize(c["content"]) for c in all_chunks]
        if not any(corpus):
            return []

        try:
            bm25 = BM25Okapi(corpus)
            scores = bm25.get_scores(target_tokens)
        except Exception:
            return []

        # 按分数降序，过滤掉 exclude
        ranked = sorted(
            [(s, i) for i, s in enumerate(scores) if all_chunks[i]["chunk_id"] not in exclude],
            key=lambda x: -x[0],
        )
        return [i for _, i in ranked[:k]]

    def _build_combined_prompt(self, ordered: list[dict]) -> str:
        """构建"生成 QA + 选 chunks"合并 prompt。

        ordered[0] = target（最相关），[1..20] = 4 桶混合候选
        桶序：[1..5]=embedding top-5，[6..10]=21-100 随机（hard negative），
              [11..15]=BM25 top-5（关键词命中），[16..20]=跨章节随机
        """
        target_block = f"[0] (target, 最相关)\n{ordered[0]['content'][:800]}"
        cand_blocks = []
        # 桶标签
        bucket_labels = (
            ["(embedding 强相关)"] * 5
            + ["(hard negative, 中等距离)"] * 5
            + ["(BM25 关键词命中)"] * 5
            + ["(跨章节随机)"] * 5
        )
        for i, c in enumerate(ordered[1:], 1):
            label = bucket_labels[i - 1] if i - 1 < len(bucket_labels) else "(候选)"
            cand_blocks.append(f"[{i}] {label}\n{c['content'][:500]}")
        return COMBINED_QA_PROMPT.format(
            target_block=target_block,
            candidate_blocks="\n\n".join(cand_blocks),
        )

    def _build_multihop_prompt(self, ordered: list[dict], n_candidates: int) -> str:
        """构建 multi-hop 版 prompt。

        ordered[0] = target，[1..n_candidates] = 4 桶混合候选，
                     [n_candidates+1..] = 2 个 peer（"同主题跨章节"）
        要求：used_chunks 至少 2 个，其中一个必须是 [0] target，另一个是 peer。
        """
        target_block = f"[0] (target, 主片段)\n{ordered[0]['content'][:800]}"
        cand_blocks = []
        bucket_labels = (
            ["(embedding 强相关)"] * 5
            + ["(hard negative, 中等距离)"] * 5
            + ["(BM25 关键词命中)"] * 5
            + ["(跨章节随机)"] * 5
        )
        for i in range(1, n_candidates + 1):
            c = ordered[i]
            label = bucket_labels[i - 1] if i - 1 < len(bucket_labels) else "(候选)"
            cand_blocks.append(f"[{i}] {label}\n{c['content'][:500]}")
        # peers
        peer_blocks = []
        for j, idx in enumerate(range(n_candidates + 1, len(ordered))):
            c = ordered[idx]
            peer_blocks.append(
                f"[{idx}] (peer{j+1}, 同主题跨章节)\n{c['content'][:500]}"
            )
        return MULTIHOP_QA_PROMPT.format(
            target_block=target_block,
            candidate_blocks="\n\n".join(cand_blocks),
            peer_blocks="\n\n".join(peer_blocks),
        )

    def _parse_combined_json(self, content: str) -> dict | None:
        """解析 LLM 返回的合并 JSON。"""
        import json, re
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
        if match:
            content = match.group(1)
        try:
            data = json.loads(content.strip())
            return {
                "question": data.get("question", "").strip(),
                "answer": data.get("answer", "").strip(),
                "used_chunks": data.get("used_chunks", []),
            }
        except Exception as e:
            logger.warning(f"解析 JSON 失败: {e}\nContent: {content[:200]}")
            return None

    async def _generate_qa_for_chunk(self, chunk: dict) -> dict | None:
        """为单个 chunk 生成一个 QA（fallback 用，不带 chunks 选取）。"""
        try:
            prompt = QA_GENERATION_PROMPT.format(chunk=chunk["content"][:1500])
            response = await self._llm.ainvoke([{"role": "user", "content": prompt}])
            content = response.content if hasattr(response, "content") else str(response)
            import json, re
            match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
            if match:
                content = match.group(1)
            data = json.loads(content.strip())
            return {
                "question": data.get("question", "").strip(),
                "answer": data.get("answer", "").strip(),
            }
        except Exception as e:
            logger.warning(f"生成 QA 失败: {e}")
            return None
