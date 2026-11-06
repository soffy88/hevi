"""Dance camera-sync gate (``qa.dance_camera_sync_gate``).

Clean-room restatement of the dance MV methodology (see
``DANCE_MV_METHODOLOGY_ATTRIBUTION.md``): body and camera
share one clock and one set of peaks. The camera starts
when the body starts, moves while the body moves, arrives
at the open composition at the same instant the hands
finish their extension on the accent, and settles as the
body recovers — never after the action is already done.
For a hero accent the frame must already be in place
before the accent lands. This gate judges the sync
timeline only. It shoots nothing, renders nothing, and
spends nothing: ``executed_here`` is always false.
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

SYNC_TOLERANCE_S = 0.05


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def check_dance_camera_sync(timeline: Any) -> dict[str, Any]:
    """Validate one camera-and-body sync timeline.

    Verdicts are ``pass`` / ``fail`` only. The timeline
    fails when a shot's times are missing or out of order,
    when the camera starts or peaks later than the body
    by more than the tolerance, when the camera never
    settles after the peak, when a hero accent arrives
    before its frame does, or when shots run out of order.
    """
    issues: list[dict[str, Any]] = []

    def fail(code: str, detail: str) -> dict[str, Any]:
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [*issues, _issue(code, detail)],
            "executed_here": False,
        }

    if not isinstance(timeline, dict):
        return fail("timeline_not_object", "sync timeline must be a JSON object")
    shots = timeline.get("shots")
    if not isinstance(shots, list) or not shots:
        return fail("shots_missing", "sync timeline must carry at least one shot")
    previous_start: float | None = None
    for position, shot in enumerate(shots):
        if not isinstance(shot, dict):
            return fail(
                "shot_not_object",
                f"shot {position} must be an object",
            )
        times = (
            "action_start_s",
            "action_peak_s",
            "action_end_s",
            "camera_start_s",
            "camera_peak_s",
            "camera_settled_s",
        )
        for field in times:
            if not _is_number(shot.get(field)):
                return fail(
                    "shot_time_missing",
                    f"shot {position} must carry {field} in seconds",
                )
        start = shot["action_start_s"]
        peak = shot["action_peak_s"]
        end = shot["action_end_s"]
        if start < 0:
            return fail(
                "shot_time_negative",
                f"shot {position} starts before zero",
            )
        if not start <= peak <= end:
            return fail(
                "shot_peak_outside",
                f"shot {position} peak must fall inside its own window",
            )
        if abs(shot["camera_start_s"] - start) > SYNC_TOLERANCE_S:
            return fail(
                "camera_late_start",
                f"shot {position} camera starts later than the body by more than the tolerance",
            )
        if abs(shot["camera_peak_s"] - peak) > SYNC_TOLERANCE_S:
            return fail(
                "camera_late_peak",
                f"shot {position} camera peaks later than the body by more than the tolerance",
            )
        if shot["camera_settled_s"] < peak:
            return fail(
                "camera_no_recovery",
                f"shot {position} camera never settles after the peak",
            )
        if shot.get("hero") is True and shot.get("framing_before_action") is not True:
            return fail(
                "hero_framing_late",
                f"hero shot {position} must have its frame in place before the accent lands",
            )
        if previous_start is not None and start < previous_start:
            return fail(
                "shots_unordered",
                f"shot {position} starts before the previous shot",
            )
        previous_start = start
    return {
        "verdict": "pass",
        "ok": True,
        "issues": [],
        "executed_here": False,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_dance_camera_sync(params.get("timeline"))
    report_path = out_dir / "dance_camera_sync_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_dance_camera_sync_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.dance_camera_sync_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "timeline": {"type": "object"},
                },
                "required": ["timeline"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="oskill",
            description=(
                "Dance camera-sync gate: camera and body start "
                "together, peak together and recover together on "
                "one clock, with the frame in place before any "
                "hero accent."
            ),
        )
    )
    return ["qa.dance_camera_sync_gate"]


__all__ = [
    "SYNC_TOLERANCE_S",
    "check_dance_camera_sync",
    "register_dance_camera_sync_gate_capabilities_once",
]
