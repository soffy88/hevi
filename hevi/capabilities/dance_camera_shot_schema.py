"""Dance camera shot schema (``video.dance_camera_shot_schema``).

Contract-only schema for one camera shot in a dance MV:
its place in the segment, the moment it starts, how
long it lasts, where the camera sits relative to the
dancer, what it does physically, how far and how fast
it moves, and whether it is the shot before the hero
move. Clean-room restatement of the dance MV
methodology (see ``DANCE_MV_METHODOLOGY_ATTRIBUTION.md``);
the camera is described by the physical facts the
method uses — distance, height, position, relative
rotation, motion — never by abstract angle words.

This module is a **contract layer only**. The schema
never renders, scores, or calls a model; ``compile``
returns a contract declaring ``executed_here: false``
and ``output_file: None`` on a well-formed shot, and
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
        "shot_id": {"type": "string", "minLength": 1},
        "segment_id": {"type": "string", "minLength": 1},
        "start_s": {"type": "number", "minimum": 0},
        "end_s": {"type": "number", "exclusiveMinimum": 0},
        "distance_m": {"type": "number", "exclusiveMinimum": 0},
        "height": {"type": "string", "minLength": 1},
        "position": {"type": "string", "minLength": 1},
        "relative_rotation_degrees": {"type": "number"},
        "motion": {"type": "string", "minLength": 1},
        "move_distance_m": {"type": "number", "minimum": 0},
        "move_duration_s": {"type": "number", "exclusiveMinimum": 0},
        "framing_before_hero": {"type": "boolean"},
        "settle_s": {"type": "number", "minimum": 0},
    },
    "required": [
        "shot_id",
        "segment_id",
        "start_s",
        "end_s",
        "distance_m",
        "height",
        "position",
        "motion",
        "move_distance_m",
        "move_duration_s",
        "framing_before_hero",
        "settle_s",
    ],
    "additionalProperties": False,
}


def compile_dance_camera_shot(shot: Any) -> dict[str, Any]:
    """Compile one dance camera shot contract.

    Returns a contract declaring ``executed_here: false``
    and ``output_file: None`` on a well-formed shot.
    Raises :class:`CapabilityError` on any shape
    violation, including an end that is not later than
    its start.
    """
    if not isinstance(shot, dict):
        raise CapabilityError("dance_camera_shot: camera shot must be a JSON object")
    for key in SCHEMA["required"]:
        if key not in shot:
            raise CapabilityError(f"dance_camera_shot: missing required field {key!r}")
    extra = sorted(set(shot) - set(SCHEMA["properties"]))
    if extra:
        raise CapabilityError("dance_camera_shot: unknown fields: " + ", ".join(extra))
    if shot.get("end_s") <= shot.get("start_s"):
        raise CapabilityError("dance_camera_shot: end_s must be later than start_s")
    return {
        "contract": "dance-camera-shot",
        "shot_id": shot["shot_id"],
        "segment_id": shot["segment_id"],
        "executed_here": False,
        "output_file": None,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    contract = compile_dance_camera_shot(params.get("shot"))
    contract_path = out_dir / "dance_camera_shot_contract.json"
    contract_path.write_text(json.dumps(contract, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(contract_path),
        qa={
            "report_json": str(contract_path),
            "shot_id": contract["shot_id"],
            "executed_here": False,
        },
    )


def register_dance_camera_shot_schema_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="video.dance_camera_shot_schema",
            kind="video",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "shot": {"type": "object"},
                },
                "required": ["shot"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="obase",
            description=(
                "Dance camera shot contract (fake): one shot, its "
                "time, its physical camera facts, and whether its "
                "frame is set before the hero move."
            ),
        )
    )
    return ["video.dance_camera_shot_schema"]


__all__ = [
    "SCHEMA",
    "compile_dance_camera_shot",
    "register_dance_camera_shot_schema_capabilities_once",
]
