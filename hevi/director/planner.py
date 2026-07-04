"""L4 端到端规划 —— 输入剧情文本 → 可执行分镜图(北极星"输入剧情,输出第 N 集"的输入端)。

串起最后两层 LLM 外壳 + 三角:
  文本 → parse_intent(NL 解析)→ produce(可行性)→ plan_shots(自动分镜)→
  build_canvas_graph(可执行 canvas 图)。

产出既是**人在环**的可编辑分镜图(用户改图再执行),也可直接交 canvas executor 全自动跑。
"""

from __future__ import annotations

from typing import Any

from hevi.director.director import build_canvas_graph
from hevi.director.intent import parse_intent
from hevi.director.producer import produce
from hevi.director.storyboard import plan_shots


async def plan_from_text(
    *,
    text: str,
    num_shots: int = 4,
    llm: Any = None,
    character_reference: str | None = None,
) -> dict[str, Any]:
    """剧情文本 → {intent, plan, shot_prompts, graph}。graph 可编辑/可执行。"""
    intent = await parse_intent(text, llm=llm)
    plan = await produce(**intent)
    shot_prompts = await plan_shots(
        topic=intent["topic"], num_shots=num_shots, style=intent["style"], llm=llm
    )
    graph = build_canvas_graph(
        plan=plan, shot_prompts=shot_prompts, character_reference=character_reference
    )
    return {"intent": intent, "plan": plan, "shot_prompts": shot_prompts, "graph": graph}
