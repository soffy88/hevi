"""L4 Editor —— 消费评分卡 → 返工与节奏。

设计 §3 L4:Editor 读裁决结果,决定重拍哪些镜头、什么时候交付。它把这一路的件闭成环:
  - 输入:整片确定性体检 `quality`(§7-4)+ 逐镜头选优明细 `shots`(C3 落库,含
    consistency_score / passed)
  - 输出:`EditDecision`(交付 or 定向返工),`regenerate_shot_ids` + `hints` 直接喂
    `TaskService.regenerate_task_shots`(verdict→返工闭环)。

"guilty until proven innocent":不及格镜头 / 一致性分偏低 → 返工;整片体检不过 → 不交付。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class EditDecision:
    deliver: bool
    regenerate_shot_ids: list[int]
    hints: dict[int, str]
    reasons: list[str] = field(default_factory=list)


def review(
    *,
    quality: dict[str, Any] | None,
    shots: list[dict[str, Any]],
    consistency_floor: float = 0.75,
) -> EditDecision:
    """裁决:哪些镜头返工、能否交付。

    - 镜头 `passed=False` 或 `consistency_score < floor` → 列入 `regenerate_shot_ids` + hints。
    - 整片体检 `quality.passed=False` 或有镜头待返工 → `deliver=False`。
    - 返工完成后由调用方再 review 一轮(loop 收敛)。
    """
    regen: dict[int, str] = {}
    reasons: list[str] = []

    for s in shots:
        idx = s.get("index")
        if idx is None:
            continue
        score = s.get("consistency_score")
        if not s.get("passed", True):
            regen[idx] = "镜头未过一致性校验,重生成"
        elif score is not None and score < consistency_floor:
            regen[idx] = f"一致性分 {score:.2f} < {consistency_floor} 偏低,重生成"

    quality_ok = quality is None or quality.get("passed", True)
    if not quality_ok:
        reasons.append(f"整片体检不过:{quality.get('violations', [])}")
    if regen:
        reasons.append(f"{len(regen)} 个镜头需返工:{sorted(regen)}")

    return EditDecision(
        deliver=quality_ok and not regen,
        regenerate_shot_ids=sorted(regen),
        hints=regen,
        reasons=reasons,
    )
