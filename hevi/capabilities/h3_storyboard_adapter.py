"""H3 storyboard compile adapter, fake contract (``video.h3_storyboard_adapter``).

Fake-level adapter only. It turns a caller-supplied storyboard
into per-segment generation plans -- durations, frame counts,
continuation declarations and reference mappings -- and it
stops there. It never submits anything to a backend, never loads
a weight, never mixes LoRA families, and never silently repairs
an off-grid plan: a segment whose frame count is not on hevi's
5+17k grid (see ``qa.continuation_grid_gate``) raises
``CapabilityError`` and no plan is emitted. The reviewed
template's 120-frame plan fails exactly this check.

Continuation is a declaration, not a measurement: each segment
after the first names the previous segment as its tail-frame
source. Whether a real relay holds its subject is a question for
the execution layer and the degradation ledger, neither of
which this adapter claims.

Clean-room contract restated from the storyboard discipline in
the Infinite Creation review (see
``INFINITE_CREATION_ATTRIBUTION.md``). No workflow document,
prompt text, or weight parameter from the reviewed project is
copied here.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

GRID_BASE = 5
GRID_STEP = 17
TAIL_FRAME_COUNT = 5


def compile_storyboard(storyboard: Any) -> dict[str, Any]:
    """Compile a storyboard into per-segment generation plans.

    ``storyboard`` carries ``fps`` and ``segments`` (each with
    ``id``, ``duration_s``, ``prompt`` and optional ``loras`` and
    ``references``). Raises ``CapabilityError`` on any off-grid
    segment, any stacked LoRA, or any missing field: fail-closed,
    no partial plan is returned.
    """
    if not isinstance(storyboard, dict):
        raise CapabilityError("storyboard must be an object")
    fps = storyboard.get("fps")
    if not isinstance(fps, (int, float)) or fps <= 0:
        raise CapabilityError("storyboard requires fps > 0")
    segments = storyboard.get("segments")
    if not isinstance(segments, list) or not segments:
        raise CapabilityError("storyboard requires a non-empty segments list")
    plans: list[dict[str, Any]] = []
    previous_id: str | None = None
    total_frames = 0
    for index, segment in enumerate(segments):
        if not isinstance(segment, dict):
            raise CapabilityError(f"segment {index} is not an object")
        segment_id = segment.get("id")
        duration = segment.get("duration_s")
        prompt = segment.get("prompt")
        if not segment_id:
            raise CapabilityError(f"segment {index} lacks an id")
        if not isinstance(duration, (int, float)) or duration <= 0:
            raise CapabilityError(f"segment {segment_id} requires duration_s > 0")
        if not isinstance(prompt, str) or not prompt.strip():
            raise CapabilityError(f"segment {segment_id} requires a non-empty prompt")
        loras = segment.get("loras", [])
        if not isinstance(loras, list):
            raise CapabilityError(f"segment {segment_id} loras must be a list")
        if len(loras) > 1:
            raise CapabilityError(
                f"segment {segment_id} stacks {len(loras)} LoRAs; "
                "hevi never mixes LoRA families in one generation"
            )
        frame_count = round(duration * fps)
        if (frame_count - GRID_BASE) % GRID_STEP != 0:
            raise CapabilityError(
                f"segment {segment_id} frame count {frame_count} "
                f"({duration}s at {fps}fps) is not on the 5+17k grid; "
                "no plan is emitted"
            )
        references = segment.get("references", {})
        if not isinstance(references, dict):
            raise CapabilityError(f"segment {segment_id} references must be an object")
        plans.append(
            {
                "segment_id": segment_id,
                "order": index + 1,
                "duration_s": duration,
                "fps": fps,
                "frame_count": frame_count,
                "grid_ok": True,
                "prompt": prompt,
                "loras": loras,
                "references": references,
                "continuation": (
                    {
                        "source_segment_id": previous_id,
                        "tail_frame_count": TAIL_FRAME_COUNT,
                        "declaration_only": True,
                    }
                    if previous_id is not None
                    else None
                ),
                "executed_here": False,
            }
        )
        total_frames += frame_count
        previous_id = str(segment_id)
    return {
        "segment_count": len(plans),
        "total_frames": total_frames,
        "fps": fps,
        "segments": plans,
        "executed_here": False,
        "backend_contacted": False,
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    plan = compile_storyboard(params.get("storyboard"))
    plan_path = out_dir / "h3_storyboard_plan.json"
    plan_path.write_text(
        json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(plan_path),
        qa={"plan_json": str(plan_path), "segment_count": plan["segment_count"]},
    )


def register_h3_storyboard_adapter_capabilities_once() -> list[str]:
    """Register ``video.h3_storyboard_adapter`` on the unified registry (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="video.h3_storyboard_adapter",
            kind="video",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "storyboard": {"type": "object"},
                },
                "required": ["storyboard"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "H3 storyboard compile adapter (fake contract): storyboard "
                "to per-segment generation plans with grid-checked frame "
                "counts and tail-frame continuation declarations; never "
                "submits, never loads a weight, off-grid plans fail closed."
            ),
        )
    )
    return ["video.h3_storyboard_adapter"]


__all__ = ["compile_storyboard", "register_h3_storyboard_adapter_capabilities_once"]
