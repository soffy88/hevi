"""Dance physical-camera gate (``qa.dance_camera_physical_gate``).

Clean-room restatement of the dance MV methodology (see
``DANCE_MV_METHODOLOGY_ATTRIBUTION.md``): a shot is
written as a physical fact, not as an effect name. The
record must say where the camera really stands, how
high it sits, how far it is from the dancer, which way
its lens points, how the dancer sits in space before
it, what that position naturally shows, how it answers
the dancer's movement, and where it stops. Angle numbers
are refused — no "low angle 30 degrees" — because the
real position, distance and axis are what control the
picture. The one exception is the true overhead preset:
a camera directly above the dancer, lens straight down,
which is a position, not a number. This gate judges the
shot record only. It shoots nothing, renders nothing,
and spends nothing: ``executed_here`` is always false.
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

# The eight physical facts every shot must carry.
SHOT_ELEMENTS: tuple[str, ...] = (
    "placement",
    "height",
    "optical_axis",
    "spatial_relation",
    "physical_result",
    "movement_response",
    "camera_lock",
)
PRESETS: frozenset[str] = frozenset({"none", "overhead_90"})
OVERHEAD_HEIGHT = "directly_above"

# Abstract effect names the record must not lean on.
ABSTRACT_TERMS: tuple[str, ...] = (
    "extreme low angle",
    "dutch angle",
    "dynamic orbit",
    "close-up cinematic",
    "cinematic camera",
)


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def check_dance_camera_physical(shot: Any) -> dict[str, Any]:
    """Validate one shot's physical camera record.

    Verdicts are ``pass`` / ``fail`` only. The shot fails
    when any of the eight physical facts is missing, when
    the camera distance is missing or not positive, when
    an angle number appears outside the true overhead
    preset, when the overhead preset does not sit directly
    above the dancer, or when the record leans on an
    abstract effect name instead of a real position.
    """
    issues: list[dict[str, Any]] = []

    def fail(code: str, detail: str) -> dict[str, Any]:
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [*issues, _issue(code, detail)],
            "executed_here": False,
        }

    if not isinstance(shot, dict):
        return fail("shot_not_object", "camera record must be a JSON object")
    for element in SHOT_ELEMENTS:
        value = shot.get(element)
        if not isinstance(value, str) or not value.strip():
            return fail(
                "shot_element_missing",
                f"shot must state its {element} as a physical fact",
            )
    distance = shot.get("distance_m")
    if not isinstance(distance, (int, float)) or isinstance(distance, bool):
        return fail(
            "distance_missing",
            "shot must state the real camera distance in metres",
        )
    if distance <= 0:
        return fail(
            "distance_not_positive",
            "camera distance must be a positive number of metres",
        )
    preset = shot.get("preset", "none")
    if preset not in PRESETS:
        return fail(
            "preset_unknown",
            "camera preset must be none or overhead_90",
        )
    angle = shot.get("angle_degrees")
    if angle is not None and not (preset == "overhead_90" and angle == 90):
        return fail(
            "angle_number_refused",
            "angle numbers are refused; write the real camera "
            "position instead — the only exception is the true "
            "overhead preset at 90 degrees",
        )
    if preset == "overhead_90" and shot.get("height") != OVERHEAD_HEIGHT:
        return fail(
            "overhead_height_wrong",
            "the true overhead preset sits directly above the "
            "dancer, lens straight down — not a diagonal high shot",
        )
    text = " ".join(
        shot[element].lower() for element in ("placement", "optical_axis", "movement_response")
    )
    for term in ABSTRACT_TERMS:
        if term in text:
            return fail(
                "abstract_angle_term",
                f"shot leans on abstract effect name {term!r}; write "
                "where the camera really stands instead",
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
    report = check_dance_camera_physical(params.get("shot"))
    report_path = out_dir / "dance_camera_physical_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_dance_camera_physical_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.dance_camera_physical_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "shot": {"type": "object"},
                },
                "required": ["shot"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="oskill",
            description=(
                "Dance physical-camera gate: eight physical facts "
                "per shot, real distance, no angle numbers except "
                "the true overhead preset, no abstract effect names."
            ),
        )
    )
    return ["qa.dance_camera_physical_gate"]


__all__ = [
    "ABSTRACT_TERMS",
    "OVERHEAD_HEIGHT",
    "PRESETS",
    "SHOT_ELEMENTS",
    "check_dance_camera_physical",
    "register_dance_camera_physical_gate_capabilities_once",
]
