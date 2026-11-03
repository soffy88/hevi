"""Scene blocking schema gate (``qa.scene_blocking_schema``).

Clean-room restatement of the scene blocking discipline
described in the Infinite Creation review (see
``INFINITE_CREATION_ATTRIBUTION.md``): a scene's blocking is a
structured record, not prose. It names one spatial anchor, every
character's screen position, facing and depth, every prop's
anchor, and which side of the 180-degree axis the camera stays
on. The camera side must match the declared axis side, and a
character may only cross the axis when the crossing is declared
explicitly as a transition. Anything less is not a blocking
record a later shot can be checked against.

This module judges blocking records only. It never generates,
never calls a model, and it does not judge whether a blocking is
good staging -- only whether the record is complete and
self-consistent.
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

_SCREEN_POSITIONS = ("left", "center", "right")
_FACINGS = ("left", "right", "camera", "away")
_DEPTHS = ("foreground", "midground", "background")
_SIDES = ("left", "right")


def _issue(code: str, detail: str, **extra: Any) -> dict[str, Any]:
    issue = {"code": code, "detail": f"qa.scene_blocking_schema: {detail}"}
    issue.update(extra)
    return issue


def check_scene_blocking(blocking: Any) -> dict[str, Any]:
    """Judge one scene blocking record.

    ``blocking`` carries ``scene_id``, ``spatial_anchor``,
    ``characters`` (each with ``name``, ``screen_position``,
    ``facing`` and ``depth``), ``props`` (each with ``name`` and
    ``anchor``), ``axis_side`` and ``camera_side``, and optional
    ``transitions``. Verdict ``pass`` means the record is complete
    and the camera side matches the axis side, with every axis
    crossing declared explicitly.
    """
    if not isinstance(blocking, dict):
        raise CapabilityError("blocking record must be an object")
    issues: list[dict[str, Any]] = []
    if not blocking.get("scene_id"):
        issues.append(_issue("scene_id_missing", "blocking record requires scene_id"))
    anchor = blocking.get("spatial_anchor")
    if not isinstance(anchor, str) or not anchor.strip():
        issues.append(_issue("spatial_anchor_missing", "blocking record requires a spatial_anchor"))
    characters = blocking.get("characters")
    if not isinstance(characters, list) or not characters:
        issues.append(_issue("characters_missing", "blocking record requires a non-empty characters list"))
        characters = []
    for index, character in enumerate(characters):
        if not isinstance(character, dict):
            issues.append(_issue("character_not_object", f"character {index} is not an object"))
            continue
        if not character.get("name"):
            issues.append(_issue("character_name_missing", f"character {index} lacks a name"))
        if character.get("screen_position") not in _SCREEN_POSITIONS:
            issues.append(
                _issue(
                    "screen_position_invalid",
                    f"character {index} screen_position must be one of {_SCREEN_POSITIONS}",
                    character=index,
                )
            )
        if character.get("facing") not in _FACINGS:
            issues.append(
                _issue(
                    "facing_invalid",
                    f"character {index} facing must be one of {_FACINGS}",
                    character=index,
                )
            )
        if character.get("depth") not in _DEPTHS:
            issues.append(
                _issue(
                    "depth_invalid",
                    f"character {index} depth must be one of {_DEPTHS}",
                    character=index,
                )
            )
    props = blocking.get("props", [])
    if not isinstance(props, list):
        raise CapabilityError("props must be a list when present")
    for index, prop in enumerate(props):
        if not isinstance(prop, dict):
            issues.append(_issue("prop_not_object", f"prop {index} is not an object"))
            continue
        if not prop.get("name"):
            issues.append(_issue("prop_name_missing", f"prop {index} lacks a name"))
        if not isinstance(prop.get("anchor"), str) or not prop["anchor"].strip():
            issues.append(_issue("prop_anchor_missing", f"prop {index} lacks an anchor", prop=index))
    axis_side = blocking.get("axis_side")
    camera_side = blocking.get("camera_side")
    if axis_side not in _SIDES:
        issues.append(_issue("axis_side_invalid", f"axis_side must be one of {_SIDES}"))
    if camera_side not in _SIDES:
        issues.append(_issue("camera_side_invalid", f"camera_side must be one of {_SIDES}"))
    elif axis_side in _SIDES and camera_side != axis_side:
        issues.append(
            _issue(
                "axis_crossed",
                f"camera_side {camera_side} does not match axis_side {axis_side}",
            )
        )
    transitions = blocking.get("transitions", [])
    if not isinstance(transitions, list):
        raise CapabilityError("transitions must be a list when present")
    for index, transition in enumerate(transitions):
        if not isinstance(transition, dict):
            issues.append(_issue("transition_not_object", f"transition {index} is not an object"))
            continue
        if transition.get("crosses_axis") and not transition.get("explicit_transition"):
            issues.append(
                _issue(
                    "undeclared_axis_crossing",
                    f"transition {index} crosses the axis without an explicit declaration",
                    transition=index,
                )
            )
    verdict = "fail" if issues else "pass"
    return {
        "ok": verdict != "fail",
        "verdict": verdict,
        "issues": issues,
        "not_checked": [],
        "scene_id": blocking.get("scene_id"),
        "character_count": len(characters),
        "prop_count": len(props),
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_scene_blocking(params.get("blocking"))
    report_path = out_dir / "scene_blocking.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_scene_blocking_schema_capabilities_once() -> list[str]:
    """Register ``qa.scene_blocking_schema`` on the unified registry (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.scene_blocking_schema",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "blocking": {"type": "object"},
                },
                "required": ["blocking"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Scene blocking schema gate: a blocking record must name a "
                "spatial anchor, every character position/facing/depth, every "
                "prop anchor, and a camera side matching the axis side, with "
                "every axis crossing declared explicitly."
            ),
        )
    )
    return ["qa.scene_blocking_schema"]


__all__ = ["check_scene_blocking", "register_scene_blocking_schema_capabilities_once"]
