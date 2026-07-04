"""L4 全自动导演回路 —— 把 Producer / 管线 / Editor / 返工串成一个可运行 agent。

设计 §3 L4"全自动模式":
  Producer(可行性)→ 跑管线出片 → Editor(体检+评分卡评审)→ 不及格则**定向返工**
  (regenerate_task_shots)→ 再评审,循环到交付或封顶(rework 上限)。

依赖 `TaskService`(鸭子类型:需 `run_task` / `regenerate_task_shots` / `repository.get_task`
/ `repository.get_shots`)。管线本身跑在 L0-L3 已接的件上,这里只做导演编排(不新建管线)。
自然语言意图 → produce() 字段的解析仍是更上层薄 LLM 层,后续增量。
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from hevi.director.editor import EditDecision, review
from hevi.director.producer import ProducerPlan, produce

logger = logging.getLogger(__name__)


@dataclass
class DirectorResult:
    delivered: bool
    plan: ProducerPlan
    rework_rounds: int
    reason: str
    final_decision: EditDecision | None = None
    trail: list[str] = field(default_factory=list)


def _shot_view(row: dict[str, Any]) -> dict[str, Any]:
    """DB shot_states 行 → Editor 视图(index/passed/consistency_score)。"""
    sel = row.get("selection_json") or {}
    return {
        "index": row.get("shot_index"),
        "passed": sel.get("passed", True),
        "consistency_score": sel.get("consistency_score"),
    }


async def run_director_loop(
    *,
    task_id: uuid.UUID,
    task_service: Any,
    intent: dict[str, Any],
    max_rework_rounds: int = 2,
    consistency_floor: float = 0.75,
) -> DirectorResult:
    """对已建 task 跑全自动导演回路。intent 传给 Producer(topic/duration_archetype/budget…)。"""
    trail: list[str] = []

    # 1) Producer:可行性 —— 不可行(预算不够等)直接止损,不烧算力。
    plan = await produce(**intent)
    trail.append(
        f"producer: provider={plan.video_provider} est=${plan.estimated_usd:.2f} feasible={plan.feasible}"
    )
    if not plan.feasible:
        return DirectorResult(
            delivered=False,
            plan=plan,
            rework_rounds=0,
            reason="infeasible: " + "; ".join(plan.notes),
            trail=trail,
        )

    # 2) 首次出片
    await task_service.run_task(task_id)
    task = await task_service.repository.get_task(task_id)
    quality = (task.get("config_json") or {}).get("quality")
    shots = [_shot_view(r) for r in await task_service.repository.get_shots(task_id)]
    decision = review(quality=quality, shots=shots, consistency_floor=consistency_floor)
    trail.append(f"round0: deliver={decision.deliver} regen={decision.regenerate_shot_ids}")

    # 3) Editor→返工循环:不及格且有可返工镜头 → 定向重烧 → 再评审。
    rounds = 0
    while not decision.deliver and decision.regenerate_shot_ids and rounds < max_rework_rounds:
        regen = await task_service.regenerate_task_shots(
            task_id, shot_ids=decision.regenerate_shot_ids, hints=decision.hints
        )
        rounds += 1
        # regenerate 直接返回 Editor 格式的 shots;quality 沿用首轮(返工不重跑整片体检)。
        shots = regen.get("shots") or [
            _shot_view(r) for r in await task_service.repository.get_shots(task_id)
        ]
        decision = review(quality=quality, shots=shots, consistency_floor=consistency_floor)
        trail.append(
            f"round{rounds}: deliver={decision.deliver} regen={decision.regenerate_shot_ids}"
        )

    reason = "delivered" if decision.deliver else f"stopped after {rounds} rework round(s)"
    logger.info("director loop %s: %s", task_id, reason)
    return DirectorResult(
        delivered=decision.deliver,
        plan=plan,
        rework_rounds=rounds,
        reason=reason,
        final_decision=decision,
        trail=trail,
    )
