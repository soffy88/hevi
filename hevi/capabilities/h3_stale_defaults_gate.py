"""Stale inner-defaults isolation gate (``qa.h3_stale_defaults_gate``).

Clean-room restatement of the staleness discipline behind the
pixelaigc single-segment H3 workflow (see
``PIXELAIGC_H3_WORKFLOW_ATTRIBUTION.md``): a workflow file can
carry two layers of values -- the outer control panel the caller
actually sets, and older example values left inside a nested
sub-process. Only the outer panel is current. Any effective
configuration value that equals a nested inner default while
differing from the outer panel value is stale and fails; the
plan must be cleaned so the effective configuration comes from
the outer panel alone.

This gate compares caller-declared mappings only. It never reads
a workflow file, never copies example text, and never generates.
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


def _issue(code: str, detail: str, **extra: Any) -> dict[str, Any]:
    issue = {"code": code, "detail": f"qa.h3_stale_defaults_gate: {detail}"}
    issue.update(extra)
    return issue


def check_stale_defaults(plan: Any) -> dict[str, Any]:
    """Judge one plan's effective configuration for stale values.

    ``plan`` is an object with ``outer_panel`` (the current
    caller-set values), ``inner_defaults`` (values left inside a
    nested sub-process), and ``effective`` (the configuration
    that would actually run). Every effective field that equals
    an inner default while differing from the outer panel fails
    as ``stale_inner_defaults`` and names the field. A plan
    without an outer panel, or without declared inner defaults,
    cannot be judged and fails. Returns ``ok`` / ``issues`` /
    ``stale_fields``.
    """
    issues: list[dict[str, Any]] = []
    stale_fields: list[str] = []
    if not isinstance(plan, dict):
        return {
            "ok": False,
            "issues": [_issue("plan_not_object", "plan must be an object")],
            "stale_fields": stale_fields,
        }
    outer = plan.get("outer_panel")
    inner = plan.get("inner_defaults")
    effective = plan.get("effective")
    if not isinstance(outer, dict) or not outer:
        issues.append(
            _issue(
                "outer_panel_undeclared",
                "outer_panel (current caller-set values) is required",
            )
        )
    if not isinstance(inner, dict) or not inner:
        issues.append(
            _issue(
                "inner_defaults_undeclared",
                "inner_defaults (nested sub-process leftovers) must "
                "be declared so staleness can be checked",
            )
        )
    if not isinstance(effective, dict) or not effective:
        issues.append(
            _issue("effective_undeclared", "effective configuration is required")
        )
    if issues:
        return {"ok": False, "issues": issues, "stale_fields": stale_fields}
    for field, value in effective.items():
        if field in inner and value == inner[field] and outer.get(field) != value:
            stale_fields.append(field)
            issues.append(
                _issue(
                    "stale_inner_defaults",
                    f"effective field {field!r} equals a stale nested "
                    "default and differs from the outer panel; clean "
                    "the plan so the outer panel governs",
                    field=field,
                    value=value,
                )
            )
    return {"ok": not issues, "issues": issues, "stale_fields": stale_fields}


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_stale_defaults(params.get("plan"))
    report_path = out_dir / "h3_stale_defaults_gate.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path),
            "verdict": "pass" if report["ok"] else "fail"},
    )


def register_h3_stale_defaults_gate_capabilities_once() -> list[str]:
    """Register ``qa.h3_stale_defaults_gate`` on the unified registry (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.h3_stale_defaults_gate",
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
                "Stale inner-defaults isolation gate: the effective "
                "configuration must come from the outer control "
                "panel; any value equal to a nested sub-process "
                "default that differs from the panel fails. Judges "
                "declared mappings only; never reads workflow files."
            ),
            line="qa",
        )
    )
    return ["qa.h3_stale_defaults_gate"]


register_h3_stale_defaults_gate_capabilities_once()
