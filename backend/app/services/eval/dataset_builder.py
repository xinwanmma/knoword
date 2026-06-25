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


class GoldenDatasetBuilder:
    """从 KB 文档 chunks 自动生成 QA 三元组（Question & Answer）。

    默认生成 20 道题（来自 settings.DEFAULT_EVAL_QA_COUNT），可在创建时覆盖。
    """

    DEFAULT_QA_COUNT = 20

    def __init__(self, llm_model: str | None = None):
        # 用 mimo-2.5 生成 QA（轻量即可）
        self._provider = get_llm_provider(llm_model or settings.MIMO_LITE_MODEL)
        self._llm = self._provider.get_chat_model(temperature=0.5)

    async def generate(
        self, kb_id: int, n_questions: int | None = None
    ) -> List[dict]:
        """从 KB 文档 chunks 自动生成 QA 三元组。"""
        n = n_questions or settings.DEFAULT_EVAL_QA_COUNT
        logger.info(f"为 KB {kb_id} 生成 {n} 道 QA")

        # 1. 取 KB 所有 chunks
        chunks = self._get_kb_chunks(kb_id)
        if not chunks:
            return []

        # 2. 随机采样
        sampled = random.sample(chunks, min(n, len(chunks)))

        # 3. 并发生成 QA
        sem = asyncio.Semaphore(4)

        async def gen_one(chunk: dict) -> dict | None:
            async with sem:
                return await self._generate_qa_for_chunk(chunk)

        results = await asyncio.gather(
            *[gen_one(c) for c in sampled], return_exceptions=True
        )

        # 4. 过滤异常
        qa_pairs = []
        for chunk, r in zip(sampled, results):
            if isinstance(r, Exception):
                logger.warning(f"生成 QA 失败: {r}")
                continue
            if not r:
                continue
            qa_pairs.append({
                "question": r["question"],
                "ground_truth": r["answer"],
                "source_chunk_ids": [chunk["chunk_id"]],
                "source_doc_ids": [chunk["doc_id"]],
            })

        logger.info(f"成功生成 {len(qa_pairs)} 道 QA")
        return qa_pairs

    def _get_kb_chunks(self, kb_id: int) -> list[dict]:
        """从 ChromaDB 读取 KB 的所有 chunk。"""
        try:
            collection = get_collection()
            data = collection.get(where={"kb_id": kb_id}, limit=1000)
            if not data.get("documents"):
                return []
            chunks = []
            for i, (doc, meta) in enumerate(zip(data["documents"], data["metadatas"])):
                chunks.append({
                    "chunk_id": meta.get("chunk_id") or meta.get("id", str(i)),
                    "doc_id": meta.get("doc_id", 0),
                    "content": doc,
                })
            return chunks
        except Exception as e:
            logger.error(f"读取 KB chunks 失败: {e}")
            return []

    async def _generate_qa_for_chunk(self, chunk: dict) -> dict | None:
        """为单个 chunk 生成一个 QA。"""
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
