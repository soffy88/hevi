"""omodul.voicepro_kernel_workflow — Voice-Pro 五核配音规划。

3O 归属(待上游): `omodul.voicepro_kernel_workflow`。
三件套签名,失败不 raise,显式支柱。不在本模块顶层同时 import oprim 与 omodul。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hevi.voicepro.omodul.dub_plan import plan_dub_artifacts

logger = logging.getLogger(__name__)


@dataclass
class VoiceProKernelConfig:
    language: str = ""
    keep_bed: bool = False
    sentence_merge: bool = True
    inference_mode: str | None = None
    model_name: str | None = None


@dataclass
class VoiceProKernelInput:
    cues: list[dict[str, Any]] = field(default_factory=list)
    conversation_text: str = ""
    ref_text: str | None = None
    instruct_text: str | None = None
    bed_path: str | None = None
    clip_durations_s: list[float] | None = None
    extra: dict[str, Any] = field(default_factory=dict)


async def voicepro_kernel_workflow(
    config: VoiceProKernelConfig,
    input_data: VoiceProKernelInput,
    output_dir: Path,
    *,
    on_step: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """规划合句时钟、混音策略、Cosy 模式与 F5 目录;不跑 GPU。"""
    _enabled_pillars = {"report", "cost", "decision_trail"}

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    decision_trail: list[dict[str, Any]] = []

    def _step(stage: str, pct: float, **metadata: Any) -> None:
        if on_step is not None:
            on_step({"stage": stage, "pct": pct, **metadata})

    try:
        if not input_data.cues and not input_data.conversation_text.strip():
            return {"status": "failed", "error": "voicepro_kernel_workflow: no cues"}

        _step("plan_text", 20.0)
        plan = plan_dub_artifacts(
            input_data.cues,
            language=config.language,
            keep_bed=config.keep_bed,
            bed_path=input_data.bed_path,
            inference_mode=config.inference_mode,
            ref_text=input_data.ref_text,
            instruct_text=input_data.instruct_text,
            model_name=config.model_name,
            conversation_text=input_data.conversation_text,
            clip_durations_s=input_data.clip_durations_s,
            sentence_merge=config.sentence_merge,
        )
        decision_trail.append(
            {
                "stage": "plan_text",
                "cue_count": len(plan.cues),
                "slot_count": len(plan.slots),
                "mix": plan.mix.strategy if plan.mix else None,
                "cosy_mode": plan.cosy_mode,
                "f5_model": plan.f5_model,
                "speakers": len(plan.speakers),
                "pillars": sorted(_enabled_pillars),
            }
        )
        _step("report", 90.0)
        report_path = output_dir / "voicepro_report.json"
        report = {
            "pillars": sorted(_enabled_pillars),
            "status": "completed",
            "language": config.language,
            "plan": plan.to_dict(),
            "decision_trail": decision_trail,
        }
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        _step("completed", 100.0)
        return {
            "status": "completed",
            "report_path": str(report_path),
            "decision_trail": decision_trail,
            "cue_count": len(plan.cues),
            "cosy_mode": plan.cosy_mode,
        }
    except Exception as exc:
        logger.exception("voicepro_kernel_workflow failed")
        return {
            "status": "failed",
            "error": str(exc),
            "report_path": str(output_dir / "voicepro_report.json"),
        }
