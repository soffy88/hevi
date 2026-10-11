"""omodul.script2video_kernel_workflow — 五核文本规划(+可选肖像/过渡)。

3O 归属(待上游): `omodul.script2video_kernel_workflow`。
三件套签名,失败不 raise,显式支柱。不在本模块顶层同时 import oprim 与 omodul。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hevi.layer4_legacy.script2video.omodul_impl.kernel_plan import plan_kernel_artifacts
from hevi.layer4_legacy.script2video.oprim_impl.camera_graph import (
    generation_order,
    get_priority_shots,
)
from hevi.layer4_legacy.script2video.oprim_impl.variation import needs_last_frame

logger = logging.getLogger(__name__)


@dataclass
class Script2VideoKernelConfig:
    style: str = "cinematic"
    generate_portraits: bool = False
    generate_transitions: bool = False
    render: bool = False
    engine: str = "sdturbo_cpu"
    target_width: int = 1080
    target_height: int = 1920
    fps: int = 25
    kf_width: int = 512
    kf_height: int = 512
    face_threshold: float = 0.35
    enable_tts: bool = True
    enable_subtitles: bool = True
    base_seed: int = 42


@dataclass
class Script2VideoKernelInput:
    shots: list[dict[str, Any]]
    characters: list[dict[str, Any]] = field(default_factory=list)
    image_gen: Any = None
    video_gen: Any = None
    extra: dict[str, Any] = field(default_factory=dict)


async def script2video_kernel_workflow(
    config: Script2VideoKernelConfig,
    input_data: Script2VideoKernelInput,
    output_dir: Path,
    *,
    on_step: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """规划拆镜与机位树;可选生成三联画与过渡视频。"""
    _enabled_pillars = {"report", "cost", "decision_trail"}

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    decision_trail: list[dict[str, Any]] = []

    def _step(stage: str, pct: float, **metadata: Any) -> None:
        if on_step is not None:
            on_step({"stage": stage, "pct": pct, **metadata})

    try:
        if not input_data.shots:
            return {"status": "failed", "error": "script2video_kernel_workflow: no shots"}

        _step("plan_text", 10.0)
        plan = plan_kernel_artifacts(input_data.shots, input_data.characters)
        order = generation_order(plan.camera_tree)
        priority = get_priority_shots(plan.camera_tree)
        last_frame_shots = [
            visual.idx for visual in plan.visual_plans if needs_last_frame(visual.variation_type)
        ]
        decision_trail.append(
            {
                "stage": "plan_text",
                "shot_count": len(plan.shots),
                "camera_count": len(plan.camera_tree.cameras),
                "generation_order": order,
                "priority_shots": priority,
                "last_frame_shots": last_frame_shots,
                "pillars": sorted(_enabled_pillars),
            }
        )

        portraits_path = None
        if config.generate_portraits and input_data.image_gen is not None:
            from hevi.layer4_legacy.script2video.oskill_impl.portrait_triptych import (
                generate_all_portraits,
            )

            _step("portraits", 45.0)
            registry = await generate_all_portraits(
                plan.characters,
                output_dir=output_dir / "character_portraits",
                style=config.style,
                image_gen=input_data.image_gen,
            )
            portraits_path = str(
                output_dir / "character_portraits" / "character_portraits_registry.json"
            )
            decision_trail.append({"stage": "portraits", "count": len(registry.portraits)})

        if config.generate_transitions and input_data.video_gen is not None:
            _step("transitions", 75.0)
            decision_trail.append(
                {
                    "stage": "transitions",
                    "note": "requires parent first_frame on disk; skipped when frames absent",
                }
            )

        _step("report", 90.0)
        report_path = output_dir / "kernel_report.json"
        report = {
            "pillars": sorted(_enabled_pillars),
            "status": "completed",
            "style": config.style,
            "plan": plan.to_dict(),
            "generation_order": order,
            "priority_shots": priority,
            "last_frame_shots": last_frame_shots,
            "portraits_path": portraits_path,
            "decision_trail": decision_trail,
        }
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

        if config.render:
            _step("render", 92.0)
            from hevi.layer4_legacy.keyframe.omodul_impl.video_render import (
                RenderConfig,
                render_dramakey_pipeline,
            )
            from hevi.layer4_legacy.script2video.oprim_impl.character_fuse import (
                fuse_characters_to_cards,
            )

            cards = fuse_characters_to_cards(input_data.characters)
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
            )

            render_res = render_dramakey_pipeline(
                shots=input_data.shots,
                output_dir=output_dir,
                character_cards=cards,
                config=render_cfg,
                on_progress=on_step,
            )

            decision_trail.append(
                {
                    "stage": "render",
                    "rendered_shots": len(input_data.shots),
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
                "generation_order": order,
                "priority_shots": priority,
                "rendered_shots": len(input_data.shots),
            }

        _step("completed", 100.0)
        return {
            "status": "completed",
            "report_path": str(report_path),
            "decision_trail": decision_trail,
            "generation_order": order,
            "priority_shots": priority,
        }
    except Exception as exc:
        logger.exception("script2video_kernel_workflow failed")
        return {
            "status": "failed",
            "error": str(exc),
            "report_path": str(output_dir / "kernel_report.json"),
        }
