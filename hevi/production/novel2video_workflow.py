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

from hevi.layer4_legacy.script2video.omodul_impl.novel_plan import plan_novel2video
from hevi.script2video.adapter_schemas import LengthBudget

logger = logging.getLogger(__name__)


@dataclass
class Novel2VideoConfig:
    max_events: int = 50
    max_scenes_per_event: int = 5
    render: bool = False
    engine: str = "sdturbo_cpu"
    target_width: int = 1080
    target_height: int = 1920
    fps: int = 25
    kf_width: int = 512
    kf_height: int = 512
    target_duration_s: float = 60.0
    face_threshold: float = 0.35
    enable_tts: bool = True
    enable_subtitles: bool = True
    base_seed: int = 42
    style: str = "anime_guofeng"


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

        if config.render:
            _step("render", 50.0)
            from hevi.layer4_legacy.keyframe.omodul_impl.video_render import (
                RenderConfig,
                render_dramakey_pipeline,
            )
            from hevi.layer4_legacy.script2video.oprim_impl.character_fuse import (
                fuse_characters_to_cards,
            )
            from hevi.layer4_legacy.script2video.oskill_impl.shot_budget import (
                shot_budget_for_duration,
            )

            # Convert planned scenes into shots
            max_shots = shot_budget_for_duration(config.target_duration_s, min_shot_s=3.0, max_shot_s=5.0)
            raw_shots: list[dict[str, Any]] = []
            all_characters = []
            for s_idx, scene in enumerate(plan.scenes):
                char_names = [c.name for c in scene.characters]
                all_characters.extend([{"name": c.name, "description": c.description} for c in scene.characters])
                raw_shots.append(
                    {
                        "idx": s_idx,
                        "text": scene.script,
                        "visual_desc": scene.script,
                        "environment": scene.slugline,
                        "visible_chars": char_names,
                    }
                )

            effective_shots = raw_shots[:max_shots] if max_shots > 0 else raw_shots
            char_cards = fuse_characters_to_cards(all_characters)

            render_cfg = RenderConfig(
                engine=config.engine,
                target_width=config.target_width,
                target_height=config.target_height,
                fps=config.fps,
                kf_width=config.kf_width,
                kf_height=config.kf_height,
                face_threshold=config.face_threshold,
                enable_tts=config.enable_tts,
                enable_subtitles=config.enable_subtitles,
                base_seed=config.base_seed,
                style=config.style,
            )

            render_res = render_dramakey_pipeline(
                shots=effective_shots,
                output_dir=output_dir,
                character_cards=char_cards,
                config=render_cfg,
                on_progress=on_step,
            )

            decision_trail.append(
                {
                    "stage": "render",
                    "rendered_shots": len(effective_shots),
                    "final_mp4": render_res["final_mp4"],
                    "qa_passed": render_res["qa_report"]["passed"],
                }
            )
            _step("completed", 100.0)
            return {
                "status": render_res["status"],
                "report_path": str(report_path),
                "final_mp4": render_res["final_mp4"],
                "qa_path": render_res["qa_path"],
                "record_path": render_res["record_path"],
                "characters_path": render_res["characters_path"],
                "contact_sheet": render_res["contact_sheet"],
                "qa_report": render_res["qa_report"],
                "record_report": render_res["record_report"],
                "decision_trail": decision_trail,
                "event_count": len(plan.events),
                "scene_count": len(plan.scenes),
                "rendered_shots": len(effective_shots),
            }

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
