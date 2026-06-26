"""LLM 评估 prompt 模板。

3 个指标：
1. STATEMENT_EXTRACTION — 拆解 answer 为 atomic statements
2. FAITHFULNESS_VERDICT — 判断 statement 是否 grounded in context
3. ANSWER_RELEVANCY — 判断 answer 跟 question 的相关性

所有 prompt 要求模型**只输出 JSON**，便于 LangChain OutputParser 解析。
"""
from langchain_core.prompts import ChatPromptTemplate


# ===== 1. Faithfulness: 拆 statements =====

STATEMENT_EXTRACTION_PROMPT = ChatPromptTemplate.from_messages([
    ('system', (
        '你是一个严谨的语义分析助手。'
        '请把给定的【答案】拆解为若干个『原子陈述』（atomic statements）。'
        '每个 statement 必须是：\n'
        '1. 一个独立的事实声明\n'
        '2. 不含『和』/『以及』等连接词\n'
        '3. 可以独立判断真假\n\n'
        '【输出格式】只输出 JSON 数组，不要其他文字：\n'
        '{{"statements": ["statement1", "statement2", ...]}}'
    )),
    ('user', '【答案】\n{answer}'),
])


# ===== 2. Faithfulness: verdict 验证 =====

FAITHFULNESS_VERDICT_PROMPT = ChatPromptTemplate.from_messages([
    ('system', (
        '你是一个严格的答案忠实度评判助手。'
        '你的任务：判断给定的【陈述】是否能从【参考资料】中推出/支持。\n\n'
        '判断标准：\n'
        '- verdict = 1：陈述中的事实/信息在参考资料中能找到对应（supported）\n'
        '- verdict = 0：陈述中包含参考资料中找不到的信息（hallucinated，'
        '即使是常识但参考资料没提也算 0）\n\n'
        '【输出格式】只输出严格 JSON（不要任何额外文字、不要 markdown fence）：\n'
        '一个 JSON object，key 为 verdict（数字 0 或 1）和 reason（字符串）。\n\n'
        '示例：\n'
        '- 陈述『巴黎是法国首都』+ 参考资料『巴黎是法国首都』 → verdict=1\n'
        '- 陈述『巴黎人口 5000 万』+ 参考资料『巴黎是法国首都』 → verdict=0\n'
        '- 陈述『巴黎位于欧洲』+ 参考资料『巴黎是法国首都，法国在欧洲』 → verdict=1'
    )),
    ('user', (
        '【陈述】\n{statement}\n\n'
        '【参考资料】\n{contexts}\n'
    )),
])


# ===== 3. Answer Relevancy =====

ANSWER_RELEVANCY_PROMPT = ChatPromptTemplate.from_messages([
    ('system', (
        '你是一个严格的答案相关性评判助手。'
        '你的任务：判断给定的【答案】是否直接回答了【问题】。\n\n'
        '判断标准：\n'
        '- score = 1.0：答案直接回答了问题（即使答错也算相关——相关性和正确性分开评）\n'
        '- score = 0.5：答案部分相关（提到了问题相关领域但没直接答）\n'
        '- score = 0.0：答案完全不相关（答非所问）\n\n'
        '注意：\n'
        '- 如果答案是『我不知道』/『无法回答』，score=0.5（表态了但没回答）\n'
        '- 如果答案答的是另一个问题，score=0.0\n'
        '- 不要因为答案『不完整』或『事实错误』而扣分（那是 faithfulness/correctness 评的）\n\n'
        '【输出格式】只输出严格 JSON（不要任何额外文字、不要 markdown fence）：\n'
        '一个 JSON object，key 为 score（数字 0.0 / 0.5 / 1.0）和 reason（字符串）。'
    )),
    ('user', (
        '【问题】\n{question}\n\n'
        '【答案】\n{answer}\n'
    )),
])
