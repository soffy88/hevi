"""Workbench edit boundary gate (``qa.workbench_edit_boundary_gate``).

Discipline gate only. A browser workbench edits a finished film
within fixed bounds: the rhythm-defining constants (entry timing,
easing, camera path) stay constants and are never exposed as
editable controls, and demonstration cards are editable for time
and layer only unless a schema says otherwise. Edits live in the
browser's local storage; there is no mechanism that writes them
back into the film's source files, so any claim of write-back
fails. A claim that preview and render are frame-identical is
admitted only with a completed parity run behind it; before any
parity run the claim stays unverified. This gate judges the plan
only and builds no editor. See VIDEO_SHOTCRAFT_ATTRIBUTION.md.
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

# Export shapes a workbench may produce. Anything else is not an
# admitted export of the editing session.
EXPORT_FORMATS: tuple[str, ...] = ("mp4", "project_json")


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def check_workbench_edit_boundary(plan: Any) -> dict[str, Any]:
    """Validate a workbench edit-boundary plan. Never raises.

    Verdicts are ``pass`` / ``fail`` only. Rhythm constants must
    stay unexposed, demonstration cards must stay time/layer-only
    by default, edits must live in browser local storage with no
    write-back claim, and a frame-identical claim needs a
    completed parity run.
    """
    issues: list[dict[str, Any]] = []
    if not isinstance(plan, dict):
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [_issue("plan_not_object", "edit plan must be a JSON object")],
            "parity_status": "unverified",
        }
    if plan.get("rhythm_constants_exposed") is True:
        issues.append(
            _issue(
                "rhythm_constants_exposed",
                "rhythm-defining constants must stay unexposed",
            )
        )
    elif plan.get("rhythm_constants_exposed") is not False:
        issues.append(
            _issue(
                "rhythm_constants_undeclared",
                "plan must declare rhythm_constants_exposed as true or false",
            )
        )
    if plan.get("demo_cards_time_layer_only") is not True:
        issues.append(
            _issue(
                "demo_cards_over_editable",
                "demonstration cards are editable for time and layer "
                "only unless a schema says otherwise",
            )
        )
    if plan.get("edits_stored_in") != "localStorage":
        issues.append(
            _issue(
                "edits_storage_undeclared",
                "edits must be declared as stored in browser localStorage",
            )
        )
    if plan.get("writes_back_to_source") is True:
        issues.append(
            _issue(
                "write_back_claimed",
                "no mechanism writes workbench edits back into the film source files",
            )
        )
    exports = plan.get("export_formats")
    if exports is not None and (
        not isinstance(exports, list) or any(e not in EXPORT_FORMATS for e in exports)
    ):
        issues.append(
            _issue(
                "export_format_unknown",
                f"export formats must come from {list(EXPORT_FORMATS)}",
            )
        )
    parity_verified = plan.get("parity_verified") is True
    if plan.get("frame_identical_claim") is True and not parity_verified:
        issues.append(
            _issue(
                "frame_identical_unverified",
                "a frame-identical claim needs a completed parity run",
            )
        )
    return {
        "verdict": "fail" if issues else "pass",
        "ok": not issues,
        "issues": issues,
        "parity_status": "verified" if parity_verified else "unverified",
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_workbench_edit_boundary(params.get("plan"))
    report_path = out_dir / "workbench_edit_boundary.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_workbench_edit_boundary_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.workbench_edit_boundary_gate",
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
                "Workbench edit boundary gate: rhythm constants stay "
                "unexposed, demonstration cards stay time/layer-only, "
                "edits live in browser local storage with no "
                "write-back, and frame-identical claims need a "
                "completed parity run."
            ),
        )
    )
    return ["qa.workbench_edit_boundary_gate"]


__all__ = [
    "EXPORT_FORMATS",
    "check_workbench_edit_boundary",
    "register_workbench_edit_boundary_gate_capabilities_once",
]
