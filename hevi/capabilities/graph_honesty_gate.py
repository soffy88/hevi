"""Graph honesty gate (``qa.graph_honesty_gate``).

Discipline gate only. A dynamic line-chart plan (a line that
draws itself while a large number counts up to the final value)
must present only real data: values need a declared source, the
label count must match the value count, and the count-up must
land on the final value, which must equal the last plotted
value. A plan with only two data points that draws intermediate
curve points must declare the curve schematic; an undeclared
interpolated curve fails. Invented intermediate data fails.
This gate judges the plan only and renders nothing. See
ANIMATION_SKILLS_ATTRIBUTION.md.
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

MIN_VALUES = 2


def _issue(code: str, detail: str) -> dict[str, str]:
    return {"code": code, "detail": detail}


def check_graph_honesty(plan: Any) -> dict[str, Any]:
    """Check a chart plan for data honesty.

    Returns a report dict with ``verdict`` pass/fail, ``ok``,
    and ``issues``. Unknown or missing sources, mismatched
    labels, negative values, a count-up that misses the final
    value, and undeclared interpolated curves all fail.
    """
    issues: list[dict[str, str]] = []
    if not isinstance(plan, dict):
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [_issue("plan_not_object", "plan must be a JSON object")],
        }
    values = plan.get("values")
    if not isinstance(values, list) or len(values) < MIN_VALUES:
        issues.append(
            _issue(
                "values_too_few",
                "plan must declare at least two values",
            )
        )
        values = values if isinstance(values, list) else []
    for index, value in enumerate(values):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            issues.append(
                _issue(
                    f"values[{index}]:not_number",
                    "every value must be a number",
                )
            )
        elif value < 0:
            issues.append(
                _issue(
                    f"values[{index}]:negative",
                    "values must be zero or greater",
                )
            )
    labels = plan.get("labels")
    if not isinstance(labels, list):
        issues.append(
            _issue("labels_missing", "plan must declare a labels list")
        )
    elif len(labels) != len(values):
        issues.append(
            _issue(
                "labels_values_mismatch",
                "label count must equal value count",
            )
        )
    source = plan.get("data_source")
    if not isinstance(source, str) or not source.strip():
        issues.append(
            _issue(
                "data_source_missing",
                "plan must declare a non-empty data source; "
                "data without a source is treated as invented",
            )
        )
    final = plan.get("final")
    if values and all(
        isinstance(v, (int, float)) and not isinstance(v, bool) for v in values
    ):
        if final != values[-1]:
            issues.append(
                _issue(
                    "final_mismatch",
                    "the count-up final value must equal the "
                    "last plotted value",
                )
            )
    elif final is None:
        issues.append(
            _issue("final_missing", "plan must declare the count-up final value")
        )
    decimals = plan.get("decimals", 0)
    if isinstance(decimals, bool) or not isinstance(decimals, int) or decimals < 0 or decimals > 6:
        issues.append(
            _issue(
                "decimals_invalid",
                "decimals must be an integer between 0 and 6",
            )
        )
    if (
        len(values) == MIN_VALUES
        and plan.get("curve_claim") == "interpolated"
        and plan.get("schematic_declared") is not True
    ):
        issues.append(
            _issue(
                "interpolated_curve_undeclared",
                "with only two data points, an interpolated "
                "curve must be declared schematic",
            )
        )
    return {
        "verdict": "fail" if issues else "pass",
        "ok": not issues,
        "issues": issues,
    }


def _render(params: dict[str, Any], out_dir: Any, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_graph_honesty(params.get("plan"))
    report_path = out_dir / "graph_honesty.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_graph_honesty_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.graph_honesty_gate",
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
                "Graph honesty gate: chart values need a declared "
                "source, labels must match values, the count-up "
                "must land on the last value, and an interpolated "
                "curve from two points must be declared schematic."
            ),
        )
    )
    return ["qa.graph_honesty_gate"]


__all__ = [
    "check_graph_honesty",
    "register_graph_honesty_gate_capabilities_once",
]
