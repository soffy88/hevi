"""sand3d program schema (``model.sand3d_program_schema``).

Contract-only schema for one sand3d-style program: its id,
the pinned sand3d version, its units, its verb list, and its
parts. Clean-room restatement of the Sandflow-ai/sand3d
method (see ``SAND3D_ATTRIBUTION.md``); no upstream code,
program text, or example material appears in this schema.

This module is a **contract layer only**. The schema never
renders, scores, or calls a model; ``compile`` returns a
contract declaring ``executed_here: false`` and
``output_file: None`` on a well-formed program, and raises
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
from hevi.capabilities.sand3d_modeling_vocabulary_gate import (
    VOCABULARY,
    check_sand3d_modeling_vocabulary,
)

_Registered = False

PINNED_VERSION = "1.6.3"

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "program_id": {"type": "string", "minLength": 1},
        "sand3d_version": {"type": "string", "minLength": 1},
        "units": {"type": "string", "minLength": 1},
        "verbs": {"type": "array", "minItems": 1, "items": {"type": "string"}},
        "parts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "part_id": {"type": "string", "minLength": 1},
                    "verbs": {
                        "type": "array",
                        "minItems": 1,
                        "items": {"type": "string"},
                    },
                },
                "required": ["part_id", "verbs"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["program_id", "sand3d_version", "units", "verbs"],
    "additionalProperties": False,
}


def compile_sand3d_program(program: Any) -> dict[str, Any]:
    """Compile one sand3d program contract.

    Returns a contract declaring ``executed_here: false``
    and ``output_file: None`` on a well-formed program.
    Raises :class:`CapabilityError` on any shape violation.
    The contract certifies the shape of the program only; it
    renders nothing and executes nothing.
    """
    if not isinstance(program, dict):
        raise CapabilityError("sand3d_program: program must be a JSON object")
    for key in SCHEMA["required"]:
        if key not in program:
            raise CapabilityError(f"sand3d_program: missing required field {key!r}")
    extra = sorted(set(program) - set(SCHEMA["properties"]))
    if extra:
        raise CapabilityError("sand3d_program: unknown fields: " + ", ".join(extra))
    if program["sand3d_version"] != PINNED_VERSION:
        raise CapabilityError(
            f"sand3d_program: sand3d_version must be pinned to {PINNED_VERSION!r}"
        )
    verdict = check_sand3d_modeling_vocabulary(program)
    if verdict["verdict"] != "pass":
        first = verdict["issues"][0]
        raise CapabilityError(f"sand3d_program: {first['code']}: {first['detail']}")
    parts = program.get("parts", [])
    if not isinstance(parts, list):
        raise CapabilityError("sand3d_program: parts must be a list")
    for position, part in enumerate(parts):
        if not isinstance(part, dict):
            raise CapabilityError(f"sand3d_program: part {position} must be an object")
        if not isinstance(part.get("part_id"), str) or not part["part_id"]:
            raise CapabilityError(f"sand3d_program: part {position} must carry a part_id")
        part_verbs = part.get("verbs")
        if not isinstance(part_verbs, list) or not part_verbs:
            raise CapabilityError(
                f"sand3d_program: part {position} must carry a non-empty verb list"
            )
        for verb in part_verbs:
            if verb not in VOCABULARY:
                raise CapabilityError(
                    f"sand3d_program: part {position} verb {verb!r} "
                    "is outside the closed vocabulary"
                )
    return {
        "contract": "sand3d-program",
        "program_id": program["program_id"],
        "sand3d_version": program["sand3d_version"],
        "verb_count": len(program["verbs"]),
        "part_count": len(parts),
        "executed_here": False,
        "output_file": None,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    contract = compile_sand3d_program(params.get("program"))
    contract_path = out_dir / "sand3d_program_contract.json"
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


def register_sand3d_program_schema_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="model.sand3d_program_schema",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "program": {"type": "object"},
                },
                "required": ["program"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="obase",
            line="model",
            description=(
                "sand3d program contract (fake): one program, its "
                "pinned version, units, verb list, and parts; "
                "shape only, never executed here."
            ),
        )
    )
    return ["model.sand3d_program_schema"]


__all__ = [
    "PINNED_VERSION",
    "SCHEMA",
    "compile_sand3d_program",
    "register_sand3d_program_schema_capabilities_once",
]
