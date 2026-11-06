"""Dance segment card schema (``video.dance_segment_card_schema``).

Contract-only schema for one dance MV segment: its
place in the song, its length, its own audio, the
camera it opens and closes with, the transition that
takes it to the next segment, and the key poses and
actions it must land. Clean-room restatement of the
dance MV methodology (see
``DANCE_MV_METHODOLOGY_ATTRIBUTION.md``); the fields
use plain language because the source's internal
action library was never supplied, and no library code
appears anywhere in this schema.

This module is a **contract layer only**. The schema
never renders, scores, or calls a model; ``compile``
returns a contract declaring ``executed_here: false``
and ``output_file: None`` on a well-formed card, and
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

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "segment_id": {"type": "string", "minLength": 1},
        "title": {"type": "string", "minLength": 1},
        "duration_s": {"type": "number", "exclusiveMinimum": 0},
        "global_start_s": {"type": "number", "minimum": 0},
        "audio_file": {"type": "string", "minLength": 1},
        "music": {
            "type": "object",
            "properties": {
                "bpm": {"type": "number", "exclusiveMinimum": 0},
                "bar_length_s": {"type": "number", "exclusiveMinimum": 0},
                "time_signature": {"type": "string", "minLength": 1},
            },
            "required": ["bpm", "bar_length_s"],
            "additionalProperties": False,
        },
        "camera_in": {"type": "string", "minLength": 1},
        "camera_out": {"type": "string", "minLength": 1},
        "transition_in": {"type": "string", "minLength": 1},
        "transition_out": {"type": "string", "minLength": 1},
        "key_poses": {
            "type": "array",
            "minItems": 1,
            "items": {"type": "string", "minLength": 1},
        },
        "must_land_actions": {
            "type": "array",
            "minItems": 1,
            "items": {"type": "string", "minLength": 1},
        },
        "end_state": {
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
        "segment_id",
        "title",
        "duration_s",
        "global_start_s",
        "audio_file",
        "music",
        "camera_in",
        "camera_out",
        "transition_in",
        "transition_out",
        "key_poses",
        "must_land_actions",
        "end_state",
    ],
    "additionalProperties": False,
}


def compile_dance_segment_card(card: Any) -> dict[str, Any]:
    """Compile one dance segment card contract.

    Returns a contract declaring ``executed_here: false``
    and ``output_file: None`` on a well-formed card.
    Raises :class:`CapabilityError` on any shape
    violation. The contract certifies the shape of the
    card only; it renders nothing and executes nothing.
    """
    if not isinstance(card, dict):
        raise CapabilityError("dance_segment_card: segment card must be a JSON object")
    for key in SCHEMA["required"]:
        if key not in card:
            raise CapabilityError(f"dance_segment_card: missing required field {key!r}")
    extra = sorted(set(card) - set(SCHEMA["properties"]))
    if extra:
        raise CapabilityError("dance_segment_card: unknown fields: " + ", ".join(extra))
    if (
        not isinstance(card["duration_s"], (int, float))
        or isinstance(card["duration_s"], bool)
        or card["duration_s"] <= 0
    ):
        raise CapabilityError("dance_segment_card: duration_s must be positive")
    music = card["music"]
    if not isinstance(music, dict):
        raise CapabilityError("dance_segment_card: music must be an object")
    for key in ("bpm", "bar_length_s"):
        if key not in music:
            raise CapabilityError(f"dance_segment_card: music is missing {key!r}")
    if not card["key_poses"] or not card["must_land_actions"]:
        raise CapabilityError(
            "dance_segment_card: key poses and must-land actions must not be empty"
        )
    return {
        "contract": "dance-segment-card",
        "segment_id": card["segment_id"],
        "title": card["title"],
        "duration_s": card["duration_s"],
        "executed_here": False,
        "output_file": None,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    contract = compile_dance_segment_card(params.get("card"))
    contract_path = out_dir / "dance_segment_card_contract.json"
    contract_path.write_text(json.dumps(contract, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(contract_path),
        qa={
            "report_json": str(contract_path),
            "segment_id": contract["segment_id"],
            "executed_here": False,
        },
    )


def register_dance_segment_card_schema_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="video.dance_segment_card_schema",
            kind="video",
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
            description=(
                "Dance segment card contract (fake): one segment, "
                "its place in the song, its audio, its in and out "
                "cameras, and the poses and actions it must land."
            ),
        )
    )
    return ["video.dance_segment_card_schema"]


__all__ = [
    "SCHEMA",
    "compile_dance_segment_card",
    "register_dance_segment_card_schema_capabilities_once",
]
