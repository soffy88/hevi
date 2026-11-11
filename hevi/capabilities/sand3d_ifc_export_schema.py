"""sand3d IFC export schema (``model.sand3d_ifc_export_schema``).

Contract-only schema for one sand3d-style IFC export: its
program, its IFC4 project, its parts, and its GlobalId
notice. The GlobalId instability statement and the
exclusion declaration travel with the contract, as the
honesty gate requires. Clean-room restatement of the
Sandflow-ai/sand3d method (see ``SAND3D_ATTRIBUTION.md``);
no upstream code appears in this schema.

This module is a **contract layer only**. The schema never
renders, scores, or calls a model; ``compile`` returns a
contract declaring ``executed_here: false`` and
``output_file: None`` on a well-formed export, and raises
``CapabilityError`` on any shape violation. Real execution
needs a separate py3.13 + bpy 5.2 environment and is a
separate work item.
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
from hevi.capabilities.sand3d_ifc_honesty_gate import check_sand3d_ifc_honesty

_Registered = False

IFC_VERSION = "IFC4"

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "program_id": {"type": "string", "minLength": 1},
        "ifc_version": {"type": "string", "minLength": 1},
        "project": {"type": "string", "minLength": 1},
        "parts": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "part_id": {"type": "string", "minLength": 1},
                },
                "required": ["part_id"],
                "additionalProperties": False,
            },
        },
        "global_id_notice": {"type": "string", "minLength": 1},
        "states_global_id_unstable": {"type": "boolean"},
        "excluded_quantities": {"type": "array", "minItems": 1},
    },
    "required": [
        "program_id",
        "ifc_version",
        "project",
        "parts",
        "global_id_notice",
        "states_global_id_unstable",
        "excluded_quantities",
    ],
    "additionalProperties": False,
}


def compile_sand3d_ifc_export(ifc: Any) -> dict[str, Any]:
    """Compile one sand3d IFC export contract.

    Returns a contract declaring ``executed_here: false``
    and ``output_file: None`` on a well-formed export.
    Raises :class:`CapabilityError` on any shape violation.
    The contract certifies the shape of the export only; it
    renders nothing and executes nothing.
    """
    if not isinstance(ifc, dict):
        raise CapabilityError("sand3d_ifc_export: ifc must be a JSON object")
    for key in SCHEMA["required"]:
        if key not in ifc:
            raise CapabilityError(f"sand3d_ifc_export: missing required field {key!r}")
    extra = sorted(set(ifc) - set(SCHEMA["properties"]))
    if extra:
        raise CapabilityError("sand3d_ifc_export: unknown fields: " + ", ".join(extra))
    if ifc["ifc_version"] != IFC_VERSION:
        raise CapabilityError(f"sand3d_ifc_export: ifc_version must be {IFC_VERSION!r}")
    verdict = check_sand3d_ifc_honesty(
        {
            "format": "ifc",
            "global_id_notice": ifc["global_id_notice"],
            "states_global_id_unstable": ifc["states_global_id_unstable"],
            "excluded_quantities": ifc["excluded_quantities"],
        }
    )
    if verdict["verdict"] != "pass":
        first = verdict["issues"][0]
        raise CapabilityError(f"sand3d_ifc_export: {first['code']}: {first['detail']}")
    for position, part in enumerate(ifc["parts"]):
        if not isinstance(part, dict):
            raise CapabilityError(f"sand3d_ifc_export: part {position} must be an object")
        if not isinstance(part.get("part_id"), str) or not part["part_id"]:
            raise CapabilityError(f"sand3d_ifc_export: part {position} must carry a part_id")
    return {
        "contract": "sand3d-ifc-export",
        "program_id": ifc["program_id"],
        "project": ifc["project"],
        "part_count": len(ifc["parts"]),
        "executed_here": False,
        "output_file": None,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    contract = compile_sand3d_ifc_export(params.get("ifc"))
    contract_path = out_dir / "sand3d_ifc_export_contract.json"
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


def register_sand3d_ifc_export_schema_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="model.sand3d_ifc_export_schema",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "ifc": {"type": "object"},
                },
                "required": ["ifc"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="obase",
            line="model",
            description=(
                "sand3d IFC export contract (fake): IFC4 project, "
                "parts, GlobalId notice and exclusion declaration; "
                "shape only, never executed here."
            ),
        )
    )
    return ["model.sand3d_ifc_export_schema"]


__all__ = [
    "IFC_VERSION",
    "SCHEMA",
    "compile_sand3d_ifc_export",
    "register_sand3d_ifc_export_schema_capabilities_once",
]
