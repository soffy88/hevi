"""Konva interactive stage gate (``qa.konva_interactive_stage_gate``).

Clean-room restatement of the konvajs/konva method (see
``ANIMATION_STUDIO_18_ATTRIBUTION.md``); no upstream code
appears here. Konva is the interactive Canvas stage hevi
lacked: layers in an explicit order, and interactions
(drag, select, transform, draw, erase) that must all be
reversible, with the exported result consistent with the
stage. It complements hevi's canvas workbench
(canvas_workflow/comfy_executor), which runs jobs; this
gate owns the editable stage itself. A stage with unordered
layers, an irreversible interaction, or an export that does
not match the stage fails.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

INTERACTION_TYPES = ("drag", "select", "transform", "draw", "erase")


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def check_konva_interactive_stage(stage: Any) -> dict[str, Any]:
    """Validate a Konva-style interactive Canvas stage.

    Verdicts are ``pass`` / ``fail`` only. A stage fails when
    it is not an object, when the layer list is empty, when
    layer orders are not exactly 0..n-1, when a layer lacks a
    name, when an interaction type is outside the closed
    vocabulary, when an interaction is not reversible, or
    when the export is not declared consistent with the stage.
    """
    issues: list[dict[str, Any]] = []

    def fail(code: str, detail: str) -> dict[str, Any]:
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [*issues, _issue(code, detail)],
            "executed_here": False,
        }

    if not isinstance(stage, dict):
        return fail("stage_not_object", "interactive stage must be a JSON object")
    layers = stage.get("layers")
    if not isinstance(layers, list) or not layers:
        return fail("layers_empty", "interactive stage needs at least one layer")
    orders = []
    for layer in layers:
        if not isinstance(layer, dict):
            return fail("layer_not_object", "each layer must be an object")
        if not isinstance(layer.get("name"), str) or not layer["name"]:
            return fail("layer_name_missing", "each layer needs a non-empty name")
        order = layer.get("order")
        if not isinstance(order, int) or isinstance(order, bool):
            return fail(
                "layer_order_not_int",
                f"layer {layer.get('name')!r} needs an integer order",
            )
        orders.append(order)
    if sorted(orders) != list(range(len(layers))):
        return fail(
            "layer_order_not_sequential",
            f"layer orders must be exactly 0..{len(layers) - 1}, got {sorted(orders)}",
        )
    interactions = stage.get("interactions", [])
    if not isinstance(interactions, list):
        return fail("interactions_not_list", "interactions must be a list")
    for interaction in interactions:
        if not isinstance(interaction, dict):
            return fail("interaction_not_object", "each interaction must be an object")
        if interaction.get("type") not in INTERACTION_TYPES:
            return fail(
                "interaction_type_unknown",
                f"interaction type {interaction.get('type')!r} is outside "
                f"the closed vocabulary {INTERACTION_TYPES}",
            )
        if interaction.get("reversible") is not True:
            return fail(
                "interaction_not_reversible",
                f"interaction {interaction.get('type')!r} must declare "
                "reversible true; every stage edit must be undoable",
            )
    if stage.get("export_consistent_with_stage") is not True:
        return fail(
            "export_not_consistent",
            "the export must be declared consistent with the stage",
        )
    return {
        "verdict": "pass",
        "ok": True,
        "issues": [],
        "executed_here": False,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_konva_interactive_stage(params.get("stage"))
    report_path = out_dir / "konva_interactive_stage_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_konva_interactive_stage_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.konva_interactive_stage_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "stage": {"type": "object"},
                },
                "required": ["stage"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="oskill",
            description=(
                "Konva interactive stage gate: layers ordered exactly "
                "0..n-1, every interaction from a closed vocabulary and "
                "reversible, the export declared consistent with the stage."
            ),
        )
    )
    return ["qa.konva_interactive_stage_gate"]


__all__ = [
    "INTERACTION_TYPES",
    "check_konva_interactive_stage",
    "register_konva_interactive_stage_gate_capabilities_once",
]
