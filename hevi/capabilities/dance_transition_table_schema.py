"""Dance transition table schema (``video.dance_transition_table_schema``).

Contract-only schema for the transition table of one
dance MV: one entry per boundary between neighbouring
segments, each naming the segment it cuts from, the
segment it cuts to, the single mechanism it uses from
the closed vocabulary of eleven, and the visible hook
the edit lands on. Clean-room restatement of the dance
MV methodology (see ``DANCE_MV_METHODOLOGY_ATTRIBUTION.md``).

This module is a **contract layer only**. The schema
never renders, scores, or calls a model; ``compile``
returns a contract declaring ``executed_here: false``
and ``output_file: None`` on a well-formed table, and
raises ``CapabilityError`` on any shape violation.
Real execution is a separate work item.
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

TRANSITIONS: frozenset[str] = frozenset(
    {
        "match_on_action",
        "shape_match",
        "direction_match",
        "foreground_wipe",
        "whip_pan",
        "focus_match",
        "reflection_match",
        "rotation_phase_match",
        "hard_cut_on_beat",
        "soft_dissolve",
        "flash",
    }
)

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "table_id": {"type": "string", "minLength": 1},
        "film_id": {"type": "string", "minLength": 1},
        "entries": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "from_segment": {"type": "string", "minLength": 1},
                    "to_segment": {"type": "string", "minLength": 1},
                    "mechanism": {"type": "string", "enum": sorted(TRANSITIONS)},
                    "hook": {"type": "string", "minLength": 1},
                },
                "required": ["from_segment", "to_segment", "mechanism", "hook"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["table_id", "film_id", "entries"],
    "additionalProperties": False,
}


def compile_dance_transition_table(table: Any) -> dict[str, Any]:
    """Compile one dance transition table contract.

    Returns a contract declaring ``executed_here: false``
    and ``output_file: None`` on a well-formed table.
    Raises :class:`CapabilityError` on any shape
    violation, including an unknown mechanism.
    """
    if not isinstance(table, dict):
        raise CapabilityError("dance_transition_table: transition table must be a JSON object")
    for key in SCHEMA["required"]:
        if key not in table:
            raise CapabilityError(f"dance_transition_table: missing required field {key!r}")
    extra = sorted(set(table) - set(SCHEMA["properties"]))
    if extra:
        raise CapabilityError("dance_transition_table: unknown fields: " + ", ".join(extra))
    entries = table.get("entries")
    if not isinstance(entries, list) or not entries:
        raise CapabilityError("dance_transition_table: at least one boundary entry is required")
    for position, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise CapabilityError(f"dance_transition_table: entry {position} must be an object")
        for key in ("from_segment", "to_segment", "mechanism", "hook"):
            if key not in entry:
                raise CapabilityError(
                    f"dance_transition_table: entry {position} is missing {key!r}"
                )
        if entry["mechanism"] not in TRANSITIONS:
            raise CapabilityError(
                "dance_transition_table: entry "
                f"{position} names unknown mechanism "
                f"{entry['mechanism']!r}"
            )
    return {
        "contract": "dance-transition-table",
        "table_id": table["table_id"],
        "film_id": table["film_id"],
        "entries": len(entries),
        "executed_here": False,
        "output_file": None,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    contract = compile_dance_transition_table(params.get("table"))
    contract_path = out_dir / "dance_transition_table_contract.json"
    contract_path.write_text(json.dumps(contract, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(contract_path),
        qa={
            "report_json": str(contract_path),
            "table_id": contract["table_id"],
            "executed_here": False,
        },
    )


def register_dance_transition_table_schema_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="video.dance_transition_table_schema",
            kind="video",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "table": {"type": "object"},
                },
                "required": ["table"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="obase",
            description=(
                "Dance transition table contract (fake): one entry "
                "per boundary, one mechanism from the closed "
                "vocabulary of eleven, one visible hook each."
            ),
        )
    )
    return ["video.dance_transition_table_schema"]


__all__ = [
    "SCHEMA",
    "TRANSITIONS",
    "compile_dance_transition_table",
    "register_dance_transition_table_schema_capabilities_once",
]
