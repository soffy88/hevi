"""Palette table contract (``video.palette_table_schema``).

Fake-level contract for a per-scene colour table of the
kind described in the Eian workflow review (see
``EIAN_WORKFLOW_ATTRIBUTION.md``): the palette is
designed before the first picture, every scene lists the
colours it uses, and the table is checked in black and
white — if figures cannot be told apart from the
background once the colour is gone, the contrast is wrong
and a regrade note must say so. The contract certifies
the shape of the table only. It draws nothing and renders
nothing: every compiled contract declares
``executed_here: false``.
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


def compile_palette_table(plan: Any) -> dict[str, Any]:
    """Compile one palette table contract.

    ``plan`` carries ``scenes`` (each with a scene name
    and a non-empty ``colors`` mapping) and ``bw_check``
    (readable flag plus a regrade note when unreadable).
    Raises :class:`CapabilityError` on any shape
    violation, on a scene without colours, or on an
    unreadable black-and-white check without a regrade
    note. The returned contract records that nothing was
    executed here.
    """
    if not isinstance(plan, dict):
        raise CapabilityError("palette table plan must be an object")
    if plan.get("executed_here") is True:
        raise CapabilityError(
            "palette execution claims are refused here; this contract executes nothing"
        )
    scenes = plan.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        raise CapabilityError("palette table needs a non-empty scenes list")
    for position, scene in enumerate(scenes):
        if not isinstance(scene, dict):
            raise CapabilityError(f"scene {position} must be an object")
        if not isinstance(scene.get("scene"), str) or not scene["scene"].strip():
            raise CapabilityError(f"scene {position} must name its scene")
        colors = scene.get("colors")
        if not isinstance(colors, dict) or not colors:
            raise CapabilityError(f"scene {position} needs a non-empty colors mapping")
        for element, color in colors.items():
            if not isinstance(color, str) or not color.strip():
                raise CapabilityError(
                    f"scene {position} colour for {element!r} must be a non-empty string"
                )
    bw_check = plan.get("bw_check")
    if not isinstance(bw_check, dict):
        raise CapabilityError("palette table needs a black-and-white check")
    if bw_check.get("readable") is False:
        note = bw_check.get("regrade_note")
        if not isinstance(note, str) or not note.strip():
            raise CapabilityError(
                "black-and-white check shows figures unreadable against "
                "the background, with no regrade note"
            )
    return {
        "contract": "palette-table",
        "scene_count": len(scenes),
        "scenes": [scene["scene"] for scene in scenes],
        "bw_readable": bool(bw_check.get("readable")),
        "executed_here": False,
        "output_file": None,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = compile_palette_table(params.get("plan"))
    report_path = out_dir / "palette_table_contract.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={
            "report_json": str(report_path),
            "scene_count": report["scene_count"],
            "executed_here": False,
        },
    )


def register_palette_table_schema_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="video.palette_table_schema",
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
                "Palette table contract (fake): per-scene colour "
                "tables designed before the first picture, checked in "
                "black and white with a regrade note when unreadable."
            ),
        )
    )
    return ["video.palette_table_schema"]


__all__ = [
    "compile_palette_table",
    "register_palette_table_schema_capabilities_once",
]
