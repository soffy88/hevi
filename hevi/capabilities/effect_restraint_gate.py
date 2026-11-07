"""Effect restraint gate (``qa.effect_restraint_gate``).

Clean-room rewrite of the restraint method in
``hevi-vs-oyasumi-gamedev.md`` item 5 (from the oyasumi-gamedev.com
manga-research series, restated in the report's own words):
effect lines and tone are not fixed symbols of an emotion. Each
serves a function in its own panel -- to gather the eye, to trace
a path, to carry light or texture or a mental background -- and
must be read together with the expression and the posture. Their
strength is set by four levers (thickness, density, extent, and
the white space left alone), not by piling on black. The check is
to turn the layer off: if the intent does not change, the effect
was not carrying anything. Each panel names one lead effect
first; anything more is decided against that lead.

This gate judges an effect plan -- records supplied by the
caller -- not pixels. It checks:

1. Every panel/shot names exactly one lead effect and states the
   function that effect serves in this panel. A fixed-emotion
   symbol (the caller declaring ``fixed_emotion_symbol: true``)
   fails.
2. An effect declared to overwhelm the face, the hands, or the
   dialogue order fails.
3. The layer-off check must be declared. An unchecked panel is
   ``not_checked`` for that sub-check, never passed. A checked
   panel whose intent does not change when the layer is off fails
   as redundant.
4. Caller-given thresholds (thickness / density / extent /
   whitespace, or any caller-named levers) are compared against
   caller-given measurements; exceeding one fails. A lever with
   no threshold is ``not_checked``, never passed.

No threshold or lever value in this module comes from the source
site: every number is caller-given. This module judges plans
only. It never generates, never calls a model, never touches a
budget.
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


def _issue(code: str, detail: str, **extra: Any) -> dict[str, Any]:
    issue = {"code": code, "detail": f"qa.effect_restraint_gate: {detail}"}
    issue.update(extra)
    return issue


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def check_effect_restraint(plan: Any) -> dict[str, Any]:
    """Judge one effect plan. Returns ``ok`` / ``verdict`` / ``issues``.

    ``plan`` is an object with ``items``: a list of objects with
    ``id``, ``lead_effect`` (a single name), ``effect_role`` (the
    function it serves in this panel), ``overwhelms_subject``
    (bool), ``layer_off_checked`` (bool),
    ``layer_off_changes_intent`` (bool, required when checked),
    optional ``fixed_emotion_symbol`` (bool), optional
    ``thresholds`` and ``measurements`` (caller-named levers mapped
    to numbers).
    """
    issues: list[dict[str, Any]] = []
    unchecked = False
    if not isinstance(plan, dict):
        return {
            "ok": False,
            "verdict": "fail",
            "issues": [_issue("plan_not_object", "effect plan must be an object")],
            "item_count": 0,
        }
    items = plan.get("items")
    if not isinstance(items, list) or not items:
        return {
            "ok": False,
            "verdict": "fail",
            "issues": [_issue("items_missing", "effect plan must list at least one item")],
            "item_count": 0,
        }
    for index, item in enumerate(items):
        where = f"item {index}"
        if not isinstance(item, dict):
            issues.append(_issue("item_not_object", f"{where} must be an object"))
            continue
        item_id = item.get("id")
        lead = item.get("lead_effect")
        if isinstance(lead, list):
            issues.append(
                _issue(
                    "multiple_lead_effects",
                    f"{where} must name exactly one lead effect, got a list",
                    item_id=item_id,
                )
            )
        elif not isinstance(lead, str) or not lead.strip():
            issues.append(
                _issue(
                    "lead_effect_missing",
                    f"{where} must name exactly one lead effect",
                    item_id=item_id,
                )
            )
        role = item.get("effect_role")
        if not isinstance(role, str) or not role.strip():
            issues.append(
                _issue(
                    "effect_role_missing",
                    f"{where} must state the function the lead effect "
                    "serves in this panel",
                    item_id=item_id,
                )
            )
        if item.get("fixed_emotion_symbol") is True:
            issues.append(
                _issue(
                    "fixed_emotion_symbol",
                    f"{where} uses the effect as a fixed symbol of an "
                    "emotion; effects serve a function in their panel "
                    "and are read with expression and posture",
                    item_id=item_id,
                )
            )
        if item.get("overwhelms_subject") is True:
            issues.append(
                _issue(
                    "effect_overwhelms_subject",
                    f"{where} effect overwhelms the face, the hands, or "
                    "the dialogue order",
                    item_id=item_id,
                )
            )
        checked = item.get("layer_off_checked")
        if checked is True:
            changes = item.get("layer_off_changes_intent")
            if changes is False:
                issues.append(
                    _issue(
                        "effect_redundant",
                        f"{where} turning the effect layer off does not "
                        "change the intent; the effect carries nothing",
                        item_id=item_id,
                    )
                )
            elif changes is not True:
                issues.append(
                    _issue(
                        "layer_off_result_missing",
                        f"{where} layer_off_checked is true but "
                        "layer_off_changes_intent is not a boolean",
                        item_id=item_id,
                    )
                )
        else:
            unchecked = True
        thresholds = item.get("thresholds")
        measurements = item.get("measurements")
        if isinstance(thresholds, dict) and isinstance(measurements, dict):
            for lever, limit in thresholds.items():
                if not _is_number(limit):
                    continue
                measured = measurements.get(lever)
                if _is_number(measured) and measured > limit:
                    issues.append(
                        _issue(
                            "effect_over_threshold",
                            f"{where} lever {lever!r} measures {measured} "
                            f"over the caller-given threshold {limit}",
                            item_id=item_id,
                            lever=lever,
                        )
                    )
        elif isinstance(measurements, dict) and measurements:
            unchecked = True
    if issues:
        verdict = "fail"
    elif unchecked:
        verdict = "not_checked"
        issues.append(
            _issue(
                "effect_check_undeclared",
                "at least one item lacks a layer-off check or a "
                "threshold; those sub-checks are not_checked, never "
                "counted as passed",
            )
        )
    else:
        verdict = "pass"
    return {
        "ok": verdict == "pass",
        "verdict": verdict,
        "issues": issues,
        "item_count": len(items),
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_effect_restraint(params.get("plan"))
    report_path = out_dir / "effect_restraint_gate.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_effect_restraint_gate_capabilities_once() -> list[str]:
    """Register ``qa.effect_restraint_gate`` on the registry (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.effect_restraint_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {"plan": {"type": "object"}},
                "required": ["plan"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Effect restraint gate: one lead effect per panel with a "
                "stated function, no fixed emotion symbols, no effect "
                "overwhelming face/hands/dialogue, a declared layer-off "
                "check, and caller-given thresholds. Unchecked items are "
                "not_checked, never passed. Judges plans only."
            ),
            line="qa",
        )
    )
    return ["qa.effect_restraint_gate"]


register_effect_restraint_gate_capabilities_once()
