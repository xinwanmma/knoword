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
# 候选 = target 1 个 + embedding 召回 20 个，下标 [0..20]
COMBINED_QA_PROMPT = """你是问答数据集生成专家。请基于以下 21 个文档片段（[0] 是最相关的 target，其余 20 个是按相似度排序的候选），生成一个有意义的问题和答案，并标出"回答这个问题实际用到了哪几个片段"。

【文档片段】
{target_block}

{candidate_blocks}

要求：
1. 基于 [0] target 片段（最相关）生成 QA
2. 答案要忠实于片段内容，简短、客观（1-3 句话）
3. 关键：标出 used_chunks（回答这个问题真正用到的片段下标列表，按相关性从高到低排序），如 [0, 2, 5]
4. 通常 1-5 个就够，没把握宁可少选
5. 问题不要太简单（避免"是什么"类问题），优先问"为什么/怎么/区别/包含哪些"类

请严格输出 JSON（不要任何额外说明）：
{{"question": "...", "answer": "...", "used_chunks": [0, 2, 5]}}"""


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
            embedding_model = kb.embedding_model or "qwen3-embedding:0.6b"
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
        _wlog(f"开始并发生成（concurrency=4）...")

        # 4. 并发生成 QA（每个 target 1 次 LLM 调用）
        sem = asyncio.Semaphore(4)

        async def gen_one(target: dict, idx: int) -> dict | None:
            async with sem:
                try:
                    result = await self._generate_qa_with_selection(
                        target, chunks, chunk_embs, embedding_model
                    )
                    if result is None:
                        _wlog(f"target[{idx}] chunk_id={target['chunk_id']} → None（LLM 失败/解析失败）", "WARN")
                    else:
                        _wlog(
                            f"target[{idx}] chunk_id={target['chunk_id']} → OK "
                            f"(used {len(result['source_chunk_ids'])} chunks)"
                        )
                        _wlog(f"  Q: {result['question']}")
                        _wlog(f"  A: {result['ground_truth']}")
                        _wlog(f"  source_chunk_ids: {result['source_chunk_ids']}")
                    return result
                except Exception as e:
                    _wlog(f"target[{idx}] chunk_id={target['chunk_id']} → EXCEPTION: {e}", "ERROR")
                    _wlog(traceback.format_exc(), "ERROR")
                    return None

        results = await asyncio.gather(
            *[gen_one(c, i) for i, c in enumerate(sampled)], return_exceptions=True
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

        # 6. 写汇总
        fail_count = len(sampled) - len(qa_pairs)
        _wlog(f"=== 生成完成 ===")
        _wlog(f"成功: {len(qa_pairs)}/{len(sampled)}（失败 {fail_count} 个）")
        if qa_pairs:
            avg_gt = sum(len(q["source_chunk_ids"]) for q in qa_pairs) / len(qa_pairs)
            _wlog(f"平均 ground truth chunks: {avg_gt:.1f}")
            from collections import Counter
            dist = Counter(len(q["source_chunk_ids"]) for q in qa_pairs)
            _wlog(f"chunk_ids 长度分布: {dict(sorted(dist.items()))}")
        _wlog(f"详细日志: {log_path}")
        logger.info(f"dataset generate log: {log_path}")
        return qa_pairs

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
    ) -> dict | None:
        """合并版两阶段：1 次 LLM 调用同时生成 QA + 选 chunks。

        流程：
        1. 用 target content 召回 top-20 候选（跨距离）
        2. 把 target + 20 候选 = 21 个 chunks 喂给 LLM
        3. LLM 返回 {question, answer, used_chunks: [0, 2, 5]}
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

            # 1. embedding 召回 top-20（按相似度，不含 target 自身）
            embedder = get_embedding_provider(embedding_model)
            target_emb = await embedder.embed_query(target["content"][:1000])

            sims = []
            for i, (c, ce) in enumerate(zip(all_chunks, chunk_embs)):
                if c["chunk_id"] == target["chunk_id"]:
                    continue
                sims.append((_cos_sim(target_emb, ce), i))
            sims.sort(reverse=True)
            candidate_indices = [i for _, i in sims[:SELECTION_CANDIDATES]]
            candidates = [all_chunks[i] for i in candidate_indices]

            # 2. 构造 candidates 列表（target 排 [0]）
            ordered = [target] + candidates  # [0]=target, [1..20]=candidates

            # 3. 合并 prompt：1 次 LLM 调用
            prompt = self._build_combined_prompt(ordered)

            # 4. LLM 调用
            response = await self._llm.ainvoke([{"role": "user", "content": prompt}])
            content = response.content if hasattr(response, "content") else str(response)
            data = self._parse_combined_json(content)
            if not data:
                return None

            # 5. used_chunks 映射回 chunk_ids
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
            }
        except Exception as e:
            logger.exception(f"合并版生成失败: {e}")
            return None

    def _build_combined_prompt(self, ordered: list[dict]) -> str:
        """构建"生成 QA + 选 chunks"合并 prompt。

        ordered[0] = target（最相关），[1..N] = embedding 召回的候选
        """
        target_block = f"[0] (target, 最相关)\n{ordered[0]['content'][:800]}"
        cand_blocks = []
        for i, c in enumerate(ordered[1:], 1):
            cand_blocks.append(f"[{i}] (相似)\n{c['content'][:500]}")
        return COMBINED_QA_PROMPT.format(
            target_block=target_block,
            candidate_blocks="\n\n".join(cand_blocks),
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
