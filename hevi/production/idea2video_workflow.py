"""omodul.idea2video_workflow — 点子→故事/角色/分场→每场内核规划。

3O 归属(待上游): `omodul.idea2video_workflow`。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hevi.script2video.omodul.idea_plan import plan_idea2video

logger = logging.getLogger(__name__)


@dataclass
class Idea2VideoConfig:
    style: str = "cinematic"


@dataclass
class Idea2VideoInput:
    idea: str
    requirement: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


async def idea2video_workflow(
    config: Idea2VideoConfig,
    input_data: Idea2VideoInput,
    output_dir: Path,
    *,
    on_step: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    _enabled_pillars = {"report", "cost", "decision_trail"}
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    decision_trail: list[dict[str, Any]] = []

    def _step(stage: str, pct: float) -> None:
        if on_step is not None:
            on_step({"stage": stage, "pct": pct})

    try:
        if not (input_data.idea or "").strip():
            return {"status": "failed", "error": "idea2video_workflow: empty idea"}
        _step("plan", 20.0)
        plan = plan_idea2video(input_data.idea, input_data.requirement, config.style)
        decision_trail.append(
            {
                "stage": "plan",
                "scenes": len(plan.scenes),
                "characters": len(plan.characters),
                "pillars": sorted(_enabled_pillars),
            }
        )
        report_path = output_dir / "idea2video_report.json"
        report_path.write_text(
            json.dumps(
                {
                    "pillars": sorted(_enabled_pillars),
                    "status": "completed",
                    "style": config.style,
                    "plan": plan.to_dict(),
                    "decision_trail": decision_trail,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        _step("completed", 100.0)
        return {
            "status": "completed",
            "report_path": str(report_path),
            "decision_trail": decision_trail,
            "scene_count": len(plan.scenes),
        }
    except Exception as exc:
        logger.exception("idea2video_workflow failed")
        return {
            "status": "failed",
            "error": str(exc),
            "report_path": str(output_dir / "idea2video_report.json"),
        }
