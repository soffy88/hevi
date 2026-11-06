"""Toy clearance gate (``qa.toy_clearance_gate``).

Clean-room restatement of the ChrisHKAI-Video creator-intro
method (see ``CHRISHKAI_VIDEO_ATTRIBUTION.md``): before any
render, every frame is checked for the toy passing through
solid things. Passing through a solid by 15% or more, or by
more than a quarter of the toy's height, fails. A light
touch is a warning, not a failure. A frame the user knowingly
keeps despite a hit must be explicitly noted as forced.
This is a geometric collision check only — it says nothing
about portrait rights, and any claim that it clears a
portrait fails. This gate judges the clearance record only.
It renders nothing: ``executed_here`` is always false.
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

# Fail thresholds, restated from the reviewed method.
PENETRATION_FAIL_PCT = 15.0
HEIGHT_EXCESS_FAIL_FRACTION = 0.25


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def check_toy_clearance(clearance: Any) -> dict[str, Any]:
    """Validate a toy clearance record.

    Pass requires every frame checked before render, no
    penetration at or above 15%, no height excess above a
    quarter of the toy, and any knowingly kept hit explicitly
    noted as forced. A light touch is recorded as a warning.
    A portrait-clearance claim fails outright: this gate is
    geometric only.
    """
    issues: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    def fail(code: str, detail: str) -> dict[str, Any]:
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [*issues, _issue(code, detail)],
            "warnings": warnings,
            "executed_here": False,
        }

    if not isinstance(clearance, dict):
        return fail("clearance_not_object", "clearance must be a JSON object")
    if clearance.get("is_portrait_clearance") is True:
        return fail(
            "portrait_clearance_claim",
            "this is a geometric collision check only; it never clears a portrait",
        )
    if clearance.get("frames_checked") is not True:
        return fail(
            "frames_not_checked",
            "every frame must be checked for penetration before render",
        )
    penetration = clearance.get("max_penetration_pct")
    if not isinstance(penetration, (int, float)) or isinstance(penetration, bool):
        return fail(
            "penetration_unmeasured",
            "clearance must state the worst penetration in percent",
        )
    if penetration >= PENETRATION_FAIL_PCT:
        return fail(
            "penetration_fail",
            f"toy passes through a solid by {penetration}%, at or above the 15% fail line",
        )
    height_excess = clearance.get("max_height_excess_fraction")
    if not isinstance(height_excess, (int, float)) or isinstance(height_excess, bool):
        return fail(
            "height_excess_unmeasured",
            "clearance must state the worst height excess as a fraction of toy height",
        )
    if height_excess > HEIGHT_EXCESS_FAIL_FRACTION:
        return fail(
            "height_excess_fail",
            f"toy passes through a solid by {height_excess} of its height, above the quarter-height fail line",
        )
    if clearance.get("light_touch") is True:
        warnings.append(
            _issue(
                "light_touch",
                "light touch only: recorded as a warning, not a failure",
            )
        )
    if clearance.get("forced_keep") is True and clearance.get("force_noted") is not True:
        return fail(
            "force_not_noted",
            "a knowingly kept hit must be explicitly noted as forced",
        )
    return {
        "verdict": "pass",
        "ok": True,
        "issues": [],
        "warnings": warnings,
        "executed_here": False,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_toy_clearance(params.get("clearance"))
    report_path = out_dir / "toy_clearance_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_toy_clearance_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.toy_clearance_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "clearance": {"type": "object"},
                },
                "required": ["clearance"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="oskill",
            description=(
                "Toy clearance gate: every frame checked before "
                "render, penetration at or above 15% or height excess "
                "above a quarter fails, light touch warns, forced keeps "
                "must be noted; geometric only, never portrait clearance."
            ),
        )
    )
    return ["qa.toy_clearance_gate"]


__all__ = [
    "HEIGHT_EXCESS_FAIL_FRACTION",
    "PENETRATION_FAIL_PCT",
    "check_toy_clearance",
    "register_toy_clearance_gate_capabilities_once",
]
