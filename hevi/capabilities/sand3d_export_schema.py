"""sand3d multi-format export schema (``model.sand3d_export_schema``).

Contract-only schema for one sand3d-style multi-format
export: the program it exports and the files it writes, one
per format, chosen by suffix. Clean-room restatement of the
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
from hevi.capabilities.sand3d_export_format_gate import check_sand3d_export_format

_Registered = False

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "program_id": {"type": "string", "minLength": 1},
        "exports": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "minLength": 1},
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["program_id", "exports"],
    "additionalProperties": False,
}


def _suffix(path: str) -> str:
    name = path.rsplit("/", 1)[-1]
    if "." not in name:
        return ""
    return "." + name.rsplit(".", 1)[-1].lower()


def compile_sand3d_export(export: Any) -> dict[str, Any]:
    """Compile one sand3d export contract.

    Returns a contract declaring ``executed_here: false``
    and ``output_file: None`` on a well-formed export.
    Raises :class:`CapabilityError` on any shape violation.
    The contract certifies the shape of the export only; it
    renders nothing and executes nothing.
    """
    if not isinstance(export, dict):
        raise CapabilityError("sand3d_export: export must be a JSON object")
    for key in SCHEMA["required"]:
        if key not in export:
            raise CapabilityError(f"sand3d_export: missing required field {key!r}")
    extra = sorted(set(export) - set(SCHEMA["properties"]))
    if extra:
        raise CapabilityError("sand3d_export: unknown fields: " + ", ".join(extra))
    verdict = check_sand3d_export_format(export["exports"])
    if verdict["verdict"] != "pass":
        first = verdict["issues"][0]
        raise CapabilityError(f"sand3d_export: {first['code']}: {first['detail']}")
    formats = sorted({_suffix(entry["path"]) for entry in export["exports"]})
    return {
        "contract": "sand3d-export",
        "program_id": export["program_id"],
        "formats": formats,
        "executed_here": False,
        "output_file": None,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    contract = compile_sand3d_export(params.get("export"))
    contract_path = out_dir / "sand3d_export_contract.json"
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


def register_sand3d_export_schema_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="model.sand3d_export_schema",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "export": {"type": "object"},
                },
                "required": ["export"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="obase",
            line="model",
            description=(
                "sand3d export contract (fake): one program, its "
                "export files, one per format by suffix; shape "
                "only, never executed here."
            ),
        )
    )
    return ["model.sand3d_export_schema"]


__all__ = [
    "SCHEMA",
    "compile_sand3d_export",
    "register_sand3d_export_schema_capabilities_once",
]
