"""File-based interactive world engine (clean-room, minimal).

A world is one JSON state file::

    {
      "schema": "hevi.playworld/v1",
      "title": ..., "setting": ...,
      "characters": [{"name": ..., "description": ...}, ...],
      "flags": {},            # arbitrary world flags (bool/str/number)
      "items": [],            # carried items (strings)
      "relationships": {},    # {character: {other: value}}
      "location": ...,        # current location name
      "turn": 0,
      "narration": ...,       # latest narration text
      "choices": [{"id": ..., "label": ...}, ...],
      "image_prompt": ...,    # illustration hook: a prompt, never an image
      "log": [{"turn": n, "action": ..., "narration": ...}, ...]
    }

``init_world`` creates the file; ``step_world`` advances it by one turn.
The caller injects ``narrator_fn(state, action)`` which must return::

    {
      "narration": str,                       # required, non-empty
      "choices": [{"id": str, "label": str}], # required (may be empty = ending)
      "image_prompt": str,                    # optional; auto-composed if omitted
      "state_delta": {                        # optional
        "location": str,
        "flags": {key: value}, "flags_unset": [key, ...],
        "items_add": [str], "items_remove": [str],
        "relationships": {name: {other: value}}
      }
    }

The engine owns validation, turn counting and atomic persistence
(temp file + ``os.replace``); the narrator owns creativity.  Every misuse
raises :class:`CapabilityError` — never a fake success.
"""

from __future__ import annotations

import contextlib
import copy
import json
import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from hevi.capabilities.errors import CapabilityError

WORLD_SCHEMA = "hevi.playworld/v1"

NarratorFn = Callable[[dict[str, Any], str], dict[str, Any]]

_DELTA_KEYS = {"location", "flags", "flags_unset", "items_add", "items_remove", "relationships"}


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False, indent=1))
        os.replace(tmp_name, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise


def _require_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CapabilityError(f"playworld: {field} must be a non-empty string")
    return value


def _validate_choices(choices: Any, field: str) -> list[dict[str, str]]:
    if not isinstance(choices, list):
        raise CapabilityError(f"playworld: {field} must be a list of {{id, label}}")
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in choices:
        if not isinstance(item, dict):
            raise CapabilityError(f"playworld: {field} entries must be objects")
        cid = _require_text(item.get("id"), f"{field}[].id")
        label = _require_text(item.get("label"), f"{field}[].label")
        if cid in seen:
            raise CapabilityError(f"playworld: duplicate choice id {cid!r} in {field}")
        seen.add(cid)
        out.append({"id": cid, "label": label})
    return out


def _validate_characters(characters: Any) -> list[dict[str, Any]]:
    if characters is None:
        return []
    if not isinstance(characters, list):
        raise CapabilityError("playworld: characters must be a list")
    out: list[dict[str, Any]] = []
    for item in characters:
        if not isinstance(item, dict):
            raise CapabilityError("playworld: characters entries must be objects")
        name = _require_text(item.get("name"), "characters[].name")
        entry: dict[str, Any] = {"name": name}
        if item.get("description") is not None:
            entry["description"] = str(item["description"])
        out.append(entry)
    return out


def load_world(path: str | Path) -> dict[str, Any]:
    """Read and validate a world state file; raise CapabilityError if unusable."""
    p = Path(path)
    if not p.is_file():
        raise CapabilityError(f"playworld: world file not found: {p}")
    try:
        payload = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        raise CapabilityError(f"playworld: world file is not valid JSON: {p}: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema") != WORLD_SCHEMA:
        raise CapabilityError(f"playworld: not a {WORLD_SCHEMA} world file: {p}")
    return payload


def init_world(
    path: str | Path,
    *,
    title: str,
    setting: str,
    characters: Any = None,
    starting_location: str,
    opening_narration: str,
    opening_choices: Any,
    opening_image_prompt: str = "",
) -> dict[str, Any]:
    """Create a new world state file and return the initial state.

    Refuses to overwrite an existing file: clobbering a running world is a
    caller bug, not a reset feature.
    """
    p = Path(path)
    if p.exists():
        raise CapabilityError(f"playworld: world file already exists: {p}")
    state: dict[str, Any] = {
        "schema": WORLD_SCHEMA,
        "title": _require_text(title, "title"),
        "setting": _require_text(setting, "setting"),
        "characters": _validate_characters(characters),
        "flags": {},
        "items": [],
        "relationships": {},
        "location": _require_text(starting_location, "starting_location"),
        "turn": 0,
        "narration": _require_text(opening_narration, "opening_narration"),
        "choices": _validate_choices(opening_choices, "opening_choices"),
        "image_prompt": str(opening_image_prompt or ""),
        "log": [{"turn": 0, "action": None, "narration": opening_narration}],
    }
    if not state["choices"]:
        raise CapabilityError("playworld: opening_choices must offer at least one choice")
    _atomic_write_json(p, state)
    return state


def _apply_delta(state: dict[str, Any], delta: Any) -> None:
    if delta is None:
        return
    if not isinstance(delta, dict):
        raise CapabilityError("playworld: state_delta must be an object")
    unknown = set(delta) - _DELTA_KEYS
    if unknown:
        raise CapabilityError(f"playworld: unknown state_delta keys: {sorted(unknown)}")
    if "location" in delta:
        state["location"] = _require_text(delta["location"], "state_delta.location")
    if "flags" in delta:
        if not isinstance(delta["flags"], dict):
            raise CapabilityError("playworld: state_delta.flags must be an object")
        state.setdefault("flags", {}).update(delta["flags"])
    for key in delta.get("flags_unset") or []:
        state.setdefault("flags", {}).pop(key, None)
    items = state.setdefault("items", [])
    for item in delta.get("items_add") or []:
        if item not in items:
            items.append(item)
    for item in delta.get("items_remove") or []:
        if item in items:
            items.remove(item)
    if "relationships" in delta:
        rel = delta["relationships"]
        if not isinstance(rel, dict):
            raise CapabilityError("playworld: state_delta.relationships must be an object")
        target = state.setdefault("relationships", {})
        for name, edges in rel.items():
            if not isinstance(edges, dict):
                raise CapabilityError("playworld: relationships values must be objects")
            target.setdefault(name, {}).update(edges)


def step_world(
    path: str | Path,
    *,
    action: str | None = None,
    choice_id: str | None = None,
    narrator_fn: NarratorFn,
) -> dict[str, Any]:
    """Advance the world at ``path`` by one turn.

    ``action`` is free text; ``choice_id`` selects one of the current choices
    (its label becomes the action when no explicit action text is given).
    Returns ``{narration, choices, image_prompt, turn, state}``.
    """
    if not callable(narrator_fn):
        raise CapabilityError("playworld: narrator_fn must be callable")
    state = load_world(path)

    if choice_id is not None:
        match = next((c for c in state.get("choices", []) if c.get("id") == choice_id), None)
        if match is None:
            raise CapabilityError(f"playworld: unknown choice_id {choice_id!r} for current choices")
        action_text = action if action else match["label"]
    elif action:
        action_text = action
    else:
        raise CapabilityError("playworld: step requires an action or a choice_id")
    action_text = _require_text(action_text, "action")

    try:
        produced = narrator_fn(copy.deepcopy(state), action_text)
    except CapabilityError:
        raise
    except Exception as exc:
        raise CapabilityError(f"playworld: narrator_fn failed: {exc}") from exc

    if not isinstance(produced, dict):
        raise CapabilityError("playworld: narrator_fn must return an object")
    narration = _require_text(produced.get("narration"), "narrator narration")
    if "choices" not in produced:
        raise CapabilityError("playworld: narrator_fn result missing 'choices'")
    choices = _validate_choices(produced["choices"], "narrator choices")
    _apply_delta(state, produced.get("state_delta"))

    image_prompt = produced.get("image_prompt")
    if image_prompt is None:
        # Auto illustration hook: prompt text only, no image is generated.
        image_prompt = f"{state['setting']}; {state['location']}; {narration}"
    elif not isinstance(image_prompt, str):
        raise CapabilityError("playworld: image_prompt must be a string")

    state["turn"] = int(state.get("turn", 0)) + 1
    state["narration"] = narration
    state["choices"] = choices
    state["image_prompt"] = image_prompt
    state.setdefault("log", []).append(
        {"turn": state["turn"], "action": action_text, "choice_id": choice_id, "narration": narration}
    )
    _atomic_write_json(Path(path), state)
    return {
        "narration": narration,
        "choices": choices,
        "image_prompt": image_prompt,
        "turn": state["turn"],
        "state": state,
    }
