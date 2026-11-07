"""Pure op schema + helpers (no bpy, no subprocess)."""
from __future__ import annotations

import copy
from typing import Any

OBJECT_TYPES = ("sphere", "cube", "cylinder", "cone", "plane", "torus", "text", "import")
LIGHT_TYPES = ("SUN", "AREA", "POINT", "SPOT")
IMPORT_EXT = (".obj", ".glb", ".gltf", ".fbx", ".stl", ".ply")
# engine presets: what "fast" means on a CPU-only box
ENGINE_PRESETS: dict[str, dict[str, Any]] = {
    "eevee": {"engine": "BLENDER_EEVEE_NEXT", "samples": 16},
    "cycles_fast": {"engine": "CYCLES", "samples": 8, "denoise": True},
    "cycles": {"engine": "CYCLES", "samples": 64, "denoise": True},
    "workbench": {"engine": "BLENDER_WORKBENCH"},
}
OPS = ("scene", "add", "material", "light", "camera", "keyframe", "delete",
       "render_frame", "render_animation", "info", "save_blend")
SCENE_OPS = set(OPS) - {"render_frame", "render_animation", "info", "save_blend"}


class OpError(ValueError):
    pass


def hex_to_rgb(v: Any) -> list[float]:
    if isinstance(v, (list, tuple)):
        if len(v) not in (3, 4):
            raise OpError(f"color needs 3/4 numbers: {v!r}")
        return [float(x) for x in v[:3]]
    s = str(v).lstrip("#")
    if len(s) != 6:
        raise OpError(f"bad hex color {v!r}")
    # sRGB hex -> linear
    out = []
    for i in (0, 2, 4):
        c = int(s[i:i + 2], 16) / 255.0
        out.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    return out


def _vec(v: Any, n: int = 3, name: str = "vec") -> list[float]:
    if isinstance(v, (int, float)) and name == "scale":
        return [float(v)] * 3
    if not isinstance(v, (list, tuple)) or len(v) != n:
        raise OpError(f"{name} must be {n} numbers, got {v!r}")
    return [float(x) for x in v]


def _need(op: dict, key: str) -> Any:
    if key not in op:
        raise OpError(f"op {op.get('op')!r} missing {key!r}")
    return op[key]


def validate_op(op: dict) -> dict:
    if not isinstance(op, dict) or op.get("op") not in OPS:
        raise OpError(f"unknown op: {op!r}; allowed {OPS}")
    o = copy.deepcopy(op)
    k = o["op"]
    for key in ("location", "rotation", "target"):
        if key in o and not (k == "keyframe" and key == "target") and not isinstance(o[key], str):
            o[key] = _vec(o[key], name=key)
    if "scale" in o:
        o["scale"] = _vec(o["scale"], name="scale")
    if "color" in o:
        o["color"] = hex_to_rgb(o["color"])
    if k == "scene":
        if "preset" in o:
            if o["preset"] not in ENGINE_PRESETS:
                raise OpError(f"preset must be one of {list(ENGINE_PRESETS)}")
            o = {**ENGINE_PRESETS[o["preset"]], **o}
        if "resolution" in o:
            r = o["resolution"]
            o["resolution"] = [int(x) + int(x) % 2 for x in _vec(r, 2, "resolution")]  # H264 needs even
        if "background" in o:
            o["background"] = hex_to_rgb(o["background"])
    elif k == "add":
        t = _need(o, "type")
        if t not in OBJECT_TYPES:
            raise OpError(f"type must be one of {OBJECT_TYPES}")
        _need(o, "name")
        if t == "text":
            _need(o, "text")
        if t == "import":
            p = str(_need(o, "path"))
            if not p.lower().endswith(IMPORT_EXT):
                raise OpError(f"import supports {IMPORT_EXT}")
    elif k == "material":
        _need(o, "target")
        o.setdefault("roughness", 0.9)
        o.setdefault("color", hex_to_rgb("#E8836B"))
    elif k == "light":
        _need(o, "name")
        o["type"] = str(o.get("type", "AREA")).upper()
        if o["type"] not in LIGHT_TYPES:
            raise OpError(f"light type must be {LIGHT_TYPES}")
    elif k == "keyframe":
        _need(o, "target")
        o["frame"] = int(_need(o, "frame"))
        if not any(x in o for x in ("location", "rotation", "scale")):
            raise OpError("keyframe needs location/rotation/scale")
    elif k == "delete":
        _need(o, "target")
    elif k in ("render_frame", "render_animation", "save_blend"):
        _need(o, "out")
        if k == "render_frame":
            o["frame"] = int(o.get("frame", 1))
    return o


def validate_ops(ops: list[dict]) -> list[dict]:
    if not isinstance(ops, list):
        raise OpError("ops must be a list")
    return [validate_op(x) for x in ops]


def clay_base_ops(preset: str = "eevee", resolution=(854, 480), fps: int = 24,
                  frames: int = 48, background: str = "#EADFCB") -> list[dict]:
    """Ground + key/fill light + camera: a ready clay stage."""
    return [
        {"op": "scene", "preset": preset, "resolution": list(resolution), "fps": fps,
         "frame_start": 1, "frame_end": frames, "background": background},
        {"op": "add", "type": "plane", "name": "Ground", "radius": 60},
        {"op": "material", "target": "Ground", "color": "#E8DCC8"},
        {"op": "light", "name": "Key", "type": "AREA", "location": [3, -3, 5],
         "energy": 120, "size": 5, "target": [0, 0, 0]},
        {"op": "light", "name": "Fill", "type": "SUN", "rotation": [50, 0, -120], "energy": 0.8},
        {"op": "camera", "location": [0, -7.5, 1.8], "target": [0, 0, 1.25], "lens": 32},
    ]


def bounce_keyframes(duration: float = 2.0, fps: int = 24, bounces: int = 2,
                     height: float = 2.0, radius: float = 0.5) -> list[dict]:
    """Squash-and-stretch bounce keyframes for object 'Ball'."""
    total = max(2, round(duration * fps))
    per = total / bounces
    kfs: list[dict] = []
    for b in range(bounces):
        f0 = 1 + round(b * per)
        top = 1 + round(b * per + per / 2)
        x0 = -1.5 + 3.0 * b / bounces
        xt = -1.5 + 3.0 * (b + 0.5) / bounces
        if b > 0:  # stretch just before impact
            kfs.append({"op": "keyframe", "target": "Ball", "frame": f0 - 2,
                        "location": [x0 - 0.1, 0, radius * 1.1], "scale": [0.9, 0.9, 1.2]})
        kfs.append({"op": "keyframe", "target": "Ball", "frame": f0,
                    "location": [x0, 0, radius * 0.7], "scale": [1.25, 1.25, 0.7]})
        kfs.append({"op": "keyframe", "target": "Ball", "frame": f0 + 2,
                    "location": [x0 + 0.1, 0, radius * 1.1], "scale": [0.9, 0.9, 1.2]})
        kfs.append({"op": "keyframe", "target": "Ball", "frame": top,
                    "location": [xt, 0, radius + height], "scale": [1, 1, 1]})
    kfs.append({"op": "keyframe", "target": "Ball", "frame": total - 2,
                "location": [1.4, 0, radius * 1.1], "scale": [0.9, 0.9, 1.2]})
    kfs.append({"op": "keyframe", "target": "Ball", "frame": total,
                "location": [1.5, 0, radius * 0.7], "scale": [1.25, 1.25, 0.7]})
    return kfs


def bounce_ball_ops(duration: float = 2.0, fps: int = 24, preset: str = "eevee",
                    resolution=(854, 480)) -> list[dict]:
    frames = max(2, round(duration * fps))
    return clay_base_ops(preset, resolution, fps, frames) + [
        {"op": "add", "type": "sphere", "name": "Ball", "location": [-1.5, 0, 0.5],
         "radius": 0.5, "segments": 48},
        {"op": "material", "target": "Ball", "color": "#E8836B"},
    ] + bounce_keyframes(duration, fps)
