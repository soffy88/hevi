"""oskill._physics_force_analysis_guide — 物理受力分析苏格拉底引导

职责：通过引导式提问帮学生完成受力分析，严禁直接给出受力图描述或完整方程。
苏格拉底红线：
  - 每次只问一个引导问题
  - 不输出受力图描述（箭头方向/大小）
  - 不输出列好的完整方程
  - 答错则追问，不纠正
  - equation_ready=True 时才说明可以列方程了

Added: oskill v3.25.12
"""

from __future__ import annotations
from oprim import llm_complete

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ForceAnalysisResult:
    """一次受力分析引导轮次的输出。

    Attributes
    ----------
    assistant_text : str
        引导问题（Socratic，不含答案）
    equation_ready : bool
        True 表示学生已完成受力分析，可以进入列方程阶段
    answer_leaked : bool
        True 表示检测到可能泄露答案（触发红线保护）
    """

    assistant_text: str
    equation_ready: bool = False
    answer_leaked: bool = False


_FORCE_SYSTEM = """你是一位高中物理老师，正在用苏格拉底引导法帮学生完成受力分析。

【严格红线——以下任何一条都不能做】
1. 不直接描述物体受哪些力及方向（如"受到向下的重力、向上的支持力"）
2. 不直接给出受力图的箭头描述
3. 不给出完整的方程组（如 F_N - mg = 0）
4. 不给出最终答案
5. 每次只提一个引导问题

【正确做法】
- 引导学生自己分析：先问受什么力的种类，再问方向，再问大小关系
- 确认分析完整后，输出 equation_ready=true
- 若学生分析有误，用"你有没有想过……"引导，不直接纠正

输出严格 JSON：
{
  "assistant_text": "（一个引导问题或确认语，不含答案）",
  "equation_ready": false,
  "answer_leaked": false
}"""


_OPENING_QUESTION = (
    "好的，我们一起来分析这道题。首先，这个物体处于什么运动状态？（静止、匀速、加速？）"
)


async def physics_force_analysis_guide(
    *,
    question_text: str,
    student_messages: list[str] | None = None,
    caller: Any,
    model: str = "claude-sonnet-4-6",
) -> ForceAnalysisResult:
    """物理受力分析苏格拉底引导。

    Parameters
    ----------
    question_text : str
        物理题目原文。
    student_messages : list[str] | None
        学生的历史消息列表。None 或空列表 → 返回开场引导问。
    caller : Any
        LLM 调用者（注入）。
    model : str
        模型标识符。

    Returns
    -------
    ForceAnalysisResult
        assistant_text 为下一个引导问题，不含答案。
    """
    import json

    from oprim.llm._llm_complete import llm_complete

    if not student_messages:
        return ForceAnalysisResult(
            assistant_text=_OPENING_QUESTION,
            equation_ready=False,
            answer_leaked=False,
        )

    history: list[dict] = [
        {"role": "user", "content": f"题目：{question_text}"},
        {"role": "assistant", "content": _OPENING_QUESTION},
    ]
    for i, msg in enumerate(student_messages):
        history.append({"role": "user", "content": msg})
        if i < len(student_messages) - 1:
            history.append({"role": "assistant", "content": "（引导中）"})

    resp = await llm_complete(
        history,
        caller=caller,
        system=_FORCE_SYSTEM,
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
        data = {
            "assistant_text": "你认为这个物体受到哪几类力的作用？",
            "equation_ready": False,
            "answer_leaked": False,
        }

    assistant_text: str = data.get("assistant_text", "请继续分析受力情况。")
    equation_ready: bool = bool(data.get("equation_ready", False))
    answer_leaked: bool = bool(data.get("answer_leaked", False))

    # 红线二次检测：如果回复包含完整方程特征，标记 answer_leaked
    _LEAK_PATTERNS = ["=", "N·m", "N/m", "牛顿第", "F_N", "mg =", "合力为", "受力图为"]
    if sum(p in assistant_text for p in _LEAK_PATTERNS) >= 2:
        answer_leaked = True
        assistant_text = "你觉得这个物体首先受到哪一类力？（接触力还是非接触力？）"

    return ForceAnalysisResult(
        assistant_text=assistant_text,
        equation_ready=equation_ready,
        answer_leaked=answer_leaked,
    )
