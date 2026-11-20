"""Hybrid scene sync schema (``video.hybrid_scene_sync_schema``).

Fake-level contract for one hybrid scene: a Three.js scene,
an SVG overlay layer, and the sync table that binds them.
Each sync entry pairs a 3D point id with an SVG anchor id,
so the overlay can follow the scene. The contract certifies
the shape of the binding only. It executes no sync, moves
no label, and renders nothing: every compiled contract
declares ``executed_here: false`` and ``output_file: None``.

Clean-room restatement of the hybrid sync method (see
``AETHERVIZ_G4_G5_ATTRIBUTION.md``).
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


def _is_nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def compile_hybrid_scene_sync(plan: Any) -> dict[str, Any]:
    """Compile one hybrid scene sync contract.

    ``plan`` carries ``three_scene`` (``{id}``),
    ``svg_layer`` (``{id}``), and ``sync_table`` (a non-empty
    list of ``{point_id, anchor_id}``). Raises
    :class:`CapabilityError` on any shape violation. The
    returned contract records that nothing was executed here.
    """
    if not isinstance(plan, dict):
        raise CapabilityError("hybrid scene sync plan must be an object")
    if plan.get("executed_here") is True:
        raise CapabilityError("sync claims are refused here; this contract executes nothing")
    three_scene = plan.get("three_scene")
    if not isinstance(three_scene, dict) or not _is_nonempty_str(three_scene.get("id")):
        raise CapabilityError("three_scene must carry a non-empty id")
    svg_layer = plan.get("svg_layer")
    if not isinstance(svg_layer, dict) or not _is_nonempty_str(svg_layer.get("id")):
        raise CapabilityError("svg_layer must carry a non-empty id")
    sync_table = plan.get("sync_table")
    if not isinstance(sync_table, list) or not sync_table:
        raise CapabilityError("a non-empty sync_table is required")
    for index, entry in enumerate(sync_table):
        if not isinstance(entry, dict):
            raise CapabilityError(f"sync_table[{index}] must be an object")
        if not _is_nonempty_str(entry.get("point_id")):
            raise CapabilityError(f"sync_table[{index}] must carry a point_id")
        if not _is_nonempty_str(entry.get("anchor_id")):
            raise CapabilityError(f"sync_table[{index}] must carry an anchor_id")
    return {
        "contract": "hybrid-scene-sync",
        "three_scene_id": three_scene["id"],
        "svg_layer_id": svg_layer["id"],
        "sync_entries": len(sync_table),
        "executed_here": False,
        "output_file": None,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    contract = compile_hybrid_scene_sync(params.get("plan"))
    contract_path = out_dir / "hybrid_scene_sync_contract.json"
    contract_path.write_text(json.dumps(contract, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(contract_path),
        qa={
            "report_json": str(contract_path),
            "sync_entries": contract["sync_entries"],
            "executed_here": False,
        },
    )


def register_hybrid_scene_sync_schema_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="video.hybrid_scene_sync_schema",
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
                "hybrid scene sync contract (fake): Three.js scene "
                "plus SVG layer plus sync table binding 3D points to "
                "anchors; shape only, never executed here."
            ),
        )
    )
    return ["video.hybrid_scene_sync_schema"]


__all__ = [
    "compile_hybrid_scene_sync",
    "register_hybrid_scene_sync_schema_capabilities_once",
]
