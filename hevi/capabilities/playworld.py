"""Interactive play capabilities (clean-room, minimal).

Registers two ``hevi.capabilities`` entries backed by the file-based world
engine in :mod:`hevi.playworld`:

* ``play.world_init`` — create a world state JSON (setting, characters,
  items/relationship flags, starting location, turn 0, opening choices).
* ``play.world_step`` — advance one turn.  The caller acts as the narrator:
  it supplies the narration text, the next choices, an optional
  ``image_prompt`` (an illustration hook — prompt text only, no image is
  generated) and an optional ``state_delta``; the engine validates and
  persists everything atomically.  Programmatic callers can instead inject
  a ``narrator_fn`` straight into ``hevi.playworld.step_world``.
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

_CHOICE_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "string", "minLength": 1},
        "label": {"type": "string", "minLength": 1},
    },
    "required": ["id", "label"],
    "additionalProperties": False,
}


def _render_world_init(
    params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    from hevi.playworld import engine

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    world_path = Path(params["world_path"])
    try:
        state = engine.init_world(
            world_path,
            title=params["title"],
            setting=params["setting"],
            characters=params.get("characters", []),
            starting_location=params["starting_location"],
            opening_narration=params["opening_narration"],
            opening_choices=params["opening_choices"],
            opening_image_prompt=params.get("opening_image_prompt", ""),
        )
    except CapabilityError:
        raise
    except Exception as exc:
        raise CapabilityError(f"play.world_init failed: {exc}") from exc

    snapshot = out_dir / "world.json"
    snapshot.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(world_path),
        qa={
            "world_path": str(world_path),
            "snapshot": str(snapshot),
            "title": state["title"],
            "location": state["location"],
            "turn": state["turn"],
            "choices": state["choices"],
            "image_prompt": state["image_prompt"],
        },
    )


def _render_world_step(
    params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    from hevi.playworld import engine

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    world_path = Path(params["world_path"])
    narration = params["narration"]
    choices = params["choices"]
    image_prompt = params.get("image_prompt")
    state_delta = params.get("state_delta")

    def narrator(state: dict[str, Any], action_text: str) -> dict[str, Any]:
        # The capability caller is the narrator; the engine validates this.
        produced: dict[str, Any] = {"narration": narration, "choices": choices}
        if image_prompt is not None:
            produced["image_prompt"] = image_prompt
        if state_delta is not None:
            produced["state_delta"] = state_delta
        return produced

    try:
        outcome = engine.step_world(
            world_path,
            action=params.get("action"),
            choice_id=params.get("choice_id"),
            narrator_fn=narrator,
        )
    except CapabilityError:
        raise
    except Exception as exc:
        raise CapabilityError(f"play.world_step failed: {exc}") from exc

    snapshot = out_dir / "world_step.json"
    snapshot.write_text(
        json.dumps(
            {
                "narration": outcome["narration"],
                "choices": outcome["choices"],
                "image_prompt": outcome["image_prompt"],
                "turn": outcome["turn"],
                "state": outcome["state"],
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(world_path),
        qa={
            "world_path": str(world_path),
            "snapshot": str(snapshot),
            "narration": outcome["narration"],
            "choices": outcome["choices"],
            "image_prompt": outcome["image_prompt"],
            "turn": outcome["turn"],
            "location": outcome["state"]["location"],
        },
    )


def register_playworld_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    registered: list[str] = []

    register(
        Capability(
            name="play.world_init",
            kind="line",
            aspects=["16:9", "9:16", "1:1"],
            params_schema={
                "type": "object",
                "properties": {
                    "world_path": {"type": "string", "minLength": 1},
                    "title": {"type": "string", "minLength": 1},
                    "setting": {"type": "string", "minLength": 1},
                    "characters": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string", "minLength": 1},
                                "description": {"type": "string"},
                            },
                            "required": ["name"],
                            "additionalProperties": False,
                        },
                    },
                    "starting_location": {"type": "string", "minLength": 1},
                    "opening_narration": {"type": "string", "minLength": 1},
                    "opening_choices": {
                        "type": "array",
                        "items": _CHOICE_SCHEMA,
                        "minItems": 1,
                    },
                    "opening_image_prompt": {"type": "string"},
                },
                "required": [
                    "world_path",
                    "title",
                    "setting",
                    "starting_location",
                    "opening_narration",
                    "opening_choices",
                ],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render_world_init,
            description=(
                "Create a file-based interactive world (JSON state: setting, "
                "characters, flags/items, location, turn 0, opening choices). "
                "Refuses to overwrite an existing world file."
            ),
            line="playworld",
        )
    )
    registered.append("play.world_init")

    register(
        Capability(
            name="play.world_step",
            kind="line",
            aspects=["16:9", "9:16", "1:1"],
            params_schema={
                "type": "object",
                "properties": {
                    "world_path": {"type": "string", "minLength": 1},
                    "action": {"type": "string", "minLength": 1},
                    "choice_id": {"type": "string", "minLength": 1},
                    "narration": {"type": "string", "minLength": 1},
                    "choices": {"type": "array", "items": _CHOICE_SCHEMA},
                    "image_prompt": {"type": "string"},
                    "state_delta": {"type": "object"},
                },
                "required": ["world_path", "narration", "choices"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render_world_step,
            description=(
                "Advance an interactive world by one turn: supply an action "
                "(free text and/or choice_id) plus narrator output (narration, "
                "next choices, optional image_prompt hook and state_delta). "
                "State is validated and persisted atomically; turn count grows."
            ),
            line="playworld",
        )
    )
    registered.append("play.world_step")

    return registered
