"""中文优化文本分块策略。

核心思路：按段落预分割 → 句子级切分 → 按 token 数合并（不跨句切割）→ 句级重叠。
"""

import re
import logging
from dataclasses import dataclass, field

import tiktoken

from app.config import settings

logger = logging.getLogger(__name__)

# 初始化 tiktoken 编码器（cl100k_base 覆盖中英文）
_enc = tiktoken.get_encoding("cl100k_base")

# 中文句子分割标点（按优先级排列）
_SENTENCE_SEPARATORS = ["\n\n", "\n", "。", "！", "？", "；", "…", ".", "!", "?", ";"]

# 引号内的内容不拆分：匹配中文引号和英文引号包裹的内容
_QUOTE_PATTERN = re.compile(
    r'[""「」『』""][^""「」『』""]*[""「」『』""]'
)


def _count_tokens(text: str) -> int:
    """精确计算 token 数。"""
    return len(_enc.encode(text))


def _split_sentences(text: str) -> list[str]:
    """将文本按中文句末标点切分为句子列表。

    保留引号内的完整内容不被拆分。
    """
    # 先提取引号内容，用占位符替换
    quotes = []
    def _replace_quote(m):
        quotes.append(m.group(0))
        return f"__QUOTE_{len(quotes) - 1}__"

    protected = _QUOTE_PATTERN.sub(_replace_quote, text)

    # 按标点切分
    # 构建正则：从最长的分隔符开始
    pattern = "|".join(re.escape(sep) for sep in _SENTENCE_SEPARATORS if sep != "\n")
    # 对 \n 特殊处理：\n\n 优先级高于 \n
    parts = re.split(r"(\n\n|[" + re.escape("。！？；….!?\n") + r"])", protected)

    # 合并标点回前一个句子
    sentences = []
    current = ""
    for part in parts:
        if re.match(r"^(\n\n|。|！|？|；|…|\.|!|\?|;|\n)$", part):
            current += part
            if current.strip():
                sentences.append(current)
            current = ""
        else:
            current += part
    if current.strip():
        sentences.append(current)

    # 恢复引号内容
    def _restore_quote(s):
        for i, q in enumerate(quotes):
            s = s.replace(f"__QUOTE_{i}__", q)
        return s

    sentences = [_restore_quote(s) for s in sentences]
    return [s for s in sentences if s.strip()]


def _merge_sentences_to_chunks(
    sentences: list[str],
    target_tokens: int,
    max_tokens: int,
) -> list[str]:
    """将句子按 token 数上限合并为 chunk，不跨句切割。"""
    chunks = []
    current_chunk: list[str] = []
    current_tokens = 0

    for sentence in sentences:
        sent_tokens = _count_tokens(sentence)

        # 单句超过 max_tokens：强制独立成 chunk
        if sent_tokens > max_tokens:
            # 先把当前累积的存起来
            if current_chunk:
                chunks.append("".join(current_chunk))
                current_chunk = []
                current_tokens = 0
            chunks.append(sentence)
            continue

        # 加入当前句子后是否超过目标
        if current_tokens + sent_tokens > target_tokens and current_chunk:
            chunks.append("".join(current_chunk))
            current_chunk = [sentence]
            current_tokens = sent_tokens
        else:
            current_chunk.append(sentence)
            current_tokens += sent_tokens

    if current_chunk:
        chunks.append("".join(current_chunk))

    return chunks


def _add_overlap(chunks: list[str], overlap_sentences: int) -> list[str]:
    """在相邻 chunk 之间添加句级重叠。"""
    if overlap_sentences <= 0 or len(chunks) <= 1:
        return chunks

    overlapped = [chunks[0]]
    for i in range(1, len(chunks)):
        # 从前一个 chunk 中提取最后 N 句作为重叠
        prev_sentences = _split_sentences(chunks[i - 1])
        overlap = prev_sentences[-overlap_sentences:] if len(prev_sentences) >= overlap_sentences else prev_sentences
        overlap_text = "".join(overlap)
        overlapped.append(overlap_text + chunks[i])

    return overlapped


@dataclass
class TextChunk:
    """一个文本块。"""
    text: str
    chunk_index: int
    start_char: int = 0
    end_char: int = 0
    page: int = 1


def chunk_text(
    pages: list[dict],
    target_tokens: int | None = None,
    max_tokens: int | None = None,
    overlap_sentences: int | None = None,
) -> list[TextChunk]:
    """对文档的多个页面/段落进行分块。

    Args:
        pages: [{"page": int, "text": str}, ...]
        target_tokens: 目标 chunk token 数
        max_tokens: 最大 token 数
        overlap_sentences: 重叠句数

    Returns:
        TextChunk 列表
    """
    target_tokens = target_tokens or settings.CHUNK_TARGET_TOKENS
    max_tokens = max_tokens or settings.CHUNK_MAX_TOKENS
    overlap_sentences = overlap_sentences or settings.CHUNK_OVERLAP_SENTENCES

    # 将所有页面文本合并后统一处理（按段落自然分隔）
    all_text = ""
    page_map: list[tuple[int, int]] = []  # [(page_num, start_offset), ...]
    for p in pages:
        start = len(all_text)
        all_text += p["text"] + "\n\n"
        page_map.append((p["page"], start))

    # 步骤 1：句子级切分
    sentences = _split_sentences(all_text)
    logger.info(f"切分为 {len(sentences)} 个句子")

    # 步骤 2：按 token 合并为 chunk
    raw_chunks = _merge_sentences_to_chunks(sentences, target_tokens, max_tokens)
    logger.info(f"合并为 {len(raw_chunks)} 个原始 chunk")

    # 步骤 3：添加句级重叠
    final_texts = _add_overlap(raw_chunks, overlap_sentences)
    logger.info(f"重叠处理后 {len(final_texts)} 个 chunk")

    # 步骤 4：构建 TextChunk 并计算 page / offset
    chunks = []
    char_offset = 0
    for i, text in enumerate(final_texts):
        # 找到这个 chunk 在原文中的大致位置
        start_char = all_text.find(text[:min(20, len(text))], max(0, char_offset - 10))
        if start_char == -1:
            start_char = char_offset
        end_char = start_char + len(text)

        # 确定 page
        page_num = 1
        for p_num, p_start in page_map:
            if start_char >= p_start:
                page_num = p_num

        chunks.append(TextChunk(
            text=text.strip(),
            chunk_index=i,
            start_char=start_char,
            end_char=end_char,
            page=page_num,
        ))
        char_offset = end_char

    return chunks
