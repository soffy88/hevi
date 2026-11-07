"""Named edit templates: ``edit.edit_template``.

Template counterpart of ``edit.edit_recipe`` (same data-only rule,
same save/load double validation, same movement / layer / SFX /
transition / rhythm checks), extended with the two choices a template
must make that a recipe does not:

* orientation: ``9:16`` (vertical) or ``16:9`` (horizontal). A
  template is selected against an aspect, and selection fails unless
  the template's declared orientation equals that aspect -- a vertical
  template is never silently applied to a horizontal render.
* shot kind: ``moving`` (a motion shot: exactly one registered camera
  movement, from the same 40-movement catalogue as
  ``edit.edit_recipe``) or ``static`` (a locked-off shot: no
  ``movement_id`` at all, and no movement layer either -- a static
  template that smuggles in a movement layer is rejected, same as a
  recipe layer that is itself a movement).

Preview renders a template into a readable shot-by-shot plan (one
entry per shot: orientation, kind, movement or "固定画面", layers,
transition, SFX, rhythm). Preview renders no video and calls no
generation API -- it is a plan the caller can read before committing
to a render.

A template is JSON data: it contains no code, and any key that smells
like code (``code`` / ``exec`` / ``eval`` / ``script`` / ``command``
/ ``shell`` / ``subprocess``) at any nesting level is rejected on
save and again on load, exactly like ``edit.edit_recipe``.

Mounting (item 4对照): same mount as ``edit.edit_recipe`` and
``talking_head.render`` -- register on the unified capability
registry, imported by ``hevi/capabilities/__init__.py``; the G13
completeness guard fails if the import is missing. The talking_head
line has no plugin/extension registry of its own (its stages are
direct imports), so no second mounting mechanism is built here.
"""

from __future__ import annotations

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
from hevi.capabilities.edit_recipes import load_sfx_layers
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_FORBIDDEN_KEYS = {"code", "exec", "eval", "script", "command", "shell", "subprocess"}
_TEMPLATE_KEYS = {
    "name", "description", "orientation", "shot_kind", "movement_id",
    "layer_ids", "transition", "sfx_ids", "rhythm",
}
ORIENTATIONS = {"9:16": "vertical", "16:9": "horizontal"}
SHOT_KINDS = ("static", "moving")
STATIC_LABEL = "固定画面"


def _reject_code_keys(node: Any, where: str = "template") -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if str(key) in _FORBIDDEN_KEYS:
                raise CapabilityError(
                    f"edit.edit_template: forbidden key {key!r} at {where}: "
                    "templates are data files and must not contain executable steps"
                )
            _reject_code_keys(value, f"{where}.{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            _reject_code_keys(value, f"{where}[{index}]")


def validate_template(template: dict[str, Any]) -> dict[str, Any]:
    """Validate a template dict; returns a normalized copy. Errors raise."""
    if not isinstance(template, dict):
        raise CapabilityError("edit.edit_template: template must be a dict")
    _reject_code_keys(template)
    unknown = sorted(set(template) - _TEMPLATE_KEYS)
    if unknown:
        raise CapabilityError(f"edit.edit_template: unknown template keys {unknown}")
    name = template.get("name")
    if not isinstance(name, str) or not _NAME_RE.match(name):
        raise CapabilityError(
            "edit.edit_template: name must match [a-z0-9][a-z0-9_-]{0,63} "
            "(lowercase, so template names are safe file names)"
        )
    orientation = template.get("orientation")
    if orientation not in ORIENTATIONS:
        raise CapabilityError(
            f"edit.edit_template: orientation must be one of "
            f"{sorted(ORIENTATIONS)}, got {orientation!r}"
        )
    shot_kind = template.get("shot_kind")
    if shot_kind not in SHOT_KINDS:
        raise CapabilityError(
            f"edit.edit_template: shot_kind must be one of "
            f"{list(SHOT_KINDS)}, got {shot_kind!r}"
        )
    known_movements = {row["id"] for row in load_movements()}
    movement_id = template.get("movement_id")
    if shot_kind == "static":
        if movement_id is not None:
            raise CapabilityError(
                "edit.edit_template: a static template must not carry a "
                f"movement_id (got {movement_id!r}); fixed shots have no camera move"
            )
    else:
        if not isinstance(movement_id, str) or not movement_id:
            raise CapabilityError(
                "edit.edit_template: a moving template requires exactly one movement_id"
            )
        if movement_id not in known_movements:
            raise CapabilityError(
                f"edit.edit_template: unknown movement id {movement_id!r}"
            )
    layer_ids = template.get("layer_ids", [])
    if not isinstance(layer_ids, list) or any(not isinstance(x, str) for x in layer_ids):
        raise CapabilityError("edit.edit_template: layer_ids must be a list of strings")
    for layer_id in layer_ids:
        technique = get_technique(layer_id)
        if technique.get("is_camera_movement"):
            raise CapabilityError(
                "edit.edit_template: layer "
                f"{layer_id!r} is itself a camera movement; a template "
                "takes at most one movement (movement_id for moving, none "
                "for static) and layers must not add another"
            )
    sfx_ids = template.get("sfx_ids", [])
    if not isinstance(sfx_ids, list) or any(not isinstance(x, str) for x in sfx_ids):
        raise CapabilityError("edit.edit_template: sfx_ids must be a list of strings")
    known_sfx = {row["id"] for row in load_sfx_layers()}
    unknown_sfx = [s for s in sfx_ids if s not in known_sfx]
    if unknown_sfx:
        raise CapabilityError(f"edit.edit_template: unknown sfx layer ids {unknown_sfx}")
    transition = template.get("transition", "cut")
    if transition not in ALLOWED_TRANSITIONS:
        raise CapabilityError(
            f"edit.edit_template: unknown transition {transition!r}; "
            f"want one of {list(ALLOWED_TRANSITIONS)}"
        )
    rhythm = template.get("rhythm", {})
    if not isinstance(rhythm, dict):
        raise CapabilityError("edit.edit_template: rhythm must be a dict")
    tempo = rhythm.get("tempo_bpm")
    if tempo is not None and (isinstance(tempo, bool) or not isinstance(tempo, (int, float)) or not 40 <= float(tempo) <= 240):
        raise CapabilityError("edit.edit_template: rhythm.tempo_bpm must be 40..240")
    cut_on_beat = rhythm.get("cut_on_beat", False)
    if not isinstance(cut_on_beat, bool):
        raise CapabilityError("edit.edit_template: rhythm.cut_on_beat must be a boolean")
    max_shot = rhythm.get("max_shot_sec")
    if max_shot is not None and (isinstance(max_shot, bool) or not isinstance(max_shot, (int, float)) or float(max_shot) <= 0):
        raise CapabilityError("edit.edit_template: rhythm.max_shot_sec must be > 0")
    return {
        "name": name,
        "description": template.get("description", ""),
        "orientation": orientation,
        "shot_kind": shot_kind,
        "movement_id": movement_id if shot_kind == "moving" else None,
        "layer_ids": list(layer_ids),
        "transition": transition,
        "sfx_ids": list(sfx_ids),
        "rhythm": {
            "tempo_bpm": tempo,
            "cut_on_beat": cut_on_beat,
            "max_shot_sec": max_shot,
        },
    }


def _template_path(store_dir: str | Path, name: str) -> Path:
    if not _NAME_RE.match(name):
        raise CapabilityError(f"edit.edit_template: invalid template name {name!r}")
    return Path(store_dir) / f"{name}.json"


def save_template(store_dir: str | Path, template: dict[str, Any]) -> str:
    """Validate and save a template as JSON; returns the file path."""
    normalized = validate_template(template)
    path = _template_path(store_dir, normalized["name"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(normalized, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    return str(path)


def load_template(store_dir: str | Path, name: str) -> dict[str, Any]:
    """Load a template file and re-validate it (hand edits get checked too)."""
    path = _template_path(store_dir, name)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise CapabilityError(f"edit.edit_template: cannot load template {name!r}: {exc}") from exc
    template = validate_template(raw)
    if template["name"] != name:
        raise CapabilityError(
            f"edit.edit_template: template file {name!r} names a different "
            f"template {template['name']!r}"
        )
    return template


def list_templates(store_dir: str | Path) -> list[str]:
    """Names of templates stored in a directory (sorted, no extension)."""
    directory = Path(store_dir)
    if not directory.is_dir():
        return []
    return sorted(p.stem for p in directory.glob("*.json") if _NAME_RE.match(p.stem))


def select_template(template: dict[str, Any], aspect: str) -> dict[str, Any]:
    """Validate a template and check its orientation against an aspect.

    A mismatch is an error, never a silent resize: a 9:16 template is
    not a 16:9 template.
    """
    normalized = validate_template(template)
    if aspect != normalized["orientation"]:
        raise CapabilityError(
            f"edit.edit_template: orientation mismatch: template "
            f"{normalized['name']!r} declares {normalized['orientation']} "
            f"({ORIENTATIONS[normalized['orientation']]}) but the requested "
            f"aspect is {aspect!r}"
        )
    return {
        "template": normalized,
        "aspect": aspect,
        "orientation_label": ORIENTATIONS[normalized["orientation"]],
        "matched": True,
    }


def preview_template(
    template: dict[str, Any], shots: list[dict[str, Any]], aspect: str
) -> dict[str, Any]:
    """Render a template into a readable shot-by-shot plan.

    No video is rendered and no generation API is called: the plan is
    text the caller reads before committing to a render. A shot list
    is required (an empty plan for an empty list would be a fake
    success).
    """
    selected = select_template(template, aspect)
    normalized = selected["template"]
    if not isinstance(shots, list) or not shots:
        raise CapabilityError("edit.edit_template: preview needs a non-empty shot list")
    movement = get_movement(normalized["movement_id"]) if normalized["movement_id"] else None
    layers = [get_technique(t) for t in normalized["layer_ids"]]
    sfx = [row for row in load_sfx_layers() if row["id"] in normalized["sfx_ids"]]
    plan_shots = []
    for shot in shots:
        shot_id = shot.get("shot_id") if isinstance(shot, dict) else None
        if not shot_id:
            raise CapabilityError("edit.edit_template: every shot needs a shot_id")
        plan_shots.append(
            {
                "shot_id": shot_id,
                "orientation": normalized["orientation"],
                "orientation_label": selected["orientation_label"],
                "shot_kind": normalized["shot_kind"],
                "movement_id": normalized["movement_id"],
                "movement": movement["movement"] if movement else STATIC_LABEL,
                "layer_ids": list(normalized["layer_ids"]),
                "layers": [layer["name_en"] for layer in layers],
                "transition": normalized["transition"],
                "sfx_ids": list(normalized["sfx_ids"]),
                "sfx": [row["id"] for row in sfx],
                "rhythm": dict(normalized["rhythm"]),
            }
        )
    return {
        "template_name": normalized["name"],
        "aspect": aspect,
        "orientation_label": selected["orientation_label"],
        "shot_kind": normalized["shot_kind"],
        "shot_count": len(plan_shots),
        "shots": plan_shots,
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    action = str(params.get("action") or "save")
    store_dir = params.get("store_dir") or str(Path(out_dir) / "templates")
    # An explicit aspect param wins; otherwise the render's own aspect
    # is the aspect the template is selected against.
    aspect_arg = str(params.get("aspect") or aspect)
    if action == "save":
        path = save_template(store_dir, dict(params["template"]))
        payload: dict[str, Any] = {"action": "save", "template": load_template(store_dir, params["template"]["name"]), "path": path}
    elif action == "get":
        payload = {"action": "get", "template": load_template(store_dir, str(params["name"]))}
    elif action == "list":
        payload = {"action": "list", "templates": list_templates(store_dir)}
    elif action == "select":
        template = load_template(store_dir, str(params["name"]))
        payload = {"action": "select", "selection": select_template(template, aspect_arg)}
    elif action == "preview":
        template = load_template(store_dir, str(params["name"]))
        payload = {"action": "preview", "plan": preview_template(template, list(params["shots"]), aspect_arg)}
    else:
        raise CapabilityError(f"edit.edit_template: unknown action {action!r}")
    report = Path(out_dir) / "edit_template.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report),
        qa={"report_json": str(report), **payload},
    )


def register_edit_template_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="edit.edit_template",
            kind="line",
            aspects=["16:9", "9:16", "1:1"],
            params_schema={
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["save", "get", "list", "select", "preview"]},
                    "store_dir": {"type": "string"},
                    "name": {"type": "string"},
                    "template": {"type": "object"},
                    "aspect": {"type": "string"},
                    "shots": {"type": "array", "items": {"type": "object"}},
                },
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Named edit templates: a tuned edit stored as JSON data "
                "(orientation 9:16 vertical / 16:9 horizontal, shot kind "
                "static / moving, one registered camera movement for "
                "moving only, technique layers, transition, SFX layers, "
                "rhythm). Selection fails on orientation mismatch and "
                "static templates must carry no movement; preview "
                "renders a readable shot-by-shot plan with no video and "
                "no generation call. Templates contain no executable "
                "code: code-like keys at any level are rejected."
            ),
            line="edit_assemble",
        )
    )
    return ["edit.edit_template"]


register_edit_template_capabilities_once()
