"""Vinyl toy character schema (``video.vinyl_toy_character_schema``).

Fake-level contract for a vinyl toy character of the kind
described in the ChrisHKAI-Video creator-intro review (see
``CHRISHKAI_VIDEO_ATTRIBUTION.md``): one of the three kits
(parts list, pet, SDF sculpt), a parts list, colors, and a
size record. The contract certifies the shape of the plan
only. It builds no model and holds no image asset: any plan
carrying an image file, a toy file, or an avatar image, or
claiming a toy was built or rendered here, fails outright.
Every compiled contract declares ``executed_here: false``,
and real modelling is a separate case.
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

KITS: tuple[str, ...] = ("parts", "pet", "sdf")

# Fields that would carry an image asset; never allowed here.
ASSET_FIELDS: tuple[str, ...] = ("image_file", "toy_json", "avatar_image")


def compile_vinyl_toy_character(plan: Any) -> dict[str, Any]:
    """Compile one vinyl toy character contract.

    ``plan`` carries ``kit``, ``parts``, ``colors`` and
    ``size``. Raises :class:`CapabilityError` on any shape
    violation, on an unknown kit, on any embedded image
    asset, or on any claim that a toy was built or rendered
    here. The returned contract records that nothing was
    executed here.
    """
    if not isinstance(plan, dict):
        raise CapabilityError("Vinyl toy character plan must be an object")
    if plan.get("executed_here") is True or plan.get("rendered_here") is True:
        raise CapabilityError(
            "toy build/render claims are refused here; this contract executes nothing"
        )
    for field in ASSET_FIELDS:
        if field in plan:
            raise CapabilityError(
                f"image assets are never embedded in a toy plan; {field} is refused"
            )
    kit = plan.get("kit")
    if kit not in KITS:
        raise CapabilityError(
            "Vinyl toy character contract covers the three kits only: parts, pet, sdf"
        )
    parts = plan.get("parts")
    if not isinstance(parts, list) or not parts:
        raise CapabilityError("Vinyl toy character plan requires a non-empty parts list")
    colors = plan.get("colors")
    if not isinstance(colors, list) or not colors:
        raise CapabilityError("Vinyl toy character plan requires a colors list")
    size = plan.get("size")
    if not isinstance(size, dict) or not size:
        raise CapabilityError("Vinyl toy character plan requires a size record")
    return {
        "contract": "vinyl-toy-character",
        "kit": kit,
        "parts": list(parts),
        "colors": list(colors),
        "size": dict(size),
        "executed_here": False,
        "rendered_here": False,
        "output_file": None,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = compile_vinyl_toy_character(params.get("plan"))
    report_path = out_dir / "vinyl_toy_character_contract.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={
            "report_json": str(report_path),
            "kit": report["kit"],
            "executed_here": False,
        },
    )


def register_vinyl_toy_character_schema_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="video.vinyl_toy_character_schema",
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
                "Vinyl toy character contract (fake): one of three "
                "kits, parts list, colors, size; no image asset, no "
                "build, no render."
            ),
        )
    )
    return ["video.vinyl_toy_character_schema"]


__all__ = [
    "ASSET_FIELDS",
    "KITS",
    "compile_vinyl_toy_character",
    "register_vinyl_toy_character_schema_capabilities_once",
]
