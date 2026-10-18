"""作文引导 (oskill_essay_guide)

职责：语文作文引导式批改。侧重于发现问题并引导学生自我改进，严禁代写。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class EssayGuideInput:
    title: str
    content: str
    requirements: str = ""  # 写作要求
    conversation_history: list[dict] = field(default_factory=list)


@dataclass(frozen=True)
class EssayGuideResult:
    feedback: dict[str, str]  # 维度 -> 反馈文本
    suggested_questions: list[str]  # 引导学生思考的问题
    is_completed: bool = False


_ESSAY_SYSTEM = (
    "你是一个专业的语文老师。你的任务是对学生的作文进行引导式批改。\n"
    "原则：指出问题，给出改进方向和引导性提问，但绝对不要直接写出优美的句子或整段内容供学生抄袭。\n"
    "维度包括：结构、论证/内容、表达/修辞。\n"
    "输出 JSON：\n"
    "{\n"
    '  "feedback": {"结构": "...", "论证": "...", "表达": "..."},\n'
    '  "suggested_questions": ["你觉得这里如果换一个角度写会怎样？", ...],\n'
    '  "is_completed": false\n'
    "}"
)


async def essay_guide(
    inp: EssayGuideInput, *, caller: Any, model: str = "claude-sonnet-4-6"
) -> EssayGuideResult:
    """作文引导批改。"""
    import json

    from oprim.llm._llm_complete import llm_complete

    user_msg = f"作文题目: {inp.title}\n写作要求: {inp.requirements}\n学生作文正文: {inp.content}\n"

    messages = list(inp.conversation_history)
    messages.append({"role": "user", "content": user_msg})

    response = await llm_complete(messages, caller=caller, system=_ESSAY_SYSTEM, model=model)

    raw = response.text.strip()
    if "```" in raw:
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]

    data = json.loads(raw)
    return EssayGuideResult(
        feedback=data.get("feedback", {}),
        suggested_questions=data.get("suggested_questions", []),
        is_completed=data.get("is_completed", False),
    )


__version__ = "0.1.0"
