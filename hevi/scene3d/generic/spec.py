"""oskill: generic scene JSON - schema, normalisation, prompt 3-part gate.

Scene document (all lengths in world units, angles in degrees, time in seconds)::

  {
    "name": "boat_sea", "duration_s": 6, "fps": 24, "resolution": 360, "seed": 7,
    "prompt": {"subject": "海上的小船", "must_have": ["小船", "岛", "树"],
               "must_not": ["人物", "文字"]},
    "background": {"type": "gradient", "top": "#7ec8ff", "bottom": "#e8f6ff"},
    "fog": {"type": "linear", "color": "#cfe8ff", "near": 30, "far": 120},
    "lights": [{"type": "hemisphere", "sky": "#bfe3ff", "ground": "#406080", "intensity": 0.8},
               {"type": "directional", "position": [10, 20, 8], "intensity": 1.4, "cast_shadow": true}],
    "objects": [{"id": "boat", "type": "group", "tags": ["小船", "boat"], "children": [...],
                 "anim": {"bob": {"amp": 0.15, "freq": 0.4}}}],
    "camera": {"aspect": "16:9", "fov": 45,
               "path": {"points": [[...]], "closed": false, "curve": "centripetal",
                        "lookahead": 0.03, "look_at": [0, 0, 0], "look_at_blend": 0.7,
                        "ease": "in_out"},
               "fov_keys": [{"t": 0, "fov": 50}], "roll_keys": [{"t": 0, "deg": 0}]}
  }

Prompt gate: every ``must_have`` term must match an object's id/type/tags
(recursive), and no ``must_not`` term may match any object - otherwise
:class:`SceneError`.  This makes the three-part prompt a hard contract instead of
free text.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Iterator

try:
    import jsonschema
except Exception:  # pragma: no cover
    jsonschema = None


class SceneError(ValueError):
    pass


PRIMITIVES = ("box", "sphere", "cylinder", "cone", "plane", "torus", "icosahedron",
              "dodecahedron", "octahedron", "capsule", "circle", "ring")
OBJECT_TYPES = PRIMITIVES + ("gltf", "group", "water", "points")
MATERIALS = ("standard", "toon", "lambert", "phong", "basic", "physical")
LIGHTS = ("ambient", "hemisphere", "directional", "point", "spot")
ASPECTS = {"16:9": 16 / 9, "9:16": 9 / 16, "1:1": 1.0, "21:9": 21 / 9, "4:3": 4 / 3, "3:4": 3 / 4}

_V3 = {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3}
_COLOR = {"type": "string", "pattern": "^#[0-9a-fA-F]{6}$"}
_NUM_OR_V3 = {"oneOf": [{"type": "number"}, _V3]}

_MATERIAL = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "type": {"enum": list(MATERIALS)}, "color": _COLOR, "emissive": _COLOR,
        "emissive_intensity": {"type": "number", "minimum": 0},
        "roughness": {"type": "number", "minimum": 0, "maximum": 1},
        "metalness": {"type": "number", "minimum": 0, "maximum": 1},
        "opacity": {"type": "number", "minimum": 0, "maximum": 1},
        "flat_shading": {"type": "boolean"}, "wireframe": {"type": "boolean"},
        "side": {"enum": ["front", "back", "double"]},
    },
}
_ANIM = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "bob": {"type": "object", "properties": {"amp": {"type": "number"}, "freq": {"type": "number"}, "phase": {"type": "number"}}},
        "rock": {"type": "object", "properties": {"amp_deg": {"type": "number"}, "freq": {"type": "number"}, "phase": {"type": "number"}, "axis": {"enum": ["x", "y", "z"]}}},
        "spin": {"type": "object", "properties": {"speed_deg": {"type": "number"}, "axis": {"enum": ["x", "y", "z"]}}},
        "keyframes": {"type": "array", "items": {"type": "object", "required": ["t"],
                      "properties": {"t": {"type": "number"}, "position": _V3, "rotation": _V3, "scale": _NUM_OR_V3}}},
    },
}
_OBJECT: dict[str, Any] = {
    "type": "object", "additionalProperties": False, "required": ["type"],
    "properties": {
        "id": {"type": "string"}, "type": {"enum": list(OBJECT_TYPES)},
        "tags": {"type": "array", "items": {"type": "string"}},
        "params": {"type": "object"}, "src": {"type": "string"},
        "fit_height": {"type": "number", "exclusiveMinimum": 0},
        "position": _V3, "rotation": _V3, "scale": _NUM_OR_V3,
        "material": _MATERIAL, "anim": _ANIM,
        "cast_shadow": {"type": "boolean"}, "receive_shadow": {"type": "boolean"},
        "children": {"type": "array", "items": {"$ref": "#/$defs/object"}},
    },
}
_KEYS = lambda field: {"type": "array", "items": {"type": "object", "required": ["t", field],
                       "properties": {"t": {"type": "number", "minimum": 0}, field: {"type": "number"},
                                      "ease": {"enum": ["linear", "in_out", "in", "out"]}}}}
SCHEMA: dict[str, Any] = {
    "$defs": {"object": _OBJECT},
    "type": "object", "additionalProperties": False,
    "required": ["objects", "camera"],
    "properties": {
        "name": {"type": "string", "pattern": "^[A-Za-z0-9_.-]+$"},
        "template": {"type": "string"},
        "duration_s": {"type": "number", "minimum": 0.1, "maximum": 600},
        "fps": {"type": "integer", "minimum": 1, "maximum": 60},
        "resolution": {"type": "integer", "minimum": 64, "maximum": 2160},
        "seed": {"type": "integer"},
        "prompt": {"type": "object", "additionalProperties": False,
                   "properties": {"subject": {"type": "string"},
                                  "must_have": {"type": "array", "items": {"type": "string"}},
                                  "must_not": {"type": "array", "items": {"type": "string"}}}},
        "background": {"type": "object", "additionalProperties": False,
                       "properties": {"type": {"enum": ["color", "gradient"]}, "color": _COLOR,
                                      "top": _COLOR, "bottom": _COLOR}},
        "fog": {"type": "object", "additionalProperties": False,
                "properties": {"type": {"enum": ["none", "linear", "exp2"]}, "color": _COLOR,
                               "near": {"type": "number"}, "far": {"type": "number"},
                               "density": {"type": "number", "minimum": 0}}},
        "renderer": {"type": "object", "additionalProperties": False,
                     "properties": {"shadows": {"type": "boolean"}, "antialias": {"type": "boolean"},
                                    "tone_mapping": {"enum": ["none", "aces"]}, "exposure": {"type": "number"}}},
        "lights": {"type": "array", "items": {"type": "object", "required": ["type"], "additionalProperties": False,
                   "properties": {"type": {"enum": list(LIGHTS)}, "color": _COLOR, "sky": _COLOR, "ground": _COLOR,
                                  "intensity": {"type": "number", "minimum": 0}, "position": _V3, "target": _V3,
                                  "distance": {"type": "number"}, "angle_deg": {"type": "number"},
                                  "cast_shadow": {"type": "boolean"}}}},
        "objects": {"type": "array", "items": {"$ref": "#/$defs/object"}},
        "camera": {"type": "object", "additionalProperties": False, "required": ["path"],
                   "properties": {
                       "aspect": {"enum": list(ASPECTS)}, "fov": {"type": "number", "minimum": 5, "maximum": 150},
                       "near": {"type": "number", "exclusiveMinimum": 0}, "far": {"type": "number"},
                       "fov_keys": _KEYS("fov"), "roll_keys": _KEYS("deg"),
                       "path": {"type": "object", "additionalProperties": False, "required": ["points"],
                                "properties": {
                                    "points": {"type": "array", "items": _V3, "minItems": 2},
                                    "closed": {"type": "boolean"},
                                    "curve": {"enum": ["centripetal", "catmullrom", "chordal"]},
                                    "tension": {"type": "number"},
                                    "lookahead": {"type": "number", "minimum": 0, "maximum": 0.5},
                                    "look_at": {"oneOf": [_V3, {"type": "null"}]},
                                    "look_at_blend": {"type": "number", "minimum": 0, "maximum": 1},
                                    "ease": {"enum": ["linear", "in_out", "in", "out"]},
                                    "u_start": {"type": "number"}, "u_end": {"type": "number"}}}}},
    },
}

DEFAULTS: dict[str, Any] = {
    "name": "scene", "duration_s": 6.0, "fps": 24, "resolution": 360, "seed": 1,
    "prompt": {"subject": "", "must_have": [], "must_not": []},
    "background": {"type": "color", "color": "#000000"},
    "fog": {"type": "none"},
    "renderer": {"shadows": True, "antialias": True, "tone_mapping": "aces", "exposure": 1.0},
    "lights": [{"type": "hemisphere", "sky": "#ffffff", "ground": "#444444", "intensity": 1.0}],
}
CAMERA_DEFAULTS = {"aspect": "16:9", "fov": 45.0, "near": 0.1, "far": 1000.0, "fov_keys": [], "roll_keys": []}
PATH_DEFAULTS = {"closed": False, "curve": "centripetal", "tension": 0.5, "lookahead": 0.03,
                 "look_at": None, "look_at_blend": 1.0, "ease": "linear", "u_start": 0.0, "u_end": 1.0}


def iter_objects(objs: list[dict[str, Any]]) -> Iterator[dict[str, Any]]:
    for o in objs:
        yield o
        yield from iter_objects(o.get("children", []))


def _labels(o: dict[str, Any]) -> list[str]:
    return [s.lower() for s in [o.get("id", ""), o.get("type", ""), *o.get("tags", [])] if s]


def check_prompt(scene: dict[str, Any]) -> dict[str, Any]:
    """Prompt 3-part gate. Returns report; ``ok`` False when a term is missing/forbidden."""
    p = scene.get("prompt") or {}
    labels = [lab for o in iter_objects(scene.get("objects", [])) for lab in _labels(o)]
    def hit(term: str) -> list[str]:
        t = term.lower().strip()
        return [lab for lab in labels if t and (t == lab or t in lab)]
    missing = [t for t in p.get("must_have", []) if not hit(t)]
    forbidden = {t: hit(t) for t in p.get("must_not", []) if hit(t)}
    return {"subject": p.get("subject", ""), "must_have": list(p.get("must_have", [])),
            "must_not": list(p.get("must_not", [])), "missing": missing,
            "forbidden_found": forbidden, "ok": not missing and not forbidden}


def normalize_scene(doc: dict[str, Any], *, base_dir: str | Path | None = None,
                    enforce_prompt: bool = True) -> dict[str, Any]:
    """Validate + fill defaults. Resolves GLTF ``src`` relative to ``base_dir``."""
    if jsonschema is not None:
        try:
            jsonschema.validate(doc, SCHEMA)
        except jsonschema.ValidationError as exc:
            where = "/".join(str(x) for x in exc.absolute_path)
            raise SceneError(f"scene invalid at {where or '<root>'}: {exc.message}") from exc
    s = copy.deepcopy(DEFAULTS)
    for k, v in doc.items():
        if isinstance(v, dict) and isinstance(s.get(k), dict) and k not in ("background", "fog"):
            s[k] = {**s[k], **copy.deepcopy(v)}
        else:
            s[k] = copy.deepcopy(v)
    cam = {**CAMERA_DEFAULTS, **s["camera"]}
    cam["path"] = {**PATH_DEFAULTS, **cam["path"]}
    s["camera"] = cam
    if cam["path"]["closed"] and len(cam["path"]["points"]) < 3:
        raise SceneError("closed camera path needs >=3 points")
    ar = ASPECTS[cam["aspect"]]
    h = int(s["resolution"]) if ar >= 1 else round(int(s["resolution"]) / ar)
    w = round(h * ar)
    s["width"], s["height"] = w + (w % 2), h + (h % 2)  # yuv420p needs even dims
    base = Path(base_dir) if base_dir else None
    ids: set[str] = set()
    for i, o in enumerate(iter_objects(s["objects"])):
        o.setdefault("id", f"{o['type']}_{i}")
        if o["id"] in ids:
            raise SceneError(f"duplicate object id {o['id']!r}")
        ids.add(o["id"])
        if o["type"] == "gltf":
            src = o.get("src")
            if not src:
                raise SceneError(f"gltf object {o['id']!r} needs a local 'src' file")
            if "://" in src:
                raise SceneError(f"gltf object {o['id']!r}: only local files allowed, got {src!r}")
            pth = Path(src)
            if not pth.is_absolute() and base is not None:
                pth = base / pth
            if not pth.is_file():
                raise SceneError(f"gltf object {o['id']!r}: file not found: {pth}")
            if pth.suffix.lower() not in (".glb", ".gltf"):
                raise SceneError(f"gltf object {o['id']!r}: expected .glb/.gltf, got {pth.suffix}")
            o["src"] = str(pth.resolve())
    report = check_prompt(s)
    s["prompt_report"] = report
    if enforce_prompt and not report["ok"]:
        raise SceneError(f"prompt gate failed: missing={report['missing']} forbidden={report['forbidden_found']}")
    return s


def load_scene_json(path: str | Path, **kw: Any) -> dict[str, Any]:
    path = Path(path)
    doc = json.loads(path.read_text(encoding="utf-8"))
    from .templates import expand_template
    doc = expand_template(doc)
    return normalize_scene(doc, base_dir=kw.pop("base_dir", path.parent), **kw)
