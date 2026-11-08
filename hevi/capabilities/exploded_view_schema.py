"""Exploded-view schema, fake layer (``video.exploded_view_schema``).

Contract-only schema. Given an exploded-view plan it compiles
the contract for a flat, layered object drawn with its layers
lifted apart: the ordered layer list, each layer's anchor and
leader line, and the label text limits. This module executes
nothing: ``executed_here`` is always false, ``rendered_here``
is always false, and ``output_file`` is always null. No pixels
are produced here and no model is loaded; real exploded-view
rendering is a separate case. See
ANIMATION_SKILLS_ATTRIBUTION.md.
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

MAX_LAYERS = 6
MAX_NAME_CHARS = 16
MAX_NOTE_CHARS = 22


def _fail(message: str) -> None:
    raise CapabilityError(message)


def compile_exploded_view_contract(plan: Any) -> dict[str, Any]:
    """Compile an exploded-view contract from a plan.

    Raises :class:`CapabilityError` on a malformed plan. The
    returned contract always carries ``executed_here: false``,
    ``rendered_here: false``, and ``output_file: null``:
    nothing is drawn here.
    """
    if not isinstance(plan, dict):
        _fail("exploded-view plan must be a JSON object")
    if plan.get("flat_layered_object") is not True:
        _fail("only flat, layered objects qualify for an exploded view")
    object_kind = plan.get("object_kind")
    if not isinstance(object_kind, str) or not object_kind.strip():
        _fail("exploded-view plan must name an object_kind")
    layers = plan.get("layers")
    if not isinstance(layers, list) or not layers:
        _fail("exploded-view plan must declare a non-empty layers list")
    if len(layers) > MAX_LAYERS:
        _fail(f"at most {MAX_LAYERS} layers may be labelled")
    layers_out: list[dict[str, Any]] = []
    for index, layer in enumerate(layers):
        if not isinstance(layer, dict):
            _fail(f"layers[{index}] must be an object")
        if layer.get("order") != index + 1:
            _fail("layer order must run 1..n top to bottom")
        name = layer.get("name")
        if not isinstance(name, str) or not name.strip():
            _fail(f"layers[{index}] must name itself")
        if len(name) > MAX_NAME_CHARS:
            _fail(f"layers[{index}] name exceeds {MAX_NAME_CHARS} characters")
        note = layer.get("note")
        if not isinstance(note, str) or not note.strip():
            _fail(f"layers[{index}] must carry a note")
        if len(note) > MAX_NOTE_CHARS:
            _fail(f"layers[{index}] note exceeds {MAX_NOTE_CHARS} characters")
        anchor = layer.get("anchor")
        if not isinstance(anchor, dict) or "x" not in anchor or "y" not in anchor:
            _fail(f"layers[{index}] must declare an anchor point")
        if layer.get("leader_line") is not True:
            _fail(f"layers[{index}] must declare a leader line to its label")
        layers_out.append(
            {
                "order": index + 1,
                "name": name,
                "note": note,
                "anchor": {"x": anchor["x"], "y": anchor["y"]},
                "leader_line": True,
            }
        )
    canvas = plan.get("canvas", {"width": 1080, "height": 1920})
    return {
        "object_kind": object_kind,
        "layers": layers_out,
        "layer_count": len(layers_out),
        "canvas": canvas,
        "executed_here": False,
        "rendered_here": False,
        "output_file": None,
        "render_required": "separate case; no rendering here",
    }


def _render(params: dict[str, Any], out_dir: Any, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    contract = compile_exploded_view_contract(params.get("plan"))
    contract_path = out_dir / "exploded_view_contract.json"
    contract_path.write_text(
        json.dumps(contract, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(contract_path),
        qa={"contract_json": str(contract_path), "executed_here": False},
    )


def register_exploded_view_schema_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="video.exploded_view_schema",
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
                "Exploded-view schema (contract only): ordered "
                "layers with anchors, leader lines, and label "
                "limits for a flat, layered object; nothing is "
                "rendered here."
            ),
        )
    )
    return ["video.exploded_view_schema"]


__all__ = [
    "compile_exploded_view_contract",
    "register_exploded_view_schema_capabilities_once",
]
