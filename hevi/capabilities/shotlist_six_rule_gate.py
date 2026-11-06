"""Shotlist six-rule gate (``qa.shotlist_six_rule_gate``).

Clean-room restatement of the Eian short-film workflow
(see ``EIAN_WORKFLOW_ATTRIBUTION.md``): a shotlist decides
the film's quality before any picture is drawn. Six rules
are checked here, in the reviewer's own words — change
angle every shot, keep something moving in frame, name
what is moving, move the camera for a reason, frame every
second so a still looks good, and design the palette up
front with a per-scene colour table checked in black and
white. This gate judges the shotlist record only. It
draws nothing, renders nothing, and spends nothing:
``executed_here`` is always false.
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

# A head or eyes belong near 38% or 62% across the frame,
# with a five-point tolerance either way.
GOLDEN_BANDS: tuple[tuple[float, float], ...] = ((33.0, 43.0), (57.0, 67.0))
MAX_FRONTAL_EYE_LEVEL = 2
MAX_SAME_SIZE_RUN = 2


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def _in_golden_bands(percent: float) -> bool:
    return any(low <= percent <= high for low, high in GOLDEN_BANDS)


def check_shotlist_six_rules(shotlist: Any) -> dict[str, Any]:
    """Validate a shotlist against the six shotlist rules.

    Verdicts are ``pass`` / ``fail`` only. A shotlist fails
    when it uses more than two eye-level frontal shots, when
    three shots in a row share one size, when a shot names
    nothing moving, when a camera move has no reason, when a
    framed subject sits outside the 38%/62% bands, when it
    has no palette table, or when a black-and-white check
    shows figures unreadable against the background with no
    regrade note.
    """
    issues: list[dict[str, Any]] = []

    def fail(code: str, detail: str) -> dict[str, Any]:
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [*issues, _issue(code, detail)],
            "executed_here": False,
        }

    if not isinstance(shotlist, dict):
        return fail("shotlist_not_object", "shotlist must be a JSON object")
    shots = shotlist.get("shots")
    if not isinstance(shots, list) or not shots:
        return fail("shots_missing", "shotlist needs a non-empty shots list")
    frontal = 0
    run_size: str | None = None
    run_length = 0
    for position, shot in enumerate(shots):
        if not isinstance(shot, dict):
            return fail(
                "shot_not_object",
                f"shot {position} must be an object",
            )
        angle = shot.get("angle")
        if angle == "eye_level_frontal":
            frontal += 1
        size = shot.get("size")
        if not isinstance(size, str) or not size.strip():
            return fail(
                "shot_size_missing",
                f"shot {position} must name its size",
            )
        if size == run_size:
            run_length += 1
        else:
            run_size = size
            run_length = 1
        if run_length > MAX_SAME_SIZE_RUN:
            return fail(
                "same_size_run",
                f"shots {position - 2} to {position} share size {size!r}; "
                "vary full, half and close-up",
            )
        moving = shot.get("moving_subject")
        if not isinstance(moving, str) or not moving.strip():
            return fail(
                "nothing_moves",
                f"shot {position} must name what is moving in frame",
            )
        reason = shot.get("camera_reason")
        if not isinstance(reason, str) or not reason.strip():
            return fail(
                "movement_without_reason",
                f"shot {position} must state why the camera moves",
            )
        percent = shot.get("subject_x_percent")
        if percent is not None:
            if not isinstance(percent, (int, float)):
                return fail(
                    "composition_not_number",
                    f"shot {position} subject_x_percent must be a number",
                )
            if not _in_golden_bands(float(percent)):
                return fail(
                    "off_golden_ratio",
                    f"shot {position} subject sits at {percent}% across; "
                    "head or eyes belong near 38% or 62%",
                )
    if frontal > MAX_FRONTAL_EYE_LEVEL:
        return fail(
            "too_many_frontal",
            f"eye-level frontal shots used {frontal} times; at most "
            f"{MAX_FRONTAL_EYE_LEVEL} in the whole film",
        )
    palette = shotlist.get("palette_table")
    if not isinstance(palette, (dict, list)) or not palette:
        return fail(
            "palette_missing",
            "palette must be designed before the first picture, as a per-scene colour table",
        )
    bw_check = shotlist.get("bw_check")
    if not isinstance(bw_check, dict):
        return fail(
            "bw_check_missing",
            "shotlist must carry a black-and-white readability check",
        )
    if bw_check.get("readable") is False:
        note = bw_check.get("regrade_note")
        if not isinstance(note, str) or not note.strip():
            return fail(
                "bw_unreadable_ungraded",
                "black-and-white check shows figures unreadable against "
                "the background, with no regrade note",
            )
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
    report = check_shotlist_six_rules(params.get("shotlist"))
    report_path = out_dir / "shotlist_six_rule_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_shotlist_six_rule_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.shotlist_six_rule_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "shotlist": {"type": "object"},
                },
                "required": ["shotlist"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="oskill",
            description=(
                "Shotlist six-rule gate: change angle every shot, keep "
                "something moving, name what moves, move the camera for "
                "a reason, frame near 38%/62%, palette table with a "
                "black-and-white check."
            ),
        )
    )
    return ["qa.shotlist_six_rule_gate"]


__all__ = [
    "GOLDEN_BANDS",
    "MAX_FRONTAL_EYE_LEVEL",
    "MAX_SAME_SIZE_RUN",
    "check_shotlist_six_rules",
    "register_shotlist_six_rule_gate_capabilities_once",
]
