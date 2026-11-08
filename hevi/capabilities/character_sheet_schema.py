"""Character sheet contract (``video.character_sheet_schema``).

Fake-level contract for a character design sheet of the
kind described in the Eian workflow review (see
``EIAN_WORKFLOW_ATTRIBUTION.md``): a character's look is
fixed before any shot is drawn, with a front view, a side
view, a set of expressions, and every fixed prop pinned
to a body position — a mark on the left arm stays on the
left arm in every picture. The contract carries text only
and holds no image assets. It certifies the shape of the
sheet only. It draws nothing and renders nothing: every
compiled contract declares ``executed_here: false``.
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

VIEWS: tuple[str, ...] = ("front", "side")


def compile_character_sheet(plan: Any) -> dict[str, Any]:
    """Compile one character sheet contract.

    ``plan`` carries ``character`` (name), ``views``
    (front and side), ``expressions`` (a non-empty list),
    and ``fixed_props`` (each with an item and a body
    position). Raises :class:`CapabilityError` on any
    shape violation, on a missing view or expression, on
    a fixed prop without a pinned position, or on any
    embedded image asset. The returned contract records
    that nothing was executed here.
    """
    if not isinstance(plan, dict):
        raise CapabilityError("character sheet plan must be an object")
    if plan.get("executed_here") is True:
        raise CapabilityError(
            "sheet execution claims are refused here; this contract executes nothing"
        )
    for key in ("image_file", "image_path", "image_url"):
        if key in plan:
            raise CapabilityError(
                "character sheets carry text only; image assets are not embedded here"
            )
    character = plan.get("character")
    if not isinstance(character, str) or not character.strip():
        raise CapabilityError("character sheet must name its character")
    views = plan.get("views")
    if not isinstance(views, dict):
        raise CapabilityError("character sheet needs a views object")
    for view in VIEWS:
        if not isinstance(views.get(view), str) or not views[view].strip():
            raise CapabilityError(f"character sheet is missing its {view} view")
    expressions = plan.get("expressions")
    if not isinstance(expressions, list) or not expressions:
        raise CapabilityError("character sheet needs a non-empty expressions list")
    for position, expression in enumerate(expressions):
        if not isinstance(expression, str) or not expression.strip():
            raise CapabilityError(f"expression {position} must be a non-empty string")
    fixed_props = plan.get("fixed_props")
    if not isinstance(fixed_props, list):
        raise CapabilityError("character sheet needs a fixed_props list")
    for position, prop in enumerate(fixed_props):
        if not isinstance(prop, dict):
            raise CapabilityError(f"fixed prop {position} must be an object")
        if not isinstance(prop.get("item"), str) or not prop["item"].strip():
            raise CapabilityError(f"fixed prop {position} must name its item")
        if not isinstance(prop.get("position"), str) or not prop["position"].strip():
            raise CapabilityError(f"fixed prop {position} must pin its body position")
    return {
        "contract": "character-sheet",
        "character": character,
        "views": list(VIEWS),
        "expression_count": len(expressions),
        "fixed_props": [
            {"item": prop["item"], "position": prop["position"]} for prop in fixed_props
        ],
        "executed_here": False,
        "output_file": None,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = compile_character_sheet(params.get("plan"))
    report_path = out_dir / "character_sheet_contract.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={
            "report_json": str(report_path),
            "character": report["character"],
            "executed_here": False,
        },
    )


def register_character_sheet_schema_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="video.character_sheet_schema",
            kind="video",
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
            layer="obase",
            description=(
                "Character sheet contract (fake): front and side views, "
                "expressions, fixed props pinned to body positions; "
                "text only, no image assets."
            ),
        )
    )
    return ["video.character_sheet_schema"]


__all__ = [
    "VIEWS",
    "compile_character_sheet",
    "register_character_sheet_schema_capabilities_once",
]
