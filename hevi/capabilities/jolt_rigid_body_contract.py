"""Jolt rigid-body contract, fake layer (``video.jolt_rigid_body_contract``).

Contract-only schema for a rigid-body and collision world, in
the narrowed scope recorded for Jolt Physics
(``jrouwe/JoltPhysics``, MIT): rigid bodies and collision only.
Soft-body vocabulary is narrowed out on purpose: any plan
carrying a soft-body, cloth, or deformable declaration fails
closed, and nothing here may claim soft-body support. The
library itself is not installed, probed, or invoked, and no
native build or binding exists here; compiling a binding is a
separate real-machine case.

Division of labour, written down so the two artefacts are
never confused: ``scene3d.collision_check`` reports overlaps
and penetration for AABBs and spheres under translation only
-- it does not simulate a physics world. This contract
declares rigid-body world intent (bodies, gravity, collision
pairs) and simulates nothing. ``executed_here`` is always
false, ``simulated_here`` is always false, and
``output_file`` is always null. See OPEN_SKILLS_ATTRIBUTION.md.
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

LIBRARY_REPO = "jrouwe/JoltPhysics"
LIBRARY_LICENSE = "MIT"
SCOPE = "rigid-body and collision only; soft-body support narrowed out"
BINDING_STATUS = (
    "no native build or binding here; compiling a binding is a "
    "separate real-machine case; the library was not installed, "
    "probed, or invoked"
)

# Soft-body vocabulary: any occurrence anywhere in the plan
# fails the contract. The check walks keys and string values so
# a soft-body declaration cannot hide inside a nested object.
_SOFT_BODY_WORDS: frozenset[str] = frozenset(
    {"soft_body", "softbody", "soft-body", "cloth", "deformable"}
)

_SHAPES: tuple[str, ...] = ("box", "sphere")


def _fail(message: str) -> None:
    raise CapabilityError(message)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _reject_soft_body(value: Any, where: str) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(key, str) and key.lower() in _SOFT_BODY_WORDS:
                _fail(
                    f"soft-body declaration at {where}: {key!r} is "
                    "narrowed out; this contract covers rigid "
                    "bodies and collision only"
                )
            _reject_soft_body(item, where)
    elif isinstance(value, list):
        for item in value:
            _reject_soft_body(item, where)
    elif isinstance(value, str) and value.lower() in _SOFT_BODY_WORDS:
        _fail(
            f"soft-body declaration at {where}: {value!r} is narrowed "
            "out; this contract covers rigid bodies and collision only"
        )


def _vec3(value: Any, what: str) -> list[float]:
    if (
        not isinstance(value, list)
        or len(value) != 3
        or not all(_is_number(v) for v in value)
    ):
        _fail(f"{what} must be a 3-number vector")
    return [float(v) for v in value]


def _unit_interval(value: Any, what: str) -> float:
    if not _is_number(value) or value < 0 or value > 1:
        _fail(f"{what} must be a number in [0, 1]")
    return float(value)


def compile_jolt_rigid_body_contract(plan: Any) -> dict[str, Any]:
    """Compile a rigid-body world contract from a plan.

    Raises :class:`CapabilityError` on a malformed plan or on
    any soft-body declaration. The returned contract always
    carries ``executed_here: false`` and
    ``simulated_here: false``: nothing is simulated here.
    """
    if not isinstance(plan, dict):
        _fail("jolt rigid-body plan must be a JSON object")
    _reject_soft_body(plan, "plan")
    world = plan.get("world")
    if not isinstance(world, dict):
        _fail("jolt plan must declare a world object")
    gravity = _vec3(world.get("gravity"), "world.gravity")
    bodies = plan.get("bodies")
    if not isinstance(bodies, list) or not bodies:
        _fail("jolt plan must declare a non-empty bodies list")
    seen_ids: set[str] = set()
    bodies_out: list[dict[str, Any]] = []
    for index, body in enumerate(bodies):
        if not isinstance(body, dict):
            _fail(f"bodies[{index}] must be an object")
        body_id = body.get("id")
        if not isinstance(body_id, str) or not body_id.strip():
            _fail(f"bodies[{index}] must declare an id")
        if body_id in seen_ids:
            _fail(f"duplicate body id {body_id!r}")
        seen_ids.add(body_id)
        shape = body.get("shape")
        if shape not in _SHAPES:
            _fail(f"bodies[{index}] shape must be one of {list(_SHAPES)}")
        if shape == "box":
            extents = body.get("half_extents")
            if (
                not isinstance(extents, list)
                or len(extents) != 3
                or not all(_is_number(v) and v > 0 for v in extents)
            ):
                _fail(
                    f"bodies[{index}] box needs half_extents of "
                    "three positive numbers"
                )
            shape_params = {"half_extents": [float(v) for v in extents]}
        else:
            radius = body.get("radius")
            if not _is_number(radius) or radius <= 0:
                _fail(f"bodies[{index}] sphere needs a positive radius")
            shape_params = {"radius": float(radius)}
        mass = body.get("mass")
        if not _is_number(mass) or mass <= 0:
            _fail(f"bodies[{index}] mass must be a positive number")
        position = _vec3(body.get("position"), f"bodies[{index}].position")
        velocity = body.get("velocity", [0, 0, 0])
        velocity = _vec3(velocity, f"bodies[{index}].velocity")
        bodies_out.append(
            {
                "id": body_id,
                "shape": shape,
                "shape_params": shape_params,
                "position": position,
                "velocity": velocity,
                "mass": float(mass),
                "restitution": _unit_interval(
                    body.get("restitution", 0.0), f"bodies[{index}].restitution"
                ),
                "friction": _unit_interval(
                    body.get("friction", 0.5), f"bodies[{index}].friction"
                ),
            }
        )
    return {
        "library": {"repo": LIBRARY_REPO, "license": LIBRARY_LICENSE},
        "scope": SCOPE,
        "world": {"gravity": gravity},
        "bodies": bodies_out,
        "body_count": len(bodies_out),
        "division_of_labour": (
            "scene3d.collision_check reports overlaps only "
            "(AABB/sphere, translation only, no dynamics); "
            "this contract declares rigid-body world intent "
            "and simulates nothing"
        ),
        "binding_required": BINDING_STATUS,
        "simulated_here": False,
        "executed_here": False,
        "rendered_here": False,
        "output_file": None,
    }


def _render(params: dict[str, Any], out_dir: Any, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    contract = compile_jolt_rigid_body_contract(params.get("plan"))
    contract_path = out_dir / "jolt_rigid_body_contract.json"
    contract_path.write_text(
        json.dumps(contract, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(contract_path),
        qa={"contract_json": str(contract_path), "executed_here": False,
            "simulated_here": False},
    )


def register_jolt_rigid_body_contract_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="video.jolt_rigid_body_contract",
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
                "Jolt rigid-body contract (contract only): "
                "rigid bodies and collision declared, soft-body "
                "vocabulary refused, nothing simulated here."
            ),
        )
    )
    return ["video.jolt_rigid_body_contract"]


__all__ = [
    "compile_jolt_rigid_body_contract",
    "register_jolt_rigid_body_contract_capabilities_once",
]
