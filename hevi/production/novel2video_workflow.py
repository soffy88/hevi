"""omodul.novel2video_workflow — 长篇层次规划,不直接渲像素。

3O 归属(待上游): `omodul.novel2video_workflow`。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hevi.script2video.adapter_schemas import LengthBudget
from hevi.script2video.omodul.novel_plan import plan_novel2video

logger = logging.getLogger(__name__)


@dataclass
class Novel2VideoConfig:
    max_events: int = 50
    max_scenes_per_event: int = 5


@dataclass
class Novel2VideoInput:
    novel_text: str
    extra: dict[str, Any] = field(default_factory=dict)


async def novel2video_workflow(
    config: Novel2VideoConfig,
    input_data: Novel2VideoInput,
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
        if not (input_data.novel_text or "").strip():
            return {"status": "failed", "error": "novel2video_workflow: empty novel_text"}
        _step("adapt", 25.0)
        plan = plan_novel2video(
            input_data.novel_text,
            budget=LengthBudget(
                max_events=config.max_events,
                max_scenes_per_event=config.max_scenes_per_event,
            ),
        )
        decision_trail.append(
            {
                "stage": "adapt",
                "events": len(plan.events),
                "scenes": len(plan.scenes),
                "compression_ratio": round(plan.compression_ratio, 4),
                "book_size": len(plan.book),
                "pillars": sorted(_enabled_pillars),
            }
        )
        report_path = output_dir / "novel2video_report.json"
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
            "event_count": len(plan.events),
            "scene_count": len(plan.scenes),
        }
    except Exception as exc:
        logger.exception("novel2video_workflow failed")
        return {
            "status": "failed",
            "error": str(exc),
            "report_path": str(output_dir / "novel2video_report.json"),
        }
