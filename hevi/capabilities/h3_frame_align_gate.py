"""Single-segment frame alignment gate (``qa.h3_frame_align_gate``).

Clean-room restatement of the frame-count arithmetic behind the
pixelaigc single-segment H3 workflow (see
``PIXELAIGC_H3_WORKFLOW_ATTRIBUTION.md``): a requested duration
in seconds is converted to frames at 24 fps, floored at 5 frames,
and snapped **up** to the 5 + 17k grid. The grid rule itself is
owned by ``qa.continuation_grid_gate`` -- this module reuses its
``is_on_grid`` and ``snap_up`` and adds no second grid. Snapping
down, or declaring a frame count that is not the snapped-up
value, fails. Because snapping up lengthens the output, a plan
whose snapped length differs from the requested duration must
declare the actual output duration; an undeclared stretch fails.

This module judges plans only. It never generates, never calls a
model, and never re-implements latent or mask machinery.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from hevi.capabilities.continuation_grid_gate import is_on_grid, snap_up
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

FPS = 24
GRID_FLOOR_FRAMES = 5


def _issue(code: str, detail: str, **extra: Any) -> dict[str, Any]:
    issue = {"code": code, "detail": f"qa.h3_frame_align_gate: {detail}"}
    issue.update(extra)
    return issue


def requested_frames(duration_s: float) -> int:
    """Frames before snapping: ``max(5, round(duration * 24))``."""
    return max(GRID_FLOOR_FRAMES, round(duration_s * FPS))


def aligned_frames(duration_s: float) -> int:
    """Frames after snapping up to the 5 + 17k grid."""
    return snap_up(requested_frames(duration_s))


def check_frame_alignment(plan: Any) -> dict[str, Any]:
    """Judge one single-segment plan's frame alignment.

    ``plan`` is an object with ``duration_s`` (requested seconds)
    and ``frames`` (declared frame count). ``snap_direction``
    must be ``"up"`` when present. When the snapped length
    differs from the request, ``declared_output_s`` must state
    the actual output duration (``frames / 24``). Returns ``ok``
    / ``issues`` / ``alignment``.
    """
    issues: list[dict[str, Any]] = []
    if not isinstance(plan, dict):
        return {
            "ok": False,
            "issues": [_issue("plan_not_object", "frame plan must be an object")],
            "alignment": None,
        }
    duration_s = plan.get("duration_s")
    frames = plan.get("frames")
    if not isinstance(duration_s, (int, float)) or isinstance(duration_s, bool) or duration_s <= 0:
        issues.append(_issue("duration_undeclared", "duration_s must be a positive number"))
        return {"ok": False, "issues": issues, "alignment": None}
    if not isinstance(frames, int) or isinstance(frames, bool):
        issues.append(_issue("frames_undeclared", "frames must be an integer"))
        return {"ok": False, "issues": issues, "alignment": None}
    expected = aligned_frames(duration_s)
    snap_direction = plan.get("snap_direction", "up")
    if snap_direction != "up":
        issues.append(
            _issue(
                "snap_direction_not_up",
                f"snap_direction must be 'up', got {snap_direction!r}; "
                "snapping down silently shortens the segment",
                snap_direction=snap_direction,
            )
        )
    if frames != expected:
        issues.append(
            _issue(
                "frame_count_off_grid",
                f"frames must be the snapped-up count {expected} for "
                f"{duration_s}s, got {frames}",
                frames=frames,
                expected=expected,
                on_grid=is_on_grid(frames),
            )
        )
    output_s = frames / FPS
    declared_output = plan.get("declared_output_s")
    if abs(output_s - duration_s) > 1e-9:
        if declared_output is None:
            issues.append(
                _issue(
                    "undeclared_output_stretch",
                    f"snapped output is {output_s:.3f}s, not the "
                    f"requested {duration_s}s; declared_output_s "
                    "must state the actual output duration",
                    output_s=output_s,
                )
            )
        elif abs(declared_output - output_s) > 1e-9:
            issues.append(
                _issue(
                    "output_duration_mismatch",
                    f"declared_output_s {declared_output} does not "
                    f"match frames/24 = {output_s:.3f}",
                    output_s=output_s,
                )
            )
    return {
        "ok": not issues,
        "issues": issues,
        "alignment": {
            "duration_s": duration_s,
            "requested_frames": requested_frames(duration_s),
            "frames": frames,
            "expected_frames": expected,
            "output_s": output_s,
            "on_grid": is_on_grid(frames),
        },
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_frame_alignment(params.get("plan"))
    report_path = out_dir / "h3_frame_align_gate.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path),
            "verdict": "pass" if report["ok"] else "fail"},
    )


def register_h3_frame_align_gate_capabilities_once() -> list[str]:
    """Register ``qa.h3_frame_align_gate`` on the unified registry (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.h3_frame_align_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "plan": {"type": "object"},
                },
                "required": ["plan"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Single-segment frame alignment gate: requested "
                "seconds convert to frames at 24 fps and snap UP to "
                "the 5+17k grid (grid owned by "
                "qa.continuation_grid_gate); any output stretch must "
                "be declared. Judges plans only; no generation."
            ),
            line="qa",
        )
    )
    return ["qa.h3_frame_align_gate"]


register_h3_frame_align_gate_capabilities_once()
