"""Reference-frame measurement gate (``qa.reference_frame_measure_gate``).

Clean-room restatement of the Eian short-film workflow
(see ``EIAN_WORKFLOW_ATTRIBUTION.md``): camera language
is hard to describe in words, so the reliable way to
learn it is to watch a reference film frame by frame and
measure the camera and the share of the frame each entry
and exit takes, then imitate the measurements. With no
reference film, the shot is composed from the shotlist
rules instead. This gate judges the study record only.
It watches nothing, measures nothing itself, and spends
nothing: ``executed_here`` is always false.
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

SHOT_FIELDS: tuple[str, ...] = ("size", "camera", "movement", "direction")


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def check_reference_frame_measure(study: Any) -> dict[str, Any]:
    """Validate a reference-film measurement study.

    Verdicts are ``pass`` / ``fail`` only. A study fails
    when it names a reference film but carries no measured
    camera and entry/exit ratios, when a shot is missing
    its size, camera, movement or screen direction, or when
    it has neither a reference film nor a declared
    rule-based composition.
    """
    issues: list[dict[str, Any]] = []

    def fail(code: str, detail: str) -> dict[str, Any]:
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [*issues, _issue(code, detail)],
            "executed_here": False,
        }

    if not isinstance(study, dict):
        return fail("study_not_object", "study must be a JSON object")
    reference = study.get("reference_film")
    has_reference = isinstance(reference, str) and bool(reference.strip())
    if has_reference:
        measurements = study.get("measurements")
        if not isinstance(measurements, list) or not measurements:
            return fail(
                "reference_not_measured",
                "a named reference film needs measured camera and "
                "entry/exit ratios, frame by frame",
            )
        for position, item in enumerate(measurements):
            if not isinstance(item, dict):
                return fail(
                    "measurement_not_object",
                    f"measurement {position} must be an object",
                )
            if not isinstance(item.get("camera"), str) or not item["camera"].strip():
                return fail(
                    "measurement_camera_missing",
                    f"measurement {position} must name the camera",
                )
            ratio = item.get("entry_exit_ratio")
            if not isinstance(ratio, (int, float)):
                return fail(
                    "measurement_ratio_missing",
                    f"measurement {position} must carry its entry/exit ratio",
                )
    elif study.get("composed_from_rules") is not True:
        return fail(
            "no_reference_no_rules",
            "with no reference film, the shot must be composed from the shotlist rules and say so",
        )
    shots = study.get("shots")
    if not isinstance(shots, list) or not shots:
        return fail("shots_missing", "study needs a non-empty shots list")
    for position, shot in enumerate(shots):
        if not isinstance(shot, dict):
            return fail(
                "shot_not_object",
                f"shot {position} must be an object",
            )
        for field in SHOT_FIELDS:
            value = shot.get(field)
            if not isinstance(value, str) or not value.strip():
                return fail(
                    "shot_language_incomplete",
                    f"shot {position} is missing its {field}",
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
    report = check_reference_frame_measure(params.get("study"))
    report_path = out_dir / "reference_frame_measure_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_reference_frame_measure_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.reference_frame_measure_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "study": {"type": "object"},
                },
                "required": ["study"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="oskill",
            description=(
                "Reference-frame measurement gate: camera and "
                "entry/exit ratios measured frame by frame from a "
                "reference film, or shots composed from the shotlist "
                "rules, each with size, camera, movement and direction."
            ),
        )
    )
    return ["qa.reference_frame_measure_gate"]


__all__ = [
    "SHOT_FIELDS",
    "check_reference_frame_measure",
    "register_reference_frame_measure_gate_capabilities_once",
]
