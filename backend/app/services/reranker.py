"""Reranking — 交叉编码器重排序，提升检索精准度。

核心思路：
- 第一轮检索（BM25 + 向量）返回 top_k 个候选
- Reranking 用交叉编码器精确计算 query-document 相关度
- 按新分数重排序，取 top_n 返回

注意：交叉编码器需要额外的模型依赖。
当前实现使用简单的 LLM 评分作为替代方案（不需要额外模型）。
如果需要真正的交叉编码器，安装 sentence-transformers：
    pip install sentence-transformers
"""

import logging
from dataclasses import dataclass

from app.config import settings

logger = logging.getLogger(__name__)


async def rerank_with_llm(
    query: str,
    documents: list[dict],
    top_n: int = 3,
) -> list[dict]:
    """用 LLM 对候选文档重新评分排序。

    比交叉编码器慢，但不需要额外模型依赖。

    Args:
        query: 用户查询
        documents: 候选文档列表 [{"text": "...", "metadata": {...}, "score": 0.8}, ...]
        top_n: 返回前 N 个

    Returns:
        重排序后的文档列表
    """
    if len(documents) <= top_n:
        return documents

    from app.core.llm import get_llm_for_supervisor

    llm = get_llm_for_supervisor()

    # 构建评分 prompt
    docs_text = ""
    for i, doc in enumerate(documents):
        text = doc.get("text", doc.get("document", ""))[:200]
        docs_text += f"[文档{i+1}] {text}\n\n"

    prompt = f"""请为以下每个文档与查询的相关性评分（0-10分，10分最相关）。

查询：{query}

{docs_text}
请以 JSON 数组格式返回每个文档的分数，例如：[8, 3, 6, 1, 9]
只返回 JSON 数组，不要其他文字。"""

    try:
        from langchain_core.messages import HumanMessage
        response = await llm.ainvoke([HumanMessage(content=prompt)])
        content = response.content.strip()

        # 解析分数
        import json
        if content.startswith("```"):
            content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        if content.startswith("["):
            scores = json.loads(content)
            # 确保分数数量匹配
            while len(scores) < len(documents):
                scores.append(0)

            # 按分数重排序
            ranked = sorted(
                enumerate(documents),
                key=lambda x: scores[x[0]],
                reverse=True,
            )

            result = []
            for idx, doc in ranked[:top_n]:
                doc["rerank_score"] = scores[idx]
                result.append(doc)

            logger.info(f"Reranking 完成: {len(documents)} → {len(result)} (LLM 评分)")
            return result

    except Exception as e:
        logger.warning(f"LLM Reranking 失败，回退到原始排序: {e}")

    # 回退：返回原始排序的 top_n
    return documents[:top_n]


async def rerank_with_score_fusion(
    query: str,
    documents: list[dict],
    top_n: int = 3,
    original_weight: float = 0.5,
    keyword_weight: float = 0.5,
) -> list[dict]:
    """基于关键词匹配的快速重排序（不需要 LLM）。

    Args:
        query: 用户查询
        documents: 候选文档
        top_n: 返回前 N 个
        original_weight: 原始分数权重
        keyword_weight: 关键词匹配分数权重

    Returns:
        重排序后的文档
    """
    import re
    from collections import Counter

    # 查询关键词
    query_chars = set(re.findall(r'[\u4e00-\u9fff]+', query))
    query_words = set(re.findall(r'\w+', query))
    query_terms = query_chars | query_words

    results = []
    for doc in documents:
        text = doc.get("text", doc.get("document", ""))
        original_score = doc.get("score", doc.get("rerank_score", 0.5))

        # 关键词匹配分数
        text_chars = set(re.findall(r'[\u4e00-\u9fff]+', text))
        text_words = set(re.findall(r'\w+', text))
        text_terms = text_chars | text_words

        overlap = len(query_terms & text_terms)
        keyword_score = min(overlap / max(len(query_terms), 1), 1.0)

        # 融合分数
        fused = original_weight * original_score + keyword_weight * keyword_score
        doc["rerank_score"] = round(fused, 4)
        results.append(doc)

    # 排序
    results.sort(key=lambda x: x["rerank_score"], reverse=True)
    return results[:top_n]
