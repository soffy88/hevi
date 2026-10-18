"""元认知支架 (oskill_metacog_scaffold)

职责：在进入苏格拉底引导前，引导学生自评“哪里不懂”，对抗元认知懒惰。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MetacogScaffoldInput:
    """元认知自评输入。"""

    question: str
    student_id: str
    input_content: str  # OCR/STT/文字输入内容


@dataclass(frozen=True)
class MetacogScaffoldResult:
    """自评结果。"""

    self_eval: dict[str, Any]
    starter_prompt: str  # 作为后续引导的起点上下文


_METACOG_PROMPT = (
    "你是一个引导员。根据学生的题目和输入，生成一个简单的元认知自评问题。\n"
    "选项应包含：'概念不清楚', '题目看不懂', '公式记不住', '知道思路但算不下去'。\n"
    '输出 JSON：{"question": "...", "options": [...]}'
)


async def metacog_scaffold(
    inp: MetacogScaffoldInput, *, caller: Any, model: str = "claude-sonnet-4-6"
) -> MetacogScaffoldResult:
    """生成或处理元认知自评。"""
    import json

    from oprim.llm._llm_complete import llm_complete

    # 实际场景中，这可能是分两步：1. 展示问题，2. 收集结果。
    # 作为一个 oskill，这里提供生成自评结构的能力。
    user_msg = f"题目: {inp.question}\n学生输入: {inp.input_content}"

    response = await llm_complete(
        [{"role": "user", "content": user_msg}], caller=caller, system=_METACOG_PROMPT, model=model
    )

    raw = response.text.strip()
    if "```" in raw:
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]

    data = json.loads(raw)

    # 模拟生成的自评（如果是实时交互，这部分逻辑会被拆分）
    # 这里直接返回结构
    return MetacogScaffoldResult(
        self_eval=data,
        starter_prompt=f"学生自评为: {data.get('question')} -> {data.get('options')}",
    )


__version__ = "0.1.0"
