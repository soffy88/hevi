"""SVG 3D overlay schema (``video.svg3d_overlay_schema``).

Fake-level contract for one SVG overlay layer anchored to
3D points: its anchor labels, its viewBox, and its pointer
behaviour. The overlay never intercepts pointer input
(``pointer-events: none``), so the 3D canvas below keeps
receiving it. The contract certifies the shape of the layer
only. It renders nothing and projects no point: every
compiled contract declares ``executed_here: false`` and
``output_file: None``.

Clean-room restatement of the overlay method (see
``AETHERVIZ_G4_G5_ATTRIBUTION.md``). This fills the Atlas
label-overlay gap (``physics.atlas_figure`` pending item 3):
the labels Atlas only declares are anchored here, as a
contract, not as pixels.
"""

from __future__ import annotations

import json
import re
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

_VIEWBOX_RE = re.compile(r"^0 0 (\d+(?:\.\d+)?) (\d+(?:\.\d+)?)$")


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _normalize_view_box(view_box: Any) -> dict[str, float]:
    """Normalize a viewBox dict or "0 0 W H" string to {width, height}."""
    if isinstance(view_box, dict):
        width = view_box.get("width")
        height = view_box.get("height")
        if _is_number(width) and _is_number(height) and width > 0 and height > 0:
            return {"width": float(width), "height": float(height)}
        raise CapabilityError("view_box must carry positive width and height")
    if isinstance(view_box, str):
        match = _VIEWBOX_RE.match(view_box.strip())
        if match:
            return {
                "width": float(match.group(1)),
                "height": float(match.group(2)),
            }
        raise CapabilityError("view_box string must look like '0 0 W H'")
    raise CapabilityError("view_box must be an object or a '0 0 W H' string")


def compile_svg3d_overlay(plan: Any) -> dict[str, Any]:
    """Compile one SVG 3D overlay contract.

    ``plan`` carries ``anchors`` (a non-empty list of
    ``{label, point}``; each label a non-empty string, each
    point a [x, y, z] number triple), ``view_box`` (``{width,
    height}`` or a ``"0 0 W H"`` string), and
    ``pointer_events`` (which must be ``"none"``). Raises
    :class:`CapabilityError` on any shape violation. The
    returned contract records that nothing was executed here.
    """
    if not isinstance(plan, dict):
        raise CapabilityError("svg3d overlay plan must be an object")
    if plan.get("executed_here") is True:
        raise CapabilityError("overlay claims are refused here; this contract renders nothing")
    anchors = plan.get("anchors")
    if not isinstance(anchors, list) or not anchors:
        raise CapabilityError("a non-empty anchors list is required")
    clean_anchors: list[dict[str, Any]] = []
    for index, anchor in enumerate(anchors):
        if not isinstance(anchor, dict):
            raise CapabilityError(f"anchors[{index}] must be an object")
        label = anchor.get("label")
        if not isinstance(label, str) or not label.strip():
            raise CapabilityError(f"anchors[{index}] must carry a non-empty label")
        point = anchor.get("point")
        if not isinstance(point, list) or len(point) != 3 or not all(_is_number(v) for v in point):
            raise CapabilityError(f"anchors[{index}] point must be [x, y, z] numbers")
        clean_anchors.append({"label": label, "point": list(point)})
    view_box = _normalize_view_box(plan.get("view_box"))
    if plan.get("pointer_events") != "none":
        raise CapabilityError("pointer_events must be 'none': the overlay never takes input")
    return {
        "contract": "svg3d-overlay",
        "anchors": clean_anchors,
        "view_box": view_box,
        "pointer_events": "none",
        "executed_here": False,
        "output_file": None,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    contract = compile_svg3d_overlay(params.get("plan"))
    contract_path = out_dir / "svg3d_overlay_contract.json"
    contract_path.write_text(json.dumps(contract, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(contract_path),
        qa={
            "report_json": str(contract_path),
            "anchors": len(contract["anchors"]),
            "executed_here": False,
        },
    )


def register_svg3d_overlay_schema_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="video.svg3d_overlay_schema",
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
            line="video",
            description=(
                "SVG 3D overlay contract (fake): anchor labels on 3D "
                "points, viewBox, pointer-events none; shape only, "
                "never executed here."
            ),
        )
    )
    return ["video.svg3d_overlay_schema"]


__all__ = [
    "compile_svg3d_overlay",
    "register_svg3d_overlay_schema_capabilities_once",
]
