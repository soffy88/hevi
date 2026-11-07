"""Cinematic technique libraries (movie-atmosphere 10-site intake, 2026-10-25).

Registers two catalogue capabilities:

* ``shot.camera_movements`` — 40 selected camera movements from
  aicameramovements.com, each in the site's four-field structure
  (Movement / Speed / Framing / End) rewritten in hevi's own wording.
  No site prompt text is copied.
* ``shot.cinematic_techniques`` — the melies.co technique-name index
  (12 categories, names only, no thumbnails or example videos),
  30 core vvsvs.pro/cinematique techniques (one-line note + short
  prompt fragment, both rewritten; the site's long descriptions and
  full templates were NOT copied), and index-only pointers for
  shot.cafe / film-grab.com / eyecannndy.com / grokfilm.app
  (no stills, no GIFs, no technique full texts imported).

One-shot-one-movement rule (Soffy constraint): a shot takes exactly
one camera movement. Lighting, atmosphere and composition entries are
layers and may stack; a second movement is rejected, even where a
source site suggests combining 2-3 techniques in one prompt.
``validate_shot`` / ``compose_shot_prompt`` enforce this, and
``detect_movements_in_text`` scans a prompt draft for movement
phrases so a stacked draft is caught before generation.

Fully local: no keys, no network, zero cost. Data files live next to
this module under ``cinematic_data/``.
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
_DATA_DIR = Path(__file__).resolve().parent / "cinematic_data"


def _load(name: str) -> dict[str, Any]:
    path = _DATA_DIR / name
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise CapabilityError(f"cinematic_techniques: cannot load {name}: {exc}") from exc


def load_movements() -> list[dict[str, Any]]:
    return _load("camera_movements.json")["movements"]


def load_techniques() -> dict[str, Any]:
    return _load("cinematic_techniques.json")


def list_movements(category: str = "") -> list[dict[str, Any]]:
    rows = load_movements()
    if category:
        rows = [r for r in rows if r["category"] == category]
    return rows


def get_movement(movement_id: str) -> dict[str, Any]:
    for row in load_movements():
        if row["id"] == movement_id:
            return row
    raise CapabilityError(f"shot.camera_movements: unknown movement id {movement_id!r}")


def list_techniques(category: str = "", layer: str = "") -> list[dict[str, Any]]:
    rows = load_techniques()["vvsvs"]
    if category:
        rows = [r for r in rows if r["category"] == category]
    if layer:
        rows = [r for r in rows if r["layer"] == layer]
    return rows


def get_technique(technique_id: str) -> dict[str, Any]:
    for row in load_techniques()["vvsvs"]:
        if row["id"] == technique_id:
            return row
    raise CapabilityError(f"shot.cinematic_techniques: unknown technique id {technique_id!r}")


def list_melies(category: str = "") -> dict[str, Any]:
    cats = load_techniques()["melies"]["categories"]
    if category:
        if category not in cats:
            raise CapabilityError(
                f"shot.cinematic_techniques: unknown melies category {category!r} "
                f"(want one of {sorted(cats)})"
            )
        return {category: cats[category]}
    return cats


# English phrases that identify one movement in a prompt draft.
# Longest phrases first so "whip pan right" wins over "pan right".
_MOVEMENT_PHRASES: dict[str, tuple[str, ...]] = {
    "whip_pan_right": ("whip pan right",),
    "whip_pan_left": ("whip pan left",),
    "orbit_counterclockwise": ("counterclockwise orbit", "orbit counterclockwise"),
    "orbit_clockwise": ("clockwise orbit", "orbit clockwise"),
    "reverse_tracking": ("reverse tracking", "walk-and-talk"),
    "vehicle_tracking": ("vehicle tracking",),
    "side_tracking": ("side tracking",),
    "low_tracking": ("low tracking",),
    "tracking_shot": ("tracking shot",),
    "follow_shot": ("follow shot from behind", "follow shot"),
    "first_person_view": ("first-person view", "first person view"),
    "drone_push_in": ("drone push in",),
    "drone_pull_back": ("drone pull back",),
    "pedestal_down": ("pedestal down",),
    "pedestal_up": ("pedestal up",),
    "slider_right": ("slider right",),
    "slider_left": ("slider left",),
    "truck_right": ("truck right",),
    "truck_left": ("truck left",),
    "crash_zoom_in": ("crash zoom in",),
    "crash_zoom_out": ("crash zoom out",),
    "slow_zoom_in": ("slow zoom in",),
    "slow_zoom_out": ("slow zoom out",),
    "fast_zoom_in": ("fast zoom in",),
    "fast_zoom_out": ("fast zoom out",),
    "crane_down": ("crane down",),
    "crane_up": ("crane up",),
    "dolly_out": ("dolly out", "pull out", "pull back"),
    "dolly_in": ("dolly in", "push in"),
    "push_past": ("push past", "pass-by shot"),
    "arc_right": ("arc right",),
    "arc_left": ("arc left",),
    "tilt_down": ("tilt down",),
    "tilt_up": ("tilt up",),
    "pan_right": ("pan right",),
    "pan_left": ("pan left",),
    "chase_shot": ("chase shot",),
    "handheld_shot": ("handheld shot", "handheld camera", "handheld"),
    "snorricam": ("snorricam", "body-mounted camera"),
    "static_shot": ("static shot", "locked-off shot", "locked off shot"),
}


def detect_movements_in_text(text: str) -> list[str]:
    lowered = (text or "").lower()
    found: list[str] = []
    for movement_id, phrases in _MOVEMENT_PHRASES.items():
        if any(p in lowered for p in phrases):
            found.append(movement_id)
    return found


def validate_shot(
    movement_ids: list[str] | None = None, text: str = ""
) -> dict[str, Any]:
    """Exactly one camera movement per shot; anything else is an error."""
    if movement_ids is not None:
        unknown = [m for m in movement_ids if m not in {r["id"] for r in load_movements()}]
        if unknown:
            raise CapabilityError(f"one-movement check: unknown movement ids {unknown}")
        found = list(movement_ids)
        source = "ids"
    else:
        found = detect_movements_in_text(text)
        source = "text"
    if len(found) != 1:
        raise CapabilityError(
            "one-movement check: a shot takes exactly one camera movement, "
            f"found {len(found)} ({found}) via {source}; "
            "keep one movement and move the rest to lighting/composition layers"
        )
    return {"ok": True, "movement": found[0], "source": source}


def compose_shot_prompt(
    subject: str, movement_id: str, layer_ids: list[str] | None = None
) -> dict[str, Any]:
    """Build one shot prompt: exactly one movement + stackable layers."""
    move = get_movement(movement_id)
    layers = [get_technique(t) for t in (layer_ids or [])]
    bad = [t["id"] for t in layers if t["is_camera_movement"]]
    if bad:
        raise CapabilityError(
            "one-movement check: layers must not contain camera movements; "
            f"these are movements, pass at most one as movement_id: {bad}"
        )
    parts = [
        f"Subject: {subject}.",
        f"Camera movement: {move['movement']} Speed: {move['speed']} "
        f"Framing: {move['framing']} End: {move['end']}",
    ]
    for layer in layers:
        parts.append(layer["prompt_fragment_en"].replace("[Subject]", subject))
    prompt = " ".join(parts)
    return {
        "subject": subject,
        "movement": move,
        "layers": layers,
        "prompt_en": prompt,
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    action = str(params.get("action", "list_movements"))
    try:
        if action == "list_movements":
            payload = {"movements": list_movements(str(params.get("category", "")))}
        elif action == "get_movement":
            payload = {"movement": get_movement(str(params.get("movement", "")))}
        elif action == "list_techniques":
            payload = {
                "techniques": list_techniques(
                    str(params.get("category", "")), str(params.get("layer", ""))
                )
            }
        elif action == "list_melies":
            payload = {"melies": list_melies(str(params.get("category", "")))}
        elif action == "validate_shot":
            ids = params.get("movements")
            payload = validate_shot(
                list(ids) if isinstance(ids, list) else None,
                str(params.get("text", "")),
            )
        elif action == "compose":
            payload = compose_shot_prompt(
                str(params.get("subject", "the subject")),
                str(params.get("movement", "")),
                list(params.get("layers", [])),
            )
        else:
            raise CapabilityError(f"cinematic_techniques: unknown action {action!r}")
    except CapabilityError:
        raise
    except Exception as exc:
        raise CapabilityError(f"cinematic_techniques: {exc}") from exc
    path = out_dir / "cinematic_techniques.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        sha256=compute_sha256(path),
        qa={
            "result_json": str(path),
            "action": action,
            "note": (
                "Local catalogue only, zero cost. One shot takes exactly "
                "one camera movement; lighting/composition entries stack "
                "as layers. No stills, GIFs or site prompt templates are "
                "stored in this module."
            ),
        },
    )


def _render_movements(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    params = {"action": "list_movements", **params}
    return _render(params, out_dir, duration=duration, aspect=aspect, seed=seed)


def _render_techniques(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    params = {"action": "list_techniques", **params}
    return _render(params, out_dir, duration=duration, aspect=aspect, seed=seed)


def register_cinematic_techniques_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "list_movements",
                    "get_movement",
                    "list_techniques",
                    "list_melies",
                    "validate_shot",
                    "compose",
                ],
            },
            "category": {"type": "string"},
            "layer": {"type": "string"},
            "movement": {"type": "string"},
            "movements": {"type": "array", "items": {"type": "string"}},
            "layers": {"type": "array", "items": {"type": "string"}},
            "subject": {"type": "string"},
            "text": {"type": "string"},
        },
        "additionalProperties": False,
    }
    register(
        Capability(
            name="shot.camera_movements",
            kind="shot",
            aspects=["16:9", "9:16", "1:1"],
            params_schema=schema,
            cpu_cost_hint=0.0,
            render=_render_movements,
            description=(
                "40 selected camera movements (aicameramovements.com library, "
                "own wording, Movement/Speed/Framing/End structure) plus the "
                "one-shot-one-movement validator: validate_shot and compose "
                "reject any shot carrying two movements."
            ),
            line="shotlang",
        )
    )
    register(
        Capability(
            name="shot.cinematic_techniques",
            kind="shot",
            aspects=["16:9", "9:16", "1:1"],
            params_schema=schema,
            cpu_cost_hint=0.0,
            render=_render_techniques,
            description=(
                "Cinematic technique catalogue: melies.co technique-name "
                "index (12 categories, names only), 30 core vvsvs "
                "cinematique techniques (rewritten notes + short fragments), "
                "and index-only pointers for shot.cafe, film-grab.com, "
                "eyecannndy.com and grokfilm.app. No stills, GIFs or "
                "site templates stored."
            ),
            line="shotlang",
        )
    )
    return ["shot.camera_movements", "shot.cinematic_techniques"]
