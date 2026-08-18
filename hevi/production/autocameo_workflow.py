"""omodul.autocameo_workflow — 照片锁身份并入角色表。

3O 归属(待上游): `omodul.autocameo_workflow`。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hevi.script2video.omodul.cameo_plan import plan_autocameo

logger = logging.getLogger(__name__)


@dataclass
class AutoCameoConfig:
    style: str = "cinematic"
    max_characters: int = 4


@dataclass
class AutoCameoInput:
    photos: list[str]
    story_context: str = ""
    image_gen: Any = None
    extra: dict[str, Any] = field(default_factory=dict)


async def autocameo_workflow(
    config: AutoCameoConfig,
    input_data: AutoCameoInput,
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
        if not input_data.photos:
            return {"status": "failed", "error": "autocameo_workflow: no photos"}
        _step("cameo", 30.0)
        plan = await plan_autocameo(
            [Path(path) for path in input_data.photos],
            story_context=input_data.story_context,
            max_characters=config.max_characters,
            image_gen=input_data.image_gen,
            output_dir=output_dir / "cameo_portraits",
            style=config.style,
        )
        decision_trail.append(
            {
                "stage": "cameo",
                "count": len(plan.characters),
                "roles": [item.role_in_story for item in plan.characters],
                "pillars": sorted(_enabled_pillars),
            }
        )
        report_path = output_dir / "autocameo_report.json"
        report_path.write_text(
            json.dumps(
                {
                    "pillars": sorted(_enabled_pillars),
                    "status": "completed",
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
            "character_count": len(plan.characters),
        }
    except Exception as exc:
        logger.exception("autocameo_workflow failed")
        return {
            "status": "failed",
            "error": str(exc),
            "report_path": str(output_dir / "autocameo_report.json"),
        }
