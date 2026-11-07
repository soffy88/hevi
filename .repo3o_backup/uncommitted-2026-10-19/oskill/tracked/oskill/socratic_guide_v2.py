"""苏格拉底引导 v2 (oskill_socratic_guide_v2)

职责：苏格拉底引导 + 动态放弃阈值。覆盖并取代 socratic_loop。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from oprim.socratic_turn import SocraticTurnInput, socratic_turn


@dataclass
class SocraticStateV2:
    question: str
    correct_answer: str
    messages: list[dict] = field(default_factory=list)
    turn_count: int = 0
    stuck_count: int = 0  # 连续卡在同一步的计数
    last_step_id: str | None = None
    hint_level: int = 1
    max_stuck_threshold: int = 3  # 默认连续 3 轮卡住则降级


@dataclass(frozen=True)
class SocraticGuideV2Output:
    assistant_text: str
    hint_level: int
    turn_number: int
    decision_trail: dict  # 记录当前决策逻辑


async def socratic_guide_v2(
    state: SocraticStateV2,
    student_message: str,
    *,
    caller: Any,
    kc_ids: list[str] | None = None,
    model: str = "claude-sonnet-4-6",
    current_step_id: str | None = None,  # 前端或校验层识别的当前步骤标识
) -> SocraticGuideV2Output:
    """处理一轮引导。"""

    # 逻辑 1：检测是否卡在同一步
    if current_step_id and current_step_id == state.last_step_id:
        state.stuck_count += 1
    else:
        state.stuck_count = 0
        state.last_step_id = current_step_id

    # 逻辑 2：动态调整提示粒度 (hint_level)
    # hint_level: 1 (温和) -> 2 (结构性) -> 3 (明确提示)
    if state.stuck_count >= state.max_stuck_threshold:
        if state.hint_level < 3:
            state.hint_level += 1
            state.stuck_count = 0  # 提升粒度后重置计数

    # 逻辑 3：调用原子原子能力
    inp = SocraticTurnInput(
        question=state.question,
        correct_answer=state.correct_answer,
        student_last_message=student_message,
        conversation_history=state.messages,
        kc_ids=kc_ids or [],
        hint_level=state.hint_level,
    )

    result = await socratic_turn(inp, caller=caller, model=model)
    text = result.text

    # 逻辑 4：护栏红线（防止答案泄露，复用旧逻辑）
    if state.correct_answer.strip() and state.correct_answer in text:
        text = "这一步我们可以再推导一下，你觉得应该用哪个公式？"

    state.messages.append({"role": "user", "content": student_message})
    state.messages.append({"role": "assistant", "content": text})
    state.turn_count += 1

    decision_trail = {
        "turn": state.turn_count,
        "stuck_count": state.stuck_count,
        "hint_level": state.hint_level,
        "step_id": state.last_step_id,
    }

    return SocraticGuideV2Output(
        assistant_text=text,
        hint_level=state.hint_level,
        turn_number=state.turn_count,
        decision_trail=decision_trail,
    )


__version__ = "0.2.0"
