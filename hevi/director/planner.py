"""L4 端到端规划 —— 输入剧情文本 → 可执行分镜图(北极星"输入剧情,输出第 N 集"的输入端)。

串起最后两层 LLM 外壳 + 三角:
  文本 → parse_intent(NL 解析)→ produce(可行性)→ plan_shots(自动分镜)→
  build_canvas_graph(可执行 canvas 图)。

产出既是**人在环**的可编辑分镜图(用户改图再执行),也可直接交 canvas executor 全自动跑。

创意工具动态编排(HEVI 路线图 Phase4 #45):9 项创意辅助工具本身零新增开发,这里
只加"决策权从用户菜单转给 Director"这一步——推荐(+ three-view 情形下真的调用)
是 best-effort 附加信息,失败不影响主流程,不给 assist_service 也完全照旧工作。
"""

from __future__ import annotations

from typing import Any

from hevi.director.creative_orchestration import (
    apply_three_view_if_recommended,
    recommend_creative_tools,
)
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
    assist_service: Any = None,
) -> dict[str, Any]:
    """剧情文本 → {intent, plan, shot_prompts, graph, creative_tool_recommendations,
    three_view}。graph 可编辑/可执行。"""
    intent = await parse_intent(text, llm=llm)
    plan = await produce(**intent)
    shot_prompts = await plan_shots(
        topic=intent["topic"], num_shots=num_shots, style=intent["style"], llm=llm
    )
    graph = build_canvas_graph(
        plan=plan, shot_prompts=shot_prompts, character_reference=character_reference
    )
    recommendations = await recommend_creative_tools(intent["topic"], llm=llm)
    three_view = await apply_three_view_if_recommended(
        recommendations,
        topic=intent["topic"],
        style=intent["style"],
        assist_service=assist_service,
    )
    return {
        "intent": intent,
        "plan": plan,
        "shot_prompts": shot_prompts,
        "graph": graph,
        "creative_tool_recommendations": recommendations,
        "three_view": three_view,
    }
