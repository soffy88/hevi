"""omodul.studio_combine_workflow — 配方履约 + 镜头砖 + 过检叠人 + NLE + 矩阵包装。

3O 归属(待上游): `omodul.studio_combine_workflow`。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hevi.studio.brick import ShotBrick, brick_from_payload, import_brick
from hevi.studio.compose_gate import apply_compose_after_qc
from hevi.studio.fulfill import fulfill_order
from hevi.studio.nle import plan_recut
from hevi.studio.packaging import pack_queue, write_pack_tickets

logger = logging.getLogger(__name__)


@dataclass
class StudioCombineConfig:
    execute: bool = True
    compose_after_qc: bool = True
    platforms: list[str] = field(default_factory=lambda: ["douyin", "xiaohongshu"])


@dataclass
class StudioCombineInput:
    order: dict[str, Any] = field(default_factory=dict)
    shot: dict[str, Any] = field(default_factory=dict)
    import_line: str = "explainer"
    timeline_clips: list[dict[str, Any]] = field(default_factory=list)
    film: str = ""
    bgm: str = ""
    topic: str = ""
    accounts: dict[str, list[str]] = field(default_factory=dict)
    qc_report: dict[str, Any] = field(default_factory=dict)
    presenter_image: str = ""
    presenter_audio: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


async def studio_combine_workflow(
    config: StudioCombineConfig,
    input_data: StudioCombineInput,
    output_dir: Path,
    *,
    on_step: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    _enabled_pillars = {"report", "cost", "decision_trail"}
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    trail: list[dict[str, Any]] = []

    def _step(stage: str, pct: float, **meta: Any) -> None:
        if on_step is not None:
            on_step({"stage": stage, "pct": pct, **meta})

    try:
        _step("fulfill", 15.0)
        fulfilled = await fulfill_order(
            input_data.order,
            execute=config.execute,
            output_dir=output_dir / "dispatch",
        )
        trail.append({"stage": "fulfill", **{k: fulfilled.get(k) for k in ("status", "target")}})

        brick: ShotBrick | None = None
        imported: dict[str, Any] = {}
        if input_data.shot:
            _step("brick", 35.0)
            brick = brick_from_payload(input_data.shot)
            brick.write(output_dir / "shot.brick.json")
            imported = import_brick(brick, input_data.import_line)
            trail.append(
                {"stage": "brick", "brick_id": brick.brick_id, "target": imported["target"]}
            )

        recut = plan_recut(
            input_data.timeline_clips,
            bgm=input_data.bgm,
            output=str(output_dir / "recut.mp4"),
            film=input_data.film,
        )
        _step("nle", 55.0)
        trail.append({"stage": "nle", "segments": len(recut.segments)})

        compose: dict[str, Any] = {"status": "skipped"}
        if config.compose_after_qc and input_data.film:
            _step("compose", 70.0)
            compose = await apply_compose_after_qc(
                base_video=input_data.film,
                image_path=input_data.presenter_image or None,
                audio_path=input_data.presenter_audio or None,
                output_path=output_dir / "composed.mp4",
                qc_report=input_data.qc_report,
            )
            trail.append({"stage": "compose", "status": compose.get("status")})

        media = input_data.film or (brick.clip_path if brick else "")
        queue = pack_queue(
            input_data.topic or str(input_data.order.get("topic") or ""),
            config.platforms,
            accounts=input_data.accounts or None,
            media_path=str(media or ""),
        )
        tickets = write_pack_tickets(queue, output_dir / "pack")
        _step("pack", 90.0)
        trail.append({"stage": "pack", "tickets": len(tickets)})

        report = {
            "pillars": sorted(_enabled_pillars),
            "status": "completed",
            "fulfill": fulfilled,
            "brick": brick.to_dict() if brick else None,
            "import": imported,
            "recut": recut.to_dict(),
            "compose": compose,
            "pack": queue.to_dict(),
            "tickets": [str(path) for path in tickets],
            "decision_trail": trail,
        }
        report_path = output_dir / "studio_combine_report.json"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        _step("completed", 100.0)
        return {
            "status": "completed",
            "report_path": str(report_path),
            "decision_trail": trail,
            "fulfill": fulfilled,
        }
    except Exception as exc:
        logger.exception("studio_combine_workflow failed")
        return {
            "status": "failed",
            "error": str(exc),
            "report_path": str(output_dir / "studio_combine_report.json"),
        }
