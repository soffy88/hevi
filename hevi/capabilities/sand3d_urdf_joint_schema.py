"""sand3d URDF joint schema (``model.sand3d_urdf_joint_schema``).

Contract-only schema for one sand3d-style URDF articulation:
its links and the joints between them, each joint naming its
parent link, its child link, its kind, its axis, and its
limits. Every joint endpoint must be a declared link.
Clean-room restatement of the Sandflow-ai/sand3d method (see
``SAND3D_ATTRIBUTION.md``); no upstream code appears here.

This module is a **contract layer only**. The schema never
renders, scores, or calls a model; ``compile`` returns a
contract declaring ``executed_here: false`` and
``output_file: None`` on a well-formed articulation, and
raises ``CapabilityError`` on any shape violation. Real
execution needs a separate py3.13 + bpy 5.2 environment and
is a separate work item.
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
from hevi.capabilities.sand3d_joint_gate import check_sand3d_joint

_Registered = False

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "program_id": {"type": "string", "minLength": 1},
        "links": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "minLength": 1},
                },
                "required": ["name"],
                "additionalProperties": False,
            },
        },
        "joints": {
            "type": "array",
            "minItems": 1,
            "items": {"type": "object"},
        },
    },
    "required": ["program_id", "links", "joints"],
    "additionalProperties": False,
}


def compile_sand3d_urdf_joint(urdf: Any) -> dict[str, Any]:
    """Compile one sand3d URDF joint contract.

    Returns a contract declaring ``executed_here: false``
    and ``output_file: None`` on a well-formed articulation.
    Raises :class:`CapabilityError` on any shape violation.
    The contract certifies the shape of the articulation
    only; it renders nothing and executes nothing.
    """
    if not isinstance(urdf, dict):
        raise CapabilityError("sand3d_urdf_joint: urdf must be a JSON object")
    for key in SCHEMA["required"]:
        if key not in urdf:
            raise CapabilityError(f"sand3d_urdf_joint: missing required field {key!r}")
    extra = sorted(set(urdf) - set(SCHEMA["properties"]))
    if extra:
        raise CapabilityError("sand3d_urdf_joint: unknown fields: " + ", ".join(extra))
    links = urdf["links"]
    if not isinstance(links, list) or not links:
        raise CapabilityError("sand3d_urdf_joint: links must be a non-empty list")
    link_names: set[str] = set()
    for position, link in enumerate(links):
        if not isinstance(link, dict):
            raise CapabilityError(f"sand3d_urdf_joint: link {position} must be an object")
        name = link.get("name")
        if not isinstance(name, str) or not name:
            raise CapabilityError(f"sand3d_urdf_joint: link {position} must carry a name")
        link_names.add(name)
    verdict = check_sand3d_joint(urdf["joints"])
    if verdict["verdict"] != "pass":
        first = verdict["issues"][0]
        raise CapabilityError(f"sand3d_urdf_joint: {first['code']}: {first['detail']}")
    for position, joint in enumerate(urdf["joints"]):
        for endpoint in ("child", "on"):
            if joint[endpoint] not in link_names:
                raise CapabilityError(
                    f"sand3d_urdf_joint: joint {position} {endpoint} "
                    f"{joint[endpoint]!r} is not a declared link"
                )
    return {
        "contract": "sand3d-urdf-joint",
        "program_id": urdf["program_id"],
        "link_count": len(links),
        "joint_count": len(urdf["joints"]),
        "executed_here": False,
        "output_file": None,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    contract = compile_sand3d_urdf_joint(params.get("urdf"))
    contract_path = out_dir / "sand3d_urdf_joint_contract.json"
    contract_path.write_text(json.dumps(contract, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(contract_path),
        qa={
            "report_json": str(contract_path),
            "program_id": contract["program_id"],
            "executed_here": False,
        },
    )


def register_sand3d_urdf_joint_schema_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="model.sand3d_urdf_joint_schema",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "urdf": {"type": "object"},
                },
                "required": ["urdf"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="obase",
            line="model",
            description=(
                "sand3d URDF joint contract (fake): links and the "
                "joints between them, every endpoint a declared "
                "link; shape only, never executed here."
            ),
        )
    )
    return ["model.sand3d_urdf_joint_schema"]


__all__ = [
    "SCHEMA",
    "compile_sand3d_urdf_joint",
    "register_sand3d_urdf_joint_schema_capabilities_once",
]
