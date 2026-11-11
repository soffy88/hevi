"""sand3d dataset program card schema (``model.sand3d_dataset_card_schema``).

Contract-only schema for one sand3d dataset program card: the
dataset it comes from, its CC BY 4.0 license, its attribution
text, its source chain, and a pointer to the program text.
The card points at program text only; it carries no mesh
bytes, and dataset meshes are never hevi assets. Clean-room
restatement of the Sandflow-ai/sand3d method (see
``SAND3D_ATTRIBUTION.md``); no upstream code appears here.

This module is a **contract layer only**. The schema never
renders, scores, or calls a model; ``compile`` returns a
contract declaring ``executed_here: false`` and
``output_file: None`` on a well-formed card, and raises
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
from hevi.capabilities.sand3d_dataset_attribution_gate import (
    check_sand3d_dataset_attribution,
)

_Registered = False

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "dataset": {"type": "string", "minLength": 1},
        "license": {"type": "string", "minLength": 1},
        "attribution": {"type": "string", "minLength": 1},
        "source_chain": {"type": "array", "minItems": 1},
        "program_pointer": {"type": "string", "minLength": 1},
        "meshes_are_hevi_assets": {"type": "boolean"},
    },
    "required": [
        "dataset",
        "license",
        "attribution",
        "source_chain",
        "program_pointer",
    ],
    "additionalProperties": False,
}


def compile_sand3d_dataset_card(card: Any) -> dict[str, Any]:
    """Compile one sand3d dataset program card contract.

    Returns a contract declaring ``executed_here: false``
    and ``output_file: None`` on a well-formed card.
    Raises :class:`CapabilityError` on any shape violation.
    The contract certifies the shape of the card only; it
    renders nothing, downloads nothing, and executes nothing.
    """
    if not isinstance(card, dict):
        raise CapabilityError("sand3d_dataset_card: card must be a JSON object")
    for key in SCHEMA["required"]:
        if key not in card:
            raise CapabilityError(f"sand3d_dataset_card: missing required field {key!r}")
    extra = sorted(set(card) - set(SCHEMA["properties"]))
    if extra:
        raise CapabilityError("sand3d_dataset_card: unknown fields: " + ", ".join(extra))
    verdict = check_sand3d_dataset_attribution(
        [
            {
                "name": card["dataset"],
                "license": card["license"],
                "attribution": card["attribution"],
                "source_chain": card["source_chain"],
                "meshes_are_hevi_assets": card.get("meshes_are_hevi_assets"),
            }
        ]
    )
    if verdict["verdict"] != "pass":
        first = verdict["issues"][0]
        raise CapabilityError(f"sand3d_dataset_card: {first['code']}: {first['detail']}")
    if not isinstance(card["program_pointer"], str) or not card["program_pointer"]:
        raise CapabilityError(
            "sand3d_dataset_card: program_pointer must be a "
            "non-empty text pointer, never mesh bytes"
        )
    return {
        "contract": "sand3d-dataset-card",
        "dataset": card["dataset"],
        "license": card["license"],
        "program_pointer": card["program_pointer"],
        "executed_here": False,
        "output_file": None,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    contract = compile_sand3d_dataset_card(params.get("card"))
    contract_path = out_dir / "sand3d_dataset_card_contract.json"
    contract_path.write_text(json.dumps(contract, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(contract_path),
        qa={
            "report_json": str(contract_path),
            "dataset": contract["dataset"],
            "executed_here": False,
        },
    )


def register_sand3d_dataset_card_schema_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="model.sand3d_dataset_card_schema",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "card": {"type": "object"},
                },
                "required": ["card"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="obase",
            line="model",
            description=(
                "sand3d dataset card contract (fake): dataset, CC "
                "BY 4.0 license, attribution, source chain, and a "
                "program-text pointer only; meshes are never hevi "
                "assets; shape only, never executed here."
            ),
        )
    )
    return ["model.sand3d_dataset_card_schema"]


__all__ = [
    "SCHEMA",
    "compile_sand3d_dataset_card",
    "register_sand3d_dataset_card_schema_capabilities_once",
]
