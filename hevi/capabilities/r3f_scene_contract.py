"""React Three Fiber scene contract, fake layer (``video.r3f_scene_contract``).

Contract-only adapter. Given a declared scene plan it
compiles the contract for a React Three Fiber scene: a
canvas, a camera, and a list of primitive shapes, under a
renderer declaration that must pass the variant gate
(``qa.r3f_variant_gate``). This module builds nothing and
renders nothing: ``executed_here`` is always false,
``rendered_here`` is always false, and ``output_file`` is
always null. No React build chain exists here and no scene
is rendered; real rendering is a separate real-machine
case. See FIFTEEN_TOOLS_ATTRIBUTION.md.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.r3f_variant_gate import check_r3f_variant
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

# Primitive shapes this contract recognizes, in our own
# vocabulary: the common solid and surface forms.
PRIMITIVE_TYPES = ("box", "sphere", "plane", "cylinder", "torus", "cone")


def _fail(message: str) -> None:
    raise CapabilityError(message)


def _vector3(value: Any, label: str) -> list[float]:
    if (
        not isinstance(value, list)
        or len(value) != 3
        or any(
            not isinstance(component, (int, float))
            or isinstance(component, bool)
            for component in value
        )
    ):
        _fail(f"{label} must be a list of three numbers")
    return [float(component) for component in value]


def compile_r3f_scene_contract(plan: Any) -> dict[str, Any]:
    """Compile a React Three Fiber scene contract from a plan.

    Raises :class:`CapabilityError` on a malformed plan. The
    returned contract always carries ``executed_here: false``,
    ``rendered_here: false``, and ``output_file: null``:
    nothing is built or rendered here.
    """
    if not isinstance(plan, dict):
        _fail("scene plan must be a JSON object")
    renderer_report = check_r3f_variant(plan.get("renderer"))
    if renderer_report["verdict"] != "pass":
        first = renderer_report["issues"][0] if renderer_report["issues"] else {}
        _fail(
            "renderer declaration failed the variant gate: "
            + str(first.get("detail", first.get("code", "unknown")))
        )
    canvas = plan.get("canvas")
    if not isinstance(canvas, dict):
        _fail("scene plan must declare a canvas object")
    for field in ("width", "height"):
        value = canvas.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            _fail(f"canvas must declare a positive integer {field}")
    camera = plan.get("camera")
    if not isinstance(camera, dict):
        _fail("scene plan must declare a camera object")
    position = _vector3(camera.get("position"), "camera position")
    fov = camera.get("fov")
    if not isinstance(fov, (int, float)) or isinstance(fov, bool) or fov <= 0:
        _fail("camera must declare a positive fov")
    primitives = plan.get("primitives")
    if not isinstance(primitives, list) or not primitives:
        _fail("scene plan must declare a non-empty primitives list")
    compiled: list[dict[str, Any]] = []
    for index, primitive in enumerate(primitives):
        if not isinstance(primitive, dict):
            _fail(f"primitives[{index}] must be an object")
        primitive_id = primitive.get("id")
        if not isinstance(primitive_id, str) or not primitive_id:
            _fail(f"primitives[{index}] must declare an id")
        primitive_type = primitive.get("type")
        if primitive_type not in PRIMITIVE_TYPES:
            _fail(
                f"primitives[{index}] type must be one of "
                + ", ".join(PRIMITIVE_TYPES)
            )
        entry: dict[str, Any] = {
            "index": index,
            "id": primitive_id,
            "type": primitive_type,
            "position": _vector3(
                primitive.get("position"), f"primitives[{index}] position"
            ),
        }
        if primitive.get("scale") is not None:
            scale = _vector3(
                primitive.get("scale"), f"primitives[{index}] scale"
            )
            if any(component <= 0 for component in scale):
                _fail(f"primitives[{index}] scale components must be positive")
            entry["scale"] = scale
        if primitive.get("color") is not None:
            color = primitive.get("color")
            if not isinstance(color, str) or not color:
                _fail(f"primitives[{index}] color must be a non-empty string")
            entry["color"] = color
        compiled.append(entry)
    return {
        "contract": "r3f_scene",
        "renderer": plan["renderer"],
        "canvas": {"width": canvas["width"], "height": canvas["height"]},
        "camera": {"position": position, "fov": fov},
        "primitives": compiled,
        "executed_here": False,
        "rendered_here": False,
        "output_file": None,
        "react_build": "real_machine_case",
        "render_bridge": "real_machine_case",
    }


def _render(params: dict[str, Any], out_dir: Any, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    contract = compile_r3f_scene_contract(params.get("plan"))
    contract_path = out_dir / "r3f_scene_contract.json"
    contract_path.write_text(
        json.dumps(contract, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(contract_path),
        qa={"contract_json": str(contract_path), "executed_here": False},
    )


def register_r3f_scene_contract_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="video.r3f_scene_contract",
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
                "React Three Fiber scene contract, fake layer: "
                "compiles a canvas/camera/primitives contract under "
                "a variant-gate-passing renderer declaration; "
                "nothing is built or rendered here."
            ),
        )
    )
    return ["video.r3f_scene_contract"]


__all__ = [
    "PRIMITIVE_TYPES",
    "compile_r3f_scene_contract",
    "register_r3f_scene_contract_capabilities_once",
]
