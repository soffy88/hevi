"""Dance MV prompt pack schema (``video.dance_mv_prompt_pack_schema``).

Contract-only schema for one complete dance MV prompt
pack: one film, one document — title, revision, nine
sections in order, one segment per entry, and one
transition entry per boundary between neighbouring
segments. Clean-room restatement of the dance MV
methodology (see ``DANCE_MV_METHODOLOGY_ATTRIBUTION.md``);
each segment carries its own frame and its complete
prompt, so no segment ever points back at another with
"same as above".

This module is a **contract layer only**. The schema
never renders, scores, or calls a model; ``compile``
returns a contract declaring ``executed_here: false``
and ``output_file: None`` on a well-formed pack, and
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

NINE_SECTIONS: tuple[str, ...] = (
    "revision_history",
    "overall_direction",
    "picture_responsibilities",
    "visual_bible",
    "audio_index",
    "h3_prompts",
    "transition_map",
    "preflight_checklist",
    "post_review",
)

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "pack_id": {"type": "string", "minLength": 1},
        "title": {"type": "string", "minLength": 1},
        "revision": {"type": "string", "minLength": 1},
        "sections": {
            "type": "array",
            "minItems": 9,
            "maxItems": 9,
            "items": {"type": "string"},
        },
        "segments": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "minLength": 1},
                    "global_start": {"type": "string", "minLength": 1},
                    "global_end": {"type": "string", "minLength": 1},
                    "local_duration_s": {"type": "number", "exclusiveMinimum": 0},
                    "audio_file": {"type": "string", "minLength": 1},
                    "h3_prompt": {"type": "object"},
                },
                "required": [
                    "id",
                    "global_start",
                    "global_end",
                    "local_duration_s",
                    "audio_file",
                    "h3_prompt",
                ],
                "additionalProperties": False,
            },
        },
        "transitions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "from_segment": {"type": "string", "minLength": 1},
                    "to_segment": {"type": "string", "minLength": 1},
                    "mechanism": {"type": "string", "minLength": 1},
                },
                "required": ["from_segment", "to_segment", "mechanism"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["pack_id", "title", "revision", "sections", "segments", "transitions"],
    "additionalProperties": False,
}


def compile_dance_mv_prompt_pack(pack: Any) -> dict[str, Any]:
    """Compile one dance MV prompt pack contract.

    Returns a contract declaring ``executed_here: false``
    and ``output_file: None`` on a well-formed pack.
    Raises :class:`CapabilityError` on any shape
    violation, including a section list that is not the
    nine sections in order, or a transition count that
    is not segments minus one.
    """
    if not isinstance(pack, dict):
        raise CapabilityError("dance_mv_prompt_pack: prompt pack must be a JSON object")
    for key in SCHEMA["required"]:
        if key not in pack:
            raise CapabilityError(f"dance_mv_prompt_pack: missing required field {key!r}")
    extra = sorted(set(pack) - set(SCHEMA["properties"]))
    if extra:
        raise CapabilityError("dance_mv_prompt_pack: unknown fields: " + ", ".join(extra))
    if list(pack.get("sections", [])) != list(NINE_SECTIONS):
        raise CapabilityError("dance_mv_prompt_pack: sections must be the nine sections in order")
    segments = pack.get("segments")
    if not isinstance(segments, list) or not segments:
        raise CapabilityError("dance_mv_prompt_pack: at least one segment is required")
    transitions = pack.get("transitions")
    if not isinstance(transitions, list):
        raise CapabilityError("dance_mv_prompt_pack: transition table must be a list")
    if len(transitions) != len(segments) - 1:
        raise CapabilityError(
            "dance_mv_prompt_pack: transition count must equal segments minus one"
        )
    segment_ids = [s.get("id") for s in segments if isinstance(s, dict)]
    for position, boundary in enumerate(transitions):
        if not isinstance(boundary, dict):
            raise CapabilityError(f"dance_mv_prompt_pack: boundary {position} must be an object")
        if boundary.get("from_segment") != segment_ids[position]:
            raise CapabilityError(
                f"dance_mv_prompt_pack: boundary {position} must cut from {segment_ids[position]}"
            )
        if boundary.get("to_segment") != segment_ids[position + 1]:
            raise CapabilityError(
                f"dance_mv_prompt_pack: boundary {position} must cut to {segment_ids[position + 1]}"
            )
    return {
        "contract": "dance-mv-prompt-pack",
        "pack_id": pack["pack_id"],
        "title": pack["title"],
        "segments": len(segments),
        "executed_here": False,
        "output_file": None,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    contract = compile_dance_mv_prompt_pack(params.get("pack"))
    contract_path = out_dir / "dance_mv_prompt_pack_contract.json"
    contract_path.write_text(json.dumps(contract, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(contract_path),
        qa={
            "report_json": str(contract_path),
            "pack_id": contract["pack_id"],
            "executed_here": False,
        },
    )


def register_dance_mv_prompt_pack_schema_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="video.dance_mv_prompt_pack_schema",
            kind="video",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "pack": {"type": "object"},
                },
                "required": ["pack"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="obase",
            description=(
                "Dance MV prompt pack contract (fake): one complete "
                "document, nine sections in order, every segment "
                "framed, every boundary covered."
            ),
        )
    )
    return ["video.dance_mv_prompt_pack_schema"]


__all__ = [
    "NINE_SECTIONS",
    "SCHEMA",
    "compile_dance_mv_prompt_pack",
    "register_dance_mv_prompt_pack_schema_capabilities_once",
]
