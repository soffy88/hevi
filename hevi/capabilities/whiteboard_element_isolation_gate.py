"""Whiteboard element isolation gate (``qa.whiteboard_element_isolation_gate``).

Clean-room restatement of the method in ``hevi-vs-explainer-skills-9.md``
section 2 item 9 (Whiteboard Explainer): one element, one picture.
Sharing a picture between elements is what causes colour bleed and
scalloped gaps at reveal time, so the discipline removes the cause at
plan level instead of inspecting it away afterwards:

1. Every whiteboard element binds exactly one asset identifier. An
   asset reused by more than one element must declare the reuse with
   a reason; undeclared reuse fails.
2. Mask invariants: the reveal row spacing must not exceed the pen
   width, and the plan must declare the snake-row inset. A spacing
   wider than the pen, or a missing inset declaration, fails.

This module judges plans only. It renders no mask and touches no
image bytes; the reveal engine contract lives in
``video.whiteboard_mask_contract``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def check_whiteboard_elements(plan: Any) -> dict[str, Any]:
    """Judge one whiteboard element plan. Returns a report; never raises.

    Verdicts are ``pass`` / ``fail`` only.
    """
    issues: list[dict[str, Any]] = []
    elements_out: list[dict[str, Any]] = []
    if not isinstance(plan, dict):
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [_issue("plan_not_object", "plan must be a JSON object")],
            "elements": [],
        }
    elements = plan.get("elements")
    if not isinstance(elements, list) or not elements:
        issues.append(
            _issue("elements_missing", "plan must declare a non-empty elements list")
        )
        elements = elements if isinstance(elements, list) else []
    asset_owners: dict[str, str] = {}
    for index, element in enumerate(elements):
        if not isinstance(element, dict):
            issues.append(
                _issue("element_not_object", f"elements[{index}] must be an object")
            )
            continue
        element_id = element.get("id")
        asset_id = element.get("asset_id")
        if not _is_nonempty_str(element_id):
            issues.append(
                _issue("element_id_missing", f"elements[{index}] must declare an id")
            )
        if not _is_nonempty_str(asset_id):
            issues.append(
                _issue(
                    "asset_binding_missing",
                    f"elements[{index}] must bind exactly one asset_id",
                )
            )
        elif asset_id in asset_owners:
            shared = element.get("shared_asset")
            if not (isinstance(shared, dict) and _is_nonempty_str(shared.get("reason"))):
                issues.append(
                    _issue(
                        "shared_asset_undeclared",
                        f"asset {asset_id!r} is reused by {element_id!r} and "
                        f"{asset_owners[asset_id]!r} without a declared reason",
                    )
                )
        else:
            asset_owners[asset_id] = element_id if _is_nonempty_str(element_id) else "?"
        elements_out.append({"id": element_id, "asset_id": asset_id})
    mask = plan.get("mask")
    if not isinstance(mask, dict):
        issues.append(
            _issue("mask_missing", "plan must declare a mask invariants object")
        )
    else:
        pen_width = mask.get("pen_width")
        row_spacing = mask.get("row_spacing")
        if not _is_number(pen_width) or pen_width <= 0:
            issues.append(
                _issue("pen_width_missing", "mask must declare a positive pen_width")
            )
        if not _is_number(row_spacing) or row_spacing <= 0:
            issues.append(
                _issue("row_spacing_missing", "mask must declare a positive row_spacing")
            )
        if _is_number(pen_width) and _is_number(row_spacing) and row_spacing > pen_width:
            issues.append(
                _issue(
                    "row_spacing_exceeds_pen_width",
                    f"row_spacing {row_spacing} exceeds pen_width {pen_width}",
                )
            )
        if not _is_number(mask.get("snake_inset")):
            issues.append(
                _issue(
                    "snake_inset_missing",
                    "mask must declare the snake-row inset",
                )
            )
    verdict = "fail" if issues else "pass"
    return {
        "verdict": verdict,
        "ok": verdict == "pass",
        "issues": issues,
        "elements": elements_out,
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    report = check_whiteboard_elements(params.get("plan"))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "whiteboard_element_isolation_gate_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={
            "report_json": str(report_path),
            "ok": report["ok"],
        },
    )


def register_whiteboard_element_isolation_gate_capabilities_once() -> list[str]:
    """Register the gate on the unified registry (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.whiteboard_element_isolation_gate",
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
                "Whiteboard element isolation gate: every element binds one "
                "asset, reuse must declare a reason, and the mask invariants "
                "(row spacing no wider than the pen, snake-row inset "
                "declared) must hold. Plans are judged, never re-masked."
            ),
            line="qa",
        )
    )
    return ["qa.whiteboard_element_isolation_gate"]


register_whiteboard_element_isolation_gate_capabilities_once()
