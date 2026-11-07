"""Text/image consistency gate (``qa.text_image_consistency_gate``).

Clean-room rewrite of the method in ``hevi-vs-rain-before-stops.md``
item A2 (from the ``<雨停之前>`` field notes): the scene card's
written assertions and the setting picture's depicted inventory
must not contradict each other. The field case: the setting
picture showed a window while the written card said there was no
window there, and generation then could not stay stable. This gate
compares the two lists item by item -- element presence and, when
both sides state one, position -- and fails on any contradiction,
naming the element.

Inputs are caller-supplied descriptions, not pixels: the gate
judges the *records* (what the card asserts vs what the picture
inventory lists). It cannot see a picture; a caller who lists an
element the picture does not actually show has lied to the gate,
and no gate can catch that. What it does catch is the record-level
contradiction, before money is spent.

This module judges records only. It never generates, never calls a
model, never touches a budget.
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
    issue = {"code": code, "detail": f"qa.text_image_consistency_gate: {detail}"}
    issue.update(extra)
    return issue


def _normalise_position(position: Any) -> str | None:
    if position is None:
        return None
    if not isinstance(position, str) or not position.strip():
        return None
    return " ".join(position.strip().split())


def _check_assertion(assertion: Any, inventory: dict[str, Any],
                     issues: list[dict[str, Any]]) -> None:
    if not isinstance(assertion, dict):
        issues.append(_issue("assertion_not_object", "each text assertion must be an object"))
        return
    element = assertion.get("element")
    if not isinstance(element, str) or not element.strip():
        issues.append(_issue("assertion_missing_element", "each text assertion must name an element"))
        return
    present = assertion.get("present")
    if not isinstance(present, bool):
        issues.append(_issue(
            "assertion_missing_present",
            f"assertion for {element!r} must state present as true/false",
            element=element,
        ))
        return
    depicted = inventory.get(element)
    if depicted is None:
        issues.append(_issue(
            "element_missing_from_inventory",
            f"element {element!r} is asserted in text but absent from the picture inventory; "
            "list it before judging",
            element=element,
        ))
        return
    if not isinstance(depicted, dict) or not isinstance(depicted.get("present"), bool):
        issues.append(_issue(
            "inventory_entry_invalid",
            f"inventory entry for {element!r} must state present as true/false",
            element=element,
        ))
        return
    if depicted["present"] != present:
        issues.append(_issue(
            "presence_conflict",
            f"element {element!r}: text says present={present}, "
            f"picture inventory says present={depicted['present']}",
            element=element,
        ))
        return
    text_position = _normalise_position(assertion.get("position"))
    depicted_position = _normalise_position(depicted.get("position"))
    if (
        text_position is not None
        and depicted_position is not None
        and text_position != depicted_position
    ):
        issues.append(_issue(
            "position_conflict",
            f"element {element!r}: text position {text_position!r} != "
            f"picture position {depicted_position!r}",
            element=element,
        ))


def check_text_image_consistency(scene_card: Any, image_inventory: Any) -> dict[str, Any]:
    """Judge text assertions against a picture inventory. Never raises for bad input."""
    issues: list[dict[str, Any]] = []
    if not isinstance(scene_card, dict):
        return {
            "ok": False,
            "verdict": "fail",
            "issues": [_issue("scene_card_not_object", "scene card must be an object")],
        }
    if not isinstance(image_inventory, dict):
        return {
            "ok": False,
            "verdict": "fail",
            "issues": [_issue("inventory_not_object", "picture inventory must be an object")],
        }
    assertions = scene_card.get("assertions")
    if not isinstance(assertions, list) or not assertions:
        issues.append(_issue(
            "assertions_missing",
            "scene card must carry a non-empty assertions list",
        ))
        return {"ok": False, "verdict": "fail", "issues": issues}
    elements = image_inventory.get("elements")
    if not isinstance(elements, list):
        issues.append(_issue(
            "inventory_elements_missing",
            "picture inventory must carry an elements list",
        ))
        return {"ok": False, "verdict": "fail", "issues": issues}
    inventory: dict[str, Any] = {}
    for entry in elements:
        if isinstance(entry, dict) and isinstance(entry.get("element"), str):
            inventory[entry["element"]] = entry
        else:
            issues.append(_issue(
                "inventory_entry_invalid",
                "each inventory entry must be an object naming an element",
            ))
    for assertion in assertions:
        _check_assertion(assertion, inventory, issues)
    return {
        "ok": not issues,
        "verdict": "pass" if not issues else "fail",
        "checked_elements": sorted(inventory),
        "issues": issues,
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            **_kwargs: Any) -> CapabilityResult:
    report = check_text_image_consistency(
        params.get("scene_card"), params.get("image_inventory")
    )
    report_path = Path(out_dir) / "text_image_consistency_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_text_image_consistency_gate_capabilities_once() -> list[str]:
    """Register ``qa.text_image_consistency_gate`` on the unified registry (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.text_image_consistency_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "scene_card": {"type": "object"},
                    "image_inventory": {"type": "object"},
                },
                "required": ["scene_card", "image_inventory"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Text/image consistency gate: the scene card's written "
                "assertions (presence and position of doors, windows, "
                "counters, lamps, key props) must not contradict the "
                "setting picture's inventory; a window the text says "
                "is absent fails. Judges records only; no generation."
            ),
            line="qa",
        )
    )
    return ["qa.text_image_consistency_gate"]


register_text_image_consistency_gate_capabilities_once()
