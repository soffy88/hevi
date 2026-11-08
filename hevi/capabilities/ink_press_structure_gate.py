"""Ink Press structure gate (``qa.ink_press_structure_gate``).

Clean-room discipline gate only. The Ink Press reference film is a
fixed-grid structure: 1920x1080 at 30 frames per second, 1085
frames in total, ten shots in one contiguous tiling, and a
sound-effect cue sheet. This gate judges structure only: it never
renders, and ``rendered_here`` must be false. Shot counts, frame
grids, and cue-sheet presence are checked from caller-supplied
numbers; no template code, scene markup, screenshot, or audio from
any outside repository is copied here. See
VIDEO_SHOTCRAFT_ATTRIBUTION.md.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

EXPECTED_WIDTH = 1920
EXPECTED_HEIGHT = 1080
EXPECTED_FPS = 30
EXPECTED_FRAMES = 1085
EXPECTED_SHOTS = 10


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def check_ink_press_structure(plan: Any) -> dict[str, Any]:
    """Validate an Ink Press structure plan. Returns a report; never raises.

    Verdicts are ``pass`` / ``fail`` only. Grid, shot count, shot
    tiling, and cue-sheet presence are all checked; rendering is
    never claimed here.
    """
    issues: list[dict[str, Any]] = []
    if not isinstance(plan, dict):
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [
                _issue("plan_not_object", "structure plan must be a JSON object")
            ],
            "grid": {
                "width": EXPECTED_WIDTH,
                "height": EXPECTED_HEIGHT,
                "fps": EXPECTED_FPS,
                "frames": EXPECTED_FRAMES,
            },
        }
    if plan.get("width") != EXPECTED_WIDTH:
        issues.append(
            _issue("width_wrong", f"width must be {EXPECTED_WIDTH}")
        )
    if plan.get("height") != EXPECTED_HEIGHT:
        issues.append(
            _issue("height_wrong", f"height must be {EXPECTED_HEIGHT}")
        )
    if plan.get("fps") != EXPECTED_FPS:
        issues.append(_issue("fps_wrong", f"fps must be {EXPECTED_FPS}"))
    if plan.get("frames") != EXPECTED_FRAMES:
        issues.append(
            _issue("frames_wrong", f"total frames must be {EXPECTED_FRAMES}")
        )
    shots = plan.get("shots")
    if not isinstance(shots, list):
        issues.append(
            _issue("shots_missing", "plan must declare a shots list")
        )
        shots = []
    if isinstance(plan.get("shots"), list) and len(shots) != EXPECTED_SHOTS:
        issues.append(
            _issue(
                "shot_count_wrong",
                f"the structure has exactly {EXPECTED_SHOTS} shots",
            )
        )
    cursor = 0
    for index, shot in enumerate(shots):
        label = f"shots[{index}]"
        if not isinstance(shot, dict):
            issues.append(
                _issue(f"{label}:not_object", "each shot must be an object")
            )
            continue
        start = shot.get("start_frame")
        end = shot.get("end_frame")
        if not isinstance(start, int) or not isinstance(end, int):
            issues.append(
                _issue(
                    f"{label}:frames_not_integers",
                    "each shot must declare integer start_frame/end_frame",
                )
            )
            continue
        if start != cursor:
            issues.append(
                _issue(
                    f"{label}:tiling_gap",
                    f"shot {index} must start at frame {cursor}, got {start}",
                )
            )
        if end <= start:
            issues.append(
                _issue(
                    f"{label}:empty_shot",
                    "each shot must cover at least one frame",
                )
            )
        cursor = end
    if isinstance(plan.get("shots"), list) and shots and cursor != EXPECTED_FRAMES:
        issues.append(
            _issue(
                "tiling_incomplete",
                f"shots must tile exactly {EXPECTED_FRAMES} frames, "
                f"ended at {cursor}",
            )
        )
    cue_sheet = plan.get("sfx_cue_sheet")
    if not isinstance(cue_sheet, list) or not cue_sheet:
        issues.append(
            _issue(
                "cue_sheet_missing",
                "plan must declare a non-empty sound-effect cue sheet",
            )
        )
    if plan.get("rendered_here") is not False:
        issues.append(
            _issue(
                "rendered_here_must_be_false",
                "this gate judges structure only and never renders; "
                "rendered_here must be false",
            )
        )
    return {
        "verdict": "fail" if issues else "pass",
        "ok": not issues,
        "issues": issues,
        "grid": {
            "width": EXPECTED_WIDTH,
            "height": EXPECTED_HEIGHT,
            "fps": EXPECTED_FPS,
            "frames": EXPECTED_FRAMES,
            "seconds": round(EXPECTED_FRAMES / EXPECTED_FPS, 2),
        },
    }


def _render(params: dict[str, Any], out_dir: Any, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_ink_press_structure(params.get("plan"))
    report_path = out_dir / "ink_press_structure.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_ink_press_structure_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.ink_press_structure_gate",
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
            layer="oskill",
            description=(
                "Ink Press structure gate: fixed 1920x1080 @ 30fps "
                "grid, 1085 frames, ten contiguous shots, and a "
                "sound-effect cue sheet; structure only, never rendered."
            ),
        )
    )
    return ["qa.ink_press_structure_gate"]


__all__ = [
    "check_ink_press_structure",
    "register_ink_press_structure_gate_capabilities_once",
]
