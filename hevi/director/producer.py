"""L4 Producer —— 意图 → 约束 + 预算可行性。

设计 §3 L4:Producer 把"想拍什么"变成"能不能拍、用什么拍、多少钱"。跑在已有件上,不新建管线:
  - 成本感知路由(`cost.router.route_video_provider`,§7-2)—— 选 provider
  - `cost.estimate_cost` —— 估价
  - 预算门 —— 估价 vs budget

输出 `ProducerPlan`(下发给 Director 建图 / 直接跑管线的约束)。
NL 意图解析(自然语言 → 这些字段)是更上层的薄 LLM 层——已实现,见
`hevi.director.intent.parse_intent`(text → intent dict)+
`hevi.director.planner.plan_from_text`(串起 parse_intent → produce → plan_shots →
build_canvas_graph 的完整"输入剧情文本 → 可执行分镜图"链路,HEVI 路线图 Phase3 #43
核实后确认此前的"后续增量"说法已过时)。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from hevi.cost.estimator import estimate_cost


@dataclass
class ProducerPlan:
    topic: str
    duration_archetype: str
    video_provider: str
    audio_provider: str
    style: str
    num_characters: int
    estimated_usd: float
    budget_usd: float | None
    budget_ok: bool
    feasible: bool
    notes: list[str] = field(default_factory=list)


async def produce(
    *,
    topic: str,
    duration_archetype: str,
    audio_provider: str = "vibevoice",
    video_provider: str = "auto",
    style: str = "cinematic",
    num_characters: int = 1,
    budget_usd: float | None = None,
    mode: str = "t2v",
) -> ProducerPlan:
    """意图 → ProducerPlan(约束 + 可行性)。

    `video_provider="auto"` → 成本感知路由(能力×活状态×最便宜);失败回退 wan_local。
    `feasible` = 预算够(provider 能力已由路由保证)。
    """
    notes: list[str] = []

    if video_provider == "auto":
        try:
            from hevi.cost.router import route_video_provider

            video_provider = await route_video_provider(
                duration_archetype=duration_archetype,
                audio_provider=audio_provider,
                mode=mode,
            )
            notes.append(f"auto-routed → {video_provider}")
        except Exception as e:
            video_provider = "wan_local"
            notes.append(f"路由失败,回退 wan_local: {e}")

    est = await estimate_cost(
        duration_archetype=duration_archetype,
        video_provider=video_provider,
        audio_provider=audio_provider,
        num_characters=num_characters,
    )
    budget_ok = budget_usd is None or est.total_usd <= budget_usd
    if not budget_ok:
        notes.append(f"预算不足:估 ${est.total_usd:.2f} > 上限 ${budget_usd:.2f}")

    return ProducerPlan(
        topic=topic,
        duration_archetype=duration_archetype,
        video_provider=video_provider,
        audio_provider=audio_provider,
        style=style,
        num_characters=num_characters,
        estimated_usd=est.total_usd,
        budget_usd=budget_usd,
        budget_ok=budget_ok,
        feasible=budget_ok,
        notes=notes,
    )
