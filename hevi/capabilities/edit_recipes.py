"""Reusable edit recipes: a tuned edit, stored as data, reused by name.

A recipe is one tuned edit flow -- one camera movement, stackable
technique layers, one transition, SFX layer references, and rhythm
parameters -- saved under a name so the next video of the same kind
reuses it instead of re-tuning from scratch. A recipe is a JSON data
file: it contains no code, no file paths to execute, and no command
strings, and loading one never executes anything.

Validation on save (and again on load, so a hand-edited file cannot
sneak past the save-time check):
* exactly one camera movement, and it must exist in the
  ``shot.camera_movements`` catalogue (40 movements);
* every layer id must exist in ``shot.cinematic_techniques`` and must
  NOT itself be a camera movement (the one-shot-one-movement rule);
* every SFX id must exist in ``edit_recipes_data/sfx_layers.json``
  (layer categories, not concrete files -- see that file's note);
* the transition must be one of ``cut`` / ``dissolve`` / ``fade``
  (the same set ``story.edit_assemble`` accepts);
* rhythm parameters, when present, stay in range (tempo 40..240 BPM,
  shot lengths positive); unknown top-level keys are rejected, and
  any key that smells like code (``code``, ``exec``, ``eval``,
  ``script``, ``command``) anywhere in the document is rejected.

Applying a recipe to a shot list stamps the same movement, layers,
transition, SFX and rhythm onto every shot; it never changes a shot's
content or timing by itself -- timing still comes from the clips.

Written from scratch for hevi; the movement/technique catalogues are
hevi's own data files, read through ``cinematic_techniques``.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

from hevi.capabilities.cinematic_techniques import (
    get_movement,
    get_technique,
    load_movements,
)
from hevi.capabilities.edit_assemble import ALLOWED_TRANSITIONS
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False
_DATA_DIR = Path(__file__).resolve().parent / "edit_recipes_data"
_SFX_FILE = _DATA_DIR / "sfx_layers.json"
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_FORBIDDEN_KEYS = {"code", "exec", "eval", "script", "command", "shell", "subprocess"}
_RECIPE_KEYS = {"name", "description", "movement_id", "layer_ids", "transition", "sfx_ids", "rhythm"}


def load_sfx_layers() -> list[dict[str, Any]]:
    """SFX layer categories a recipe may reference."""
    try:
        return json.loads(_SFX_FILE.read_text(encoding="utf-8"))["layers"]
    except Exception as exc:
        raise CapabilityError(f"edit.edit_recipe: cannot load sfx_layers.json: {exc}") from exc


def _reject_code_keys(node: Any, where: str = "recipe") -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if str(key) in _FORBIDDEN_KEYS:
                raise CapabilityError(
                    f"edit.edit_recipe: forbidden key {key!r} at {where}: "
                    "recipes are data files and must not contain executable steps"
                )
            _reject_code_keys(value, f"{where}.{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            _reject_code_keys(value, f"{where}[{index}]")


def validate_recipe(recipe: dict[str, Any]) -> dict[str, Any]:
    """Validate a recipe dict; returns a normalized copy. Errors raise."""
    if not isinstance(recipe, dict):
        raise CapabilityError("edit.edit_recipe: recipe must be a dict")
    _reject_code_keys(recipe)
    unknown = sorted(set(recipe) - _RECIPE_KEYS)
    if unknown:
        raise CapabilityError(f"edit.edit_recipe: unknown recipe keys {unknown}")
    name = recipe.get("name")
    if not isinstance(name, str) or not _NAME_RE.match(name):
        raise CapabilityError(
            "edit.edit_recipe: name must match [a-z0-9][a-z0-9_-]{0,63} "
            "(lowercase, so recipe names are safe file names)"
        )
    # Exactly one movement, and it must exist in the catalogue.
    movement_id = recipe.get("movement_id")
    if not isinstance(movement_id, str) or not movement_id:
        raise CapabilityError("edit.edit_recipe: recipe requires exactly one movement_id")
    known_movements = {row["id"] for row in load_movements()}
    if movement_id not in known_movements:
        raise CapabilityError(f"edit.edit_recipe: unknown movement id {movement_id!r}")
    # Layers: must exist, and must not themselves be camera movements.
    layer_ids = recipe.get("layer_ids", [])
    if not isinstance(layer_ids, list) or any(not isinstance(x, str) for x in layer_ids):
        raise CapabilityError("edit.edit_recipe: layer_ids must be a list of strings")
    for layer_id in layer_ids:
        technique = get_technique(layer_id)  # raises on unknown id
        if technique.get("is_camera_movement"):
            raise CapabilityError(
                "edit.edit_recipe: layer "
                f"{layer_id!r} is itself a camera movement; a recipe takes "
                "exactly one movement (movement_id) and layers must not add another"
            )
    # SFX: every referenced layer category must exist.
    sfx_ids = recipe.get("sfx_ids", [])
    if not isinstance(sfx_ids, list) or any(not isinstance(x, str) for x in sfx_ids):
        raise CapabilityError("edit.edit_recipe: sfx_ids must be a list of strings")
    known_sfx = {row["id"] for row in load_sfx_layers()}
    unknown_sfx = [s for s in sfx_ids if s not in known_sfx]
    if unknown_sfx:
        raise CapabilityError(f"edit.edit_recipe: unknown sfx layer ids {unknown_sfx}")
    # Transition: same allowed set as story.edit_assemble.
    transition = recipe.get("transition", "cut")
    if transition not in ALLOWED_TRANSITIONS:
        raise CapabilityError(
            f"edit.edit_recipe: unknown transition {transition!r}; want one of {list(ALLOWED_TRANSITIONS)}"
        )
    # Rhythm: optional, but bounded when present.
    rhythm = recipe.get("rhythm", {})
    if not isinstance(rhythm, dict):
        raise CapabilityError("edit.edit_recipe: rhythm must be a dict")
    tempo = rhythm.get("tempo_bpm")
    if tempo is not None and (isinstance(tempo, bool) or not isinstance(tempo, (int, float)) or not 40 <= float(tempo) <= 240):
        raise CapabilityError("edit.edit_recipe: rhythm.tempo_bpm must be 40..240")
    cut_on_beat = rhythm.get("cut_on_beat", False)
    if not isinstance(cut_on_beat, bool):
        raise CapabilityError("edit.edit_recipe: rhythm.cut_on_beat must be a boolean")
    max_shot = rhythm.get("max_shot_sec")
    if max_shot is not None and (isinstance(max_shot, bool) or not isinstance(max_shot, (int, float)) or float(max_shot) <= 0):
        raise CapabilityError("edit.edit_recipe: rhythm.max_shot_sec must be > 0")
    normalized = {
        "name": name,
        "description": recipe.get("description", ""),
        "movement_id": movement_id,
        "layer_ids": list(layer_ids),
        "transition": transition,
        "sfx_ids": list(sfx_ids),
        "rhythm": {
            "tempo_bpm": tempo,
            "cut_on_beat": cut_on_beat,
            "max_shot_sec": max_shot,
        },
    }
    return normalized


def _recipe_path(store_dir: str | Path, name: str) -> Path:
    if not _NAME_RE.match(name):
        raise CapabilityError(f"edit.edit_recipe: invalid recipe name {name!r}")
    return Path(store_dir) / f"{name}.json"


def save_recipe(store_dir: str | Path, recipe: dict[str, Any]) -> str:
    """Validate and save a recipe as JSON; returns the file path."""
    normalized = validate_recipe(recipe)
    path = _recipe_path(store_dir, normalized["name"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(normalized, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    return str(path)


def load_recipe(store_dir: str | Path, name: str) -> dict[str, Any]:
    """Load a recipe file and re-validate it (hand edits get checked too)."""
    path = _recipe_path(store_dir, name)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise CapabilityError(f"edit.edit_recipe: cannot load recipe {name!r}: {exc}") from exc
    recipe = validate_recipe(raw)
    if recipe["name"] != name:
        raise CapabilityError(
            f"edit.edit_recipe: recipe file {name!r} names a different recipe {recipe['name']!r}"
        )
    return recipe


def list_recipes(store_dir: str | Path) -> list[str]:
    """Names of recipes stored in a directory (sorted, no extension)."""
    directory = Path(store_dir)
    if not directory.is_dir():
        return []
    return sorted(p.stem for p in directory.glob("*.json") if _NAME_RE.match(p.stem))


def apply_recipe(recipe: dict[str, Any], shots: list[dict[str, Any]]) -> dict[str, Any]:
    """Stamp a validated recipe onto a shot list; returns the edit plan.

    Each shot keeps its own id/content; the recipe supplies movement,
    layers, transition, SFX and rhythm only. A shot list is required
    (an empty plan for an empty list would be a fake success).
    """
    normalized = validate_recipe(recipe)
    if not isinstance(shots, list) or not shots:
        raise CapabilityError("edit.edit_recipe: apply needs a non-empty shot list")
    movement = get_movement(normalized["movement_id"])
    layers = [get_technique(t) for t in normalized["layer_ids"]]
    sfx = [row for row in load_sfx_layers() if row["id"] in normalized["sfx_ids"]]
    plan_shots = []
    for shot in shots:
        shot_id = shot.get("shot_id") if isinstance(shot, dict) else None
        if not shot_id:
            raise CapabilityError("edit.edit_recipe: every shot needs a shot_id")
        plan_shots.append({
            "shot_id": shot_id,
            "movement_id": normalized["movement_id"],
            "movement": movement["movement"],
            "layer_ids": list(normalized["layer_ids"]),
            "layers": [layer["name_en"] for layer in layers],
            "transition": normalized["transition"],
            "sfx_ids": list(normalized["sfx_ids"]),
            "sfx": [row["id"] for row in sfx],
            "rhythm": dict(normalized["rhythm"]),
        })
    return {"recipe_name": normalized["name"], "shots": plan_shots}


def _render(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    action = str(params.get("action") or "save")
    store_dir = params.get("store_dir") or str(Path(out_dir) / "recipes")
    if action == "save":
        path = save_recipe(store_dir, dict(params["recipe"]))
        payload: dict[str, Any] = {"action": "save", "recipe": load_recipe(store_dir, params["recipe"]["name"]), "path": path}
    elif action == "get":
        payload = {"action": "get", "recipe": load_recipe(store_dir, str(params["name"]))}
    elif action == "list":
        payload = {"action": "list", "recipes": list_recipes(store_dir)}
    elif action == "apply":
        recipe = load_recipe(store_dir, str(params["name"]))
        payload = {"action": "apply", "plan": apply_recipe(recipe, list(params["shots"]))}
    else:
        raise CapabilityError(f"edit.edit_recipe: unknown action {action!r}")
    report = Path(out_dir) / "edit_recipe.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report),
        qa={"report_json": str(report), **payload},
    )


def register_edit_recipe_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="edit.edit_recipe",
            kind="line",
            aspects=["16:9", "9:16", "1:1"],
            params_schema={
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["save", "get", "list", "apply"]},
                    "store_dir": {"type": "string"},
                    "name": {"type": "string"},
                    "recipe": {"type": "object"},
                    "shots": {"type": "array", "items": {"type": "object"}},
                },
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Reusable edit recipes: a tuned edit (one movement, "
                "technique layers, transition, SFX layers, rhythm) saved "
                "as a named JSON data file and reused on the next video "
                "of the same kind. Saving and loading both validate: an "
                "unknown movement or SFX layer is an error, and recipes "
                "contain no executable code."
            ),
            line="edit_assemble",
        )
    )
    return ["edit.edit_recipe"]


register_edit_recipe_capabilities_once()
