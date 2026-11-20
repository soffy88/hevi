"""Two.js vector scene gate (``qa.twojs_vector_scene_gate``).

Clean-room restatement of the jonobr1/two.js method (see
``ANIMATION_STUDIO_18_ATTRIBUTION.md``); no upstream code
appears here. Two.js is a renderer-agnostic 2D vector scene
graph: one scene, one declared backend (SVG, Canvas, or
WebGL), layers in an explicit order, and vector elements
that must be serializable. It sits below hevi's handpaint
(brush strokes) and stickman (stick figures) lines: those
draw pictures, this one owns the scene graph. A scene that
does not declare its backend, has unordered or duplicated
layer orders, uses an element type outside the closed
vocabulary, or carries a non-serializable element fails.
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

BACKENDS = ("svg", "canvas", "webgl")
ELEMENT_TYPES = (
    "circle",
    "rect",
    "path",
    "line",
    "ellipse",
    "polygon",
    "text",
    "group",
)


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def check_twojs_vector_scene(scene: Any) -> dict[str, Any]:
    """Validate a Two.js-style 2D vector scene graph.

    Verdicts are ``pass`` / ``fail`` only. A scene fails when
    it is not an object, when its backend is not svg, canvas,
    or webgl, when the layer list is empty, when layer orders
    are not exactly 0..n-1, when a layer lacks a name or an
    element list, when an element type is outside the closed
    vocabulary, or when an element is not serializable.
    """
    issues: list[dict[str, Any]] = []

    def fail(code: str, detail: str) -> dict[str, Any]:
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [*issues, _issue(code, detail)],
            "executed_here": False,
        }

    if not isinstance(scene, dict):
        return fail("scene_not_object", "vector scene must be a JSON object")
    backend = scene.get("backend")
    if backend not in BACKENDS:
        return fail(
            "backend_not_declared",
            f"backend must be one of {BACKENDS}, got {backend!r}",
        )
    layers = scene.get("layers")
    if not isinstance(layers, list) or not layers:
        return fail("layers_empty", "vector scene needs at least one layer")
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
        elements = layer.get("elements")
        if not isinstance(elements, list):
            return fail(
                "layer_elements_missing",
                f"layer {layer['name']!r} needs an elements list",
            )
        for element in elements:
            if not isinstance(element, dict):
                return fail("element_not_object", "each element must be an object")
            if element.get("type") not in ELEMENT_TYPES:
                return fail(
                    "element_type_unknown",
                    f"element type {element.get('type')!r} is outside the "
                    f"closed vocabulary {ELEMENT_TYPES}",
                )
            if element.get("serializable") is not True:
                return fail(
                    "element_not_serializable",
                    f"element {element.get('type')!r} in layer "
                    f"{layer['name']!r} must declare serializable true",
                )
    if sorted(orders) != list(range(len(layers))):
        return fail(
            "layer_order_not_sequential",
            f"layer orders must be exactly 0..{len(layers) - 1}, got {sorted(orders)}",
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
    report = check_twojs_vector_scene(params.get("scene"))
    report_path = out_dir / "twojs_vector_scene_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_twojs_vector_scene_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.twojs_vector_scene_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "scene": {"type": "object"},
                },
                "required": ["scene"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="oskill",
            description=(
                "Two.js vector scene gate: one declared backend (svg, "
                "canvas, or webgl), layers ordered exactly 0..n-1, "
                "elements from a closed vocabulary, every element serializable."
            ),
        )
    )
    return ["qa.twojs_vector_scene_gate"]


__all__ = [
    "BACKENDS",
    "ELEMENT_TYPES",
    "check_twojs_vector_scene",
    "register_twojs_vector_scene_gate_capabilities_once",
]
