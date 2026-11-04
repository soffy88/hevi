"""Code-render mapping contract (``video.camera_render_mapping``).

Contract-only mapping from the 46-movement camera catalogue to
the minimal code renderer (``video.minimal_stage_render``).
The renderer implements exactly four fixed movement tokens
(``static`` / ``orbit`` / ``dolly`` / ``pan``), each a single
fixed sweep with no direction parameter and no focal-length
control. This mapping therefore supports exactly four
catalogue ids, one per token, and marks the other 42
explicitly ``not_supported`` with a reason. There is no silent
fallback: compiling a plan for a ``not_supported`` movement
fails closed, and a caller-supplied renderer token that does
not match the mapped token fails too. The four supported
entries carry ``direction_verified: false``: routing to a
token is recorded, but whether the renderer's fixed sweep
matches the physical direction of the movement was not
verified and is a separate case. Nothing is rendered here:
``executed_here`` is always false. The 124 shotcraft cards are
a different library; shared generic words take their meaning
here from the physical camera definition. ``slow_zoom_in`` and
``slow_zoom_out`` are legal vocabulary ids; they are simply
not renderable by this renderer (zoom family, no
focal-length control), never banned ids. See
CAMERA_MOVEMENTS_ATTRIBUTION.md.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hevi.capabilities.cinematic_techniques import load_movements
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

# One catalogue id per renderer token. Opposite directions are
# deliberately NOT mirrored: the renderer has no direction
# parameter, so mirroring would be a silent behaviour change.
_SUPPORTED: dict[str, str] = {
    "static_shot": "static",
    "orbit_clockwise": "orbit",
    "dolly_in": "dolly",
    "pan_right": "pan",
}

# Opposite-direction ids of the four implemented sweeps. They
# are not_supported for direction, not for family.
_DIRECTION_VARIANTS: frozenset[str] = frozenset(
    {
        "pan_left",
        "orbit_counterclockwise",
        "dolly_out",
    }
)


def _reason(movement: dict[str, Any]) -> str:
    movement_id = movement["id"]
    if movement_id in _SUPPORTED:
        return "routes to the renderer's fixed sweep for this token"
    category = movement.get("category", "")
    if category == "Zoom/Lens":
        return (
            "renderer has no focal-length control; a zoom is not "
            "a dolly move and cannot be rendered by translating "
            "the camera"
        )
    if movement_id in _DIRECTION_VARIANTS:
        return (
            "opposite direction of the one fixed sweep the "
            "renderer implements; no silent mirroring"
        )
    if category == "Specials":
        return (
            "composite, time-class, or lens effect, not a single "
            "physical camera move the minimal renderer implements"
        )
    return (
        "movement family not implemented by the minimal "
        "renderer (static/orbit/dolly/pan tokens only)"
    )


def list_render_mapping() -> list[dict[str, Any]]:
    """Return the full 46-entry mapping (copies, catalogue order)."""
    entries: list[dict[str, Any]] = []
    for movement in load_movements():
        movement_id = movement["id"]
        supported = movement_id in _SUPPORTED
        entries.append(
            {
                "id": movement_id,
                "name_en": movement.get("name_en"),
                "name_zh": movement.get("name_zh"),
                "category": movement.get("category"),
                "status": "supported" if supported else "not_supported",
                "renderer_movement": _SUPPORTED.get(movement_id),
                "reason": _reason(movement),
                # Routing only; sweep direction match unverified.
                "direction_verified": False,
                # Never a fallback token: null unless supported.
                "fallback": None,
            }
        )
    return entries


def map_movement(movement_id: Any) -> dict[str, Any]:
    """Return the mapping entry for one movement id.

    Raises :class:`CapabilityError` for an unknown id.
    """
    if not isinstance(movement_id, str):
        raise CapabilityError("movement id must be a string")
    for entry in list_render_mapping():
        if entry["id"] == movement_id:
            return entry
    raise CapabilityError(f"unknown camera movement id {movement_id!r}")


def compile_render_mapping(plan: Any) -> dict[str, Any]:
    """Compile a render-mapping contract from a plan.

    Raises :class:`CapabilityError` when the movement is
    ``not_supported`` or when a caller-supplied renderer token
    disagrees with the mapped token. No silent fallback is ever
    returned. The contract always carries
    ``executed_here: false`` and ``output_file: null``.
    """
    if not isinstance(plan, dict):
        raise CapabilityError("render mapping plan must be a JSON object")
    entry = map_movement(plan.get("movement_id"))
    if entry["status"] != "supported":
        raise CapabilityError(
            f"movement {entry['id']!r} is not_supported by the "
            f"minimal renderer: {entry['reason']}; no fallback "
            "is applied"
        )
    token = plan.get("renderer_movement")
    if token is not None and token != entry["renderer_movement"]:
        raise CapabilityError(
            f"renderer_movement {token!r} disagrees with the mapped "
            f"token {entry['renderer_movement']!r} for "
            f"{entry['id']!r}; overrides are refused"
        )
    return {
        "movement_id": entry["id"],
        "name_en": entry["name_en"],
        "name_zh": entry["name_zh"],
        "category": entry["category"],
        "status": "supported",
        "renderer_movement": entry["renderer_movement"],
        "direction_verified": False,
        "fallback": None,
        "executed_here": False,
        "rendered_here": False,
        "output_file": None,
        "render_required": "separate case; direction match of the "
        "fixed sweep against the physical definition is unverified",
    }


def _render(params: dict[str, Any], out_dir: Any, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    contract = compile_render_mapping(params.get("plan"))
    contract_path = out_dir / "camera_render_mapping.json"
    contract_path.write_text(
        json.dumps(contract, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(contract_path),
        qa={"contract_json": str(contract_path), "executed_here": False},
    )


def register_camera_render_mapping_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="video.camera_render_mapping",
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
            layer="obase",
            description=(
                "Camera render mapping (contract only): the "
                "46-movement catalogue mapped to the minimal "
                "renderer tokens; 42 movements are explicitly "
                "not_supported with reasons, never silently "
                "fallen back."
            ),
        )
    )
    return ["video.camera_render_mapping"]


__all__ = [
    "compile_render_mapping",
    "list_render_mapping",
    "map_movement",
    "register_camera_render_mapping_capabilities_once",
]
