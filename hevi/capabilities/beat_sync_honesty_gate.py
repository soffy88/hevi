"""Beat sync honesty gate (``qa.beat_sync_honesty_gate``).

Discipline gate only. Music beat sync is judged on a stated
method, not on a bare claim of tight cuts: beat positions come
from a beat tracker, an equidistant grid is fitted to them by
least squares to recover the true tempo and phase, and the fit
residual must stay within fifteen milliseconds. Times are kept
as floating-point seconds and converted to frames only at the
last step into the renderer, so a plan that rounds to frames
early fails. A cut-point error figure taken from a single
finished film is a project self-report until it is re-measured;
presenting it as verified fails. This gate judges the plan only
and renders nothing. See VIDEO_SHOTCRAFT_ATTRIBUTION.md.
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

# Largest admitted fit residual, in milliseconds.
MAX_RESIDUAL_MS = 15.0


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def check_beat_sync(plan: Any) -> dict[str, Any]:
    """Validate a beat-sync plan. Returns a report; never raises.

    Verdicts are ``pass`` / ``fail`` only. The method must be a
    beat tracker plus a least-squares equidistant grid fit, the
    residual tolerance must sit within the admitted bound, times
    must stay floating-point seconds until the final frame
    conversion, and any cut-point error figure must stay marked
    as a self-report unless re-measured.
    """
    issues: list[dict[str, Any]] = []
    if not isinstance(plan, dict):
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [_issue("plan_not_object", "beat-sync plan must be a JSON object")],
            "residual_tolerance_ms": None,
        }
    if plan.get("beat_tracker") != "librosa_beat_track":
        issues.append(
            _issue(
                "beat_tracker_undeclared",
                "beat positions must come from a declared beat tracker",
            )
        )
    if plan.get("grid_fit") != "least_squares_equidistant":
        issues.append(
            _issue(
                "grid_fit_undeclared",
                "tempo and phase must come from a least-squares equidistant grid fit",
            )
        )
    tolerance = plan.get("residual_tolerance_ms")
    if not isinstance(tolerance, (int, float)) or isinstance(tolerance, bool):
        issues.append(
            _issue(
                "residual_tolerance_missing",
                "fit residual tolerance in milliseconds must be declared",
            )
        )
    elif tolerance <= 0 or tolerance > MAX_RESIDUAL_MS:
        issues.append(
            _issue(
                "residual_tolerance_out_of_bounds",
                "fit residual tolerance must be above zero and within the admitted bound",
            )
        )
    if plan.get("float_seconds_recorded") is not True:
        issues.append(
            _issue(
                "times_not_float_seconds",
                "times must be recorded as floating-point seconds",
            )
        )
    if plan.get("frame_conversion_last_step") is not True:
        issues.append(
            _issue(
                "frame_conversion_too_early",
                "conversion to frames happens only at the last step into the renderer",
            )
        )
    if "cut_point_error_frames" in plan:
        if plan.get("cut_error_verified") is True:
            issues.append(
                _issue(
                    "cut_error_claimed_verified",
                    "a cut-point error figure from a single finished "
                    "film stays a self-report until re-measured",
                )
            )
        if plan.get("cut_error_evidence") not in (
            "project_self_report_unverified",
            "remeasured",
        ):
            issues.append(
                _issue(
                    "cut_error_evidence_missing",
                    "a cut-point error figure must carry its evidence status",
                )
            )
    return {
        "verdict": "fail" if issues else "pass",
        "ok": not issues,
        "issues": issues,
        "residual_tolerance_ms": (tolerance if isinstance(tolerance, (int, float)) else None),
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_beat_sync(params.get("plan"))
    report_path = out_dir / "beat_sync_honesty.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_beat_sync_honesty_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.beat_sync_honesty_gate",
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
                "Beat sync honesty gate: beat tracker plus "
                "least-squares equidistant grid fit, residual "
                "within the admitted bound, floating-point seconds "
                "until the final frame conversion, and cut-point "
                "error figures kept as self-reports until re-measured."
            ),
        )
    )
    return ["qa.beat_sync_honesty_gate"]


__all__ = [
    "MAX_RESIDUAL_MS",
    "check_beat_sync",
    "register_beat_sync_honesty_gate_capabilities_once",
]
