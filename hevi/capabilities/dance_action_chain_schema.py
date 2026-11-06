"""Dance action chain schema (``video.dance_action_chain_schema``).

Contract-only schema for one dance action chain: three
layers — what keeps moving underneath, the chain of
main moves, and the micro-expressions that live on top
— plus its five logical steps and its entry and exit
states. Clean-room restatement of the dance MV
methodology (see ``DANCE_MV_METHODOLOGY_ATTRIBUTION.md``);
the steps are named in plain language because the
source's internal action library was never supplied,
and **no library code appears anywhere in this schema**:
any ``library_code`` key or bare code-shaped value is
refused outright.

This module is a **contract layer only**. The schema
never renders, scores, or calls a model; ``compile``
returns a contract declaring ``executed_here: false``
and ``output_file: None`` on a well-formed chain, and
raises ``CapabilityError`` on any shape violation.
Real execution is a separate work item.
"""

from __future__ import annotations

import json
import re
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

_CODE_SHAPE = re.compile(r"^[A-Za-z]\d{1,2}$")

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "chain_id": {"type": "string", "minLength": 1},
        "segment_id": {"type": "string", "minLength": 1},
        "groove": {
            "type": "array",
            "minItems": 1,
            "items": {"type": "string", "minLength": 1},
        },
        "main_chain": {
            "type": "array",
            "minItems": 1,
            "items": {"type": "string", "minLength": 1},
        },
        "micro_expressions": {
            "type": "array",
            "items": {"type": "string", "minLength": 1},
        },
        "steps": {
            "type": "array",
            "minItems": 5,
            "maxItems": 5,
            "items": {
                "type": "object",
                "properties": {
                    "order": {"type": "integer", "minimum": 1, "maximum": 5},
                    "action": {"type": "string", "minLength": 1},
                    "duration_s": {"type": "number", "exclusiveMinimum": 0},
                    "beats": {"type": "number", "exclusiveMinimum": 0},
                    "support_foot": {"type": "string", "minLength": 1},
                    "direction": {"type": "string", "minLength": 1},
                },
                "required": ["order", "action", "duration_s"],
                "additionalProperties": False,
            },
        },
        "entry_state": {
            "type": "object",
            "properties": {
                "support_foot": {"type": "string", "minLength": 1},
                "direction": {"type": "string", "minLength": 1},
            },
            "required": ["support_foot", "direction"],
            "additionalProperties": False,
        },
        "exit_state": {
            "type": "object",
            "properties": {
                "support_foot": {"type": "string", "minLength": 1},
                "direction": {"type": "string", "minLength": 1},
            },
            "required": ["support_foot", "direction"],
            "additionalProperties": False,
        },
    },
    "required": [
        "chain_id",
        "segment_id",
        "groove",
        "main_chain",
        "micro_expressions",
        "steps",
        "entry_state",
        "exit_state",
    ],
    "additionalProperties": False,
}


def _has_library_code(value: Any) -> bool:
    """True when any key or bare code-shaped value is present."""
    if isinstance(value, dict):
        return any(
            key == "library_code" or _has_library_code(item) for key, item in value.items()
        ) or any(isinstance(key, str) and bool(_CODE_SHAPE.match(key)) for key in value)
    if isinstance(value, list):
        return any(_has_library_code(item) for item in value)
    return isinstance(value, str) and bool(_CODE_SHAPE.match(value))


def compile_dance_action_chain(chain: Any) -> dict[str, Any]:
    """Compile one dance action chain contract.

    Returns a contract declaring ``executed_here: false``
    and ``output_file: None`` on a well-formed chain.
    Raises :class:`CapabilityError` on any shape
    violation, and on any internal library code, which
    is refused outright: the source library was never
    supplied.
    """
    if not isinstance(chain, dict):
        raise CapabilityError("dance_action_chain: action chain must be a JSON object")
    if _has_library_code(chain):
        raise CapabilityError(
            "dance_action_chain: internal library codes are refused; "
            "the source library was never supplied"
        )
    for key in SCHEMA["required"]:
        if key not in chain:
            raise CapabilityError(f"dance_action_chain: missing required field {key!r}")
    extra = sorted(set(chain) - set(SCHEMA["properties"]))
    if extra:
        raise CapabilityError("dance_action_chain: unknown fields: " + ", ".join(extra))
    steps = chain.get("steps")
    if not isinstance(steps, list) or len(steps) != 5:
        raise CapabilityError("dance_action_chain: exactly five steps are required")
    if sorted(step.get("order") for step in steps if isinstance(step, dict)) != [1, 2, 3, 4, 5]:
        raise CapabilityError("dance_action_chain: steps must be numbered 1-5 in order")
    return {
        "contract": "dance-action-chain",
        "chain_id": chain["chain_id"],
        "segment_id": chain["segment_id"],
        "executed_here": False,
        "output_file": None,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    contract = compile_dance_action_chain(params.get("chain"))
    contract_path = out_dir / "dance_action_chain_contract.json"
    contract_path.write_text(json.dumps(contract, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(contract_path),
        qa={
            "report_json": str(contract_path),
            "chain_id": contract["chain_id"],
            "executed_here": False,
        },
    )


def register_dance_action_chain_schema_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="video.dance_action_chain_schema",
            kind="video",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "chain": {"type": "object"},
                },
                "required": ["chain"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="obase",
            description=(
                "Dance action chain contract (fake): three layers, "
                "five steps, entry and exit states, in plain "
                "language; internal library codes are refused."
            ),
        )
    )
    return ["video.dance_action_chain_schema"]


__all__ = [
    "SCHEMA",
    "compile_dance_action_chain",
    "register_dance_action_chain_schema_capabilities_once",
]
