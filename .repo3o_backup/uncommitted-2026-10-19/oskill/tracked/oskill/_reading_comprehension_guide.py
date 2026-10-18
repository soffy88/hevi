"""oskill._reading_comprehension_guide — 阅读理解引导（english/chinese）

职责：引导学生定位原文、提炼答题要素，严禁直接给出题目答案。
苏格拉底红线：
  - 不直接给出题目答案
  - 不整句摘抄关键句（只引导学生自己找）
  - 每次只问一个引导问题
  - 要求学生先"回到原文第X段/第X句"再作答

Added: oskill v3.25.12
"""

from __future__ import annotations
from oprim import llm_complete

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ReadingGuideResult:
    """一次阅读理解引导轮次的输出。

    Attributes
    ----------
    assistant_text : str
        引导问题（不含答案）
    located_passage : bool
        True 表示学生已成功定位关键段落
    answer_leaked : bool
        True 表示检测到可能泄露答案
    """

    assistant_text: str
    located_passage: bool = False
    answer_leaked: bool = False


_READING_SYSTEM_ZH = """你是一位语文老师，正在用苏格拉底法引导学生做阅读理解。

【严格红线】
1. 不直接说出题目答案
2. 不整句摘抄原文关键句作为答案
3. 每次只提一个引导问题
4. 引导学生先定位原文段落，再概括

【正确做法】
- "这道题的答案一定在原文中，你觉得应该去哪个段落找？"
- "你找到这段话了吗？这里作者想表达什么？"
- 确认定位后输出 located_passage=true

输出严格 JSON：
{
  "assistant_text": "（一个引导问题，不含答案）",
  "located_passage": false,
  "answer_leaked": false
}"""

_READING_SYSTEM_EN = """You are an English teacher guiding a student through a reading comprehension exercise using the Socratic method.

【STRICT RED LINES】
1. Never directly state the answer to the question
2. Do not quote the key sentence that IS the answer
3. Ask only ONE guiding question per turn
4. Guide the student to locate the relevant paragraph first

【CORRECT APPROACH】
- "Where in the passage do you think the author discusses this?"
- "Can you find the sentence in paragraph X that relates to this question?"
- Set located_passage=true once student has found the right paragraph

Output strict JSON:
{
  "assistant_text": "(one guiding question, no answer)",
  "located_passage": false,
  "answer_leaked": false
}"""

_OPENING_ZH = "好，我们一起来做这道题。先不要急着答，你觉得这道题在考查什么？"
_OPENING_EN = "Let's work through this together. Before answering, what do you think this question is asking you to find?"


async def reading_comprehension_guide(
    *,
    article_text: str,
    question: str,
    subject: str = "chinese",
    student_messages: list[str] | None = None,
    caller: Any,
    model: str = "claude-sonnet-4-6",
) -> ReadingGuideResult:
    """阅读理解苏格拉底引导。

    Parameters
    ----------
    article_text : str
        阅读材料全文。
    question : str
        题目。
    subject : str
        "chinese" 或 "english"，决定引导语言和系统提示。
    student_messages : list[str] | None
        学生历史消息。None 或空 → 返回开场引导问。
    caller : Any
        LLM 调用者（注入）。
    model : str
        模型标识符。

    Returns
    -------
    ReadingGuideResult
        assistant_text 为下一个引导问题，不含答案。
    """
    import json

    from oprim.llm._llm_complete import llm_complete

    is_english = subject.lower() == "english"
    system_prompt = _READING_SYSTEM_EN if is_english else _READING_SYSTEM_ZH
    opening = _OPENING_EN if is_english else _OPENING_ZH

    if not student_messages:
        return ReadingGuideResult(
            assistant_text=opening,
            located_passage=False,
            answer_leaked=False,
        )

    context = (
        f"【阅读材料】\n{article_text}\n\n【题目】\n{question}"
        if not is_english
        else f"[Passage]\n{article_text}\n\n[Question]\n{question}"
    )

    history: list[dict] = [
        {"role": "user", "content": context},
        {"role": "assistant", "content": opening},
    ]
    for i, msg in enumerate(student_messages):
        history.append({"role": "user", "content": msg})
        if i < len(student_messages) - 1:
            history.append({"role": "assistant", "content": "（引导中）"})

    resp = await llm_complete(
        history,
        caller=caller,
        system=system_prompt,
        model=model,
    )

    raw = resp.text.strip()
    if "```" in raw:
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        fallback = (
            "Can you go back to the passage and find the relevant paragraph?"
            if is_english
            else "你能回到原文，找一找哪个段落和这道题最相关吗？"
        )
        data = {"assistant_text": fallback, "located_passage": False, "answer_leaked": False}

    assistant_text: str = data.get("assistant_text", opening)
    located_passage: bool = bool(data.get("located_passage", False))
    answer_leaked: bool = bool(data.get("answer_leaked", False))

    # 红线二次检测：如果回复包含"答案是/the answer is"等直接给出答案的模式，拦截
    _ZH_LEAK = ["答案是", "答案为", "正确答案", "主旨是", "主旨为", "表达了……"]
    _EN_LEAK = ["the answer is", "the correct answer", "the passage says that", "it means that"]
    leak_patterns = _EN_LEAK if is_english else _ZH_LEAK
    if any(p in assistant_text.lower() for p in [lp.lower() for lp in leak_patterns]):
        answer_leaked = True
        fallback = (
            "Can you find the paragraph in the passage that relates to this question?"
            if is_english
            else "你能先找找原文中和这道题最相关的段落吗？"
        )
        assistant_text = fallback

    return ReadingGuideResult(
        assistant_text=assistant_text,
        located_passage=located_passage,
        answer_leaked=answer_leaked,
    )
