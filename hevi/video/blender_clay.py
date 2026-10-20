"""Blender clay-style 3D rendering helpers (headless, CPU-only).

This module is the engine layer behind the ``video.blender_clay_render``
capability (see ``hevi/capabilities/blender_clay.py``).  It deliberately
contains *no* ``bpy`` import: ``bpy`` only exists inside Blender's own Python
interpreter.  Instead this module

* locates a Blender binary (``$HEVI_BLENDER_BIN`` / ``$BLENDER_BIN`` / PATH /
  the known per-user installs on this machine),
* computes animation keyframes and resolutions with pure functions (unit
  testable without Blender), and
* generates a deterministic, self-contained ``bpy`` script
  (:func:`build_bpy_script`) that the capability runs as
  ``blender --background --python <script>``.

Scene look ("clay"): Principled BSDF with roughness 0.9, zero metallic, soft
pastel colours, one large area light.  No GPU is assumed anywhere: the
generated script forces Cycles on CPU.
"""

from __future__ import annotations

import json
import math
import os
import shutil
from pathlib import Path
from typing import Any

from hevi.capabilities.errors import CapabilityError

__all__ = [
    "KNOWN_BLENDER_PATHS",
    "MOTIONS",
    "PALETTES",
    "PRESETS",
    "build_bpy_script",
    "build_config",
    "compute_keyframes",
    "find_blender",
    "frame_count_for",
    "hex_to_rgb",
    "resolve_resolution",
]

# Blender is *not* on PATH on ubuntu26 (``which blender`` is empty); these are
# the two real per-user installs verified on the machine, newest first.
KNOWN_BLENDER_PATHS: tuple[str, ...] = (
    "~/.local/blender/blender",  # Blender 4.2.17 LTS (verified 2026-10-20)
    "~/opt/blender/blender",  # Blender 4.1.1 (older fallback)
    "/usr/bin/blender",
    "/usr/local/bin/blender",
)

PRESETS: tuple[str, ...] = ("ball_character", "clay_blocks")
MOTIONS: tuple[str, ...] = ("bounce", "slide_turn")

# Soft clay palettes. ``body`` is the hero colour, ``accent`` the secondary
# clay colour, ``ground`` / ``background`` the set.
PALETTES: dict[str, dict[str, str]] = {
    "warm": {
        "body": "#E8836B",
        "accent": "#F2C063",
        "detail": "#3A3238",
        "ground": "#E8DCC8",
        "background": "#F3EAD8",
    },
    "mint": {
        "body": "#6FBF9B",
        "accent": "#F2D06B",
        "detail": "#2F3A36",
        "ground": "#DCE8DC",
        "background": "#EAF3EA",
    },
    "sky": {
        "body": "#6FA8C9",
        "accent": "#F28C6B",
        "detail": "#2E3440",
        "ground": "#DDE3E8",
        "background": "#E8EEF3",
    },
}

_BASE_RESOLUTIONS: dict[str, tuple[int, int]] = {
    "480p": (854, 480),
    "540p": (960, 540),
}


def find_blender(explicit: str | None = None) -> str | None:
    """Return the path of a usable Blender binary, or ``None``.

    Search order: explicit argument, ``$HEVI_BLENDER_BIN``, ``$BLENDER_BIN``,
    ``PATH``, then :data:`KNOWN_BLENDER_PATHS`.  A candidate only counts when
    it is an existing executable file.
    """
    candidates: list[str] = []
    if explicit:
        candidates.append(explicit)
    for env_name in ("HEVI_BLENDER_BIN", "BLENDER_BIN"):
        value = os.environ.get(env_name, "").strip()
        if value:
            candidates.append(value)
    on_path = shutil.which("blender")
    if on_path:
        candidates.append(on_path)
    candidates.extend(KNOWN_BLENDER_PATHS)
    for cand in candidates:
        path = Path(cand).expanduser()
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
    return None


def resolve_resolution(resolution: str, aspect: str) -> tuple[int, int]:
    """Map a resolution label + aspect to ``(width, height)`` pixels."""
    if resolution not in _BASE_RESOLUTIONS:
        raise CapabilityError(
            f"blender_clay: unsupported resolution {resolution!r} "
            f"(supported: {sorted(_BASE_RESOLUTIONS)})"
        )
    width, height = _BASE_RESOLUTIONS[resolution]
    if aspect == "16:9":
        return width, height
    if aspect == "9:16":
        return height, width
    if aspect == "1:1":
        return height, height
    raise CapabilityError(
        f"blender_clay: unsupported aspect {aspect!r} (supported: 16:9, 9:16, 1:1)"
    )


def frame_count_for(duration: float, fps: int) -> int:
    """Number of frames for ``duration`` seconds at ``fps`` (>= 1)."""
    if duration <= 0:
        raise CapabilityError(f"blender_clay: duration must be positive, got {duration}")
    if fps <= 0:
        raise CapabilityError(f"blender_clay: fps must be positive, got {fps}")
    return max(1, round(duration * fps))


def hex_to_rgb(value: str) -> tuple[float, float, float]:
    """Convert ``#RRGGBB`` to a linear-ish ``(r, g, b)`` tuple in 0..1."""
    text = value.strip().lstrip("#")
    if len(text) != 6:
        raise CapabilityError(f"blender_clay: bad hex colour {value!r}")
    try:
        r, g, b = (int(text[i : i + 2], 16) / 255.0 for i in (0, 2, 4))
    except ValueError as exc:
        raise CapabilityError(f"blender_clay: bad hex colour {value!r}") from exc
    return (round(r, 6), round(g, 6), round(b, 6))


def compute_keyframes(
    total_frames: int,
    fps: int,
    motion: str,
    *,
    base_z: float = 1.05,
    step: int = 3,
) -> list[dict[str, Any]]:
    """Pure animation curve for the hero group.

    Returns a list of ``{frame, location:[x,y,z], rotation_z}`` dicts covering
    frame 1 and frame ``total_frames`` exactly.  ``bounce`` lifts the hero with
    ``abs(sin(...))`` hops; ``slide_turn`` glides it left-to-right while it
    turns (rotation around Z, the up axis in this scene's framing).
    """
    if motion not in MOTIONS:
        raise CapabilityError(
            f"blender_clay: unsupported motion {motion!r} (supported: {list(MOTIONS)})"
        )
    if total_frames < 1:
        raise CapabilityError(f"blender_clay: total_frames must be >= 1, got {total_frames}")
    frames = sorted({1, total_frames, *range(1, total_frames + 1, max(1, step))})
    out: list[dict[str, Any]] = []
    for frame in frames:
        t = frame - 1
        span = max(1, total_frames - 1)
        if motion == "bounce":
            period = max(6.0, fps * 0.8)
            z = base_z + 0.85 * abs(math.sin(math.pi * t / period))
            x = 0.0
            rot_z = 0.12 * math.sin(2.0 * math.pi * t / period)
        else:  # slide_turn
            frac = t / span
            z = base_z + 0.08 * math.sin(frac * math.pi)
            x = -1.6 + 3.2 * frac
            rot_z = -0.35 + 0.7 * frac
        out.append(
            {
                "frame": int(frame),
                "location": [round(x, 6), 0.0, round(z, 6)],
                "rotation_z": round(rot_z, 6),
            }
        )
    return out


def build_config(
    *,
    preset: str = "ball_character",
    motion: str = "bounce",
    palette: str = "warm",
    resolution: str = "480p",
    aspect: str = "9:16",
    fps: int = 24,
    samples: int = 32,
    duration: float = 2.5,
    seed: int = 42,
    frames_dir: str = "",
) -> dict[str, Any]:
    """Validate knobs and build the JSON-serialisable scene config."""
    if preset not in PRESETS:
        raise CapabilityError(
            f"blender_clay: unsupported preset {preset!r} (supported: {list(PRESETS)})"
        )
    if palette not in PALETTES:
        raise CapabilityError(
            f"blender_clay: unsupported palette {palette!r} (supported: {sorted(PALETTES)})"
        )
    width, height = resolve_resolution(resolution, aspect)
    total = frame_count_for(duration, fps)
    colours = {name: hex_to_rgb(hexv) for name, hexv in PALETTES[palette].items()}
    return {
        "preset": preset,
        "motion": motion,
        "palette": palette,
        "resolution_label": resolution,
        "aspect": aspect,
        "width": width,
        "height": height,
        "fps": int(fps),
        "samples": int(samples),
        "duration_s": float(duration),
        "seed": int(seed),
        "frame_start": 1,
        "frame_end": total,
        "total_frames": total,
        "colours": {k: list(v) for k, v in colours.items()},
        "keyframes": compute_keyframes(total, int(fps), motion),
        "frames_dir": frames_dir,
        "roughness": 0.9,
        "metallic": 0.0,
    }


_BPY_TEMPLATE = '''# Auto-generated by hevi.video.blender_clay.build_bpy_script - do not edit.
# Self-contained clay scene for: blender --background --python this_file.py
import json
import math

import bpy
from mathutils import Vector

CONFIG = json.loads(r\'\'\'__CONFIG_JSON__\'\'\')
CFG = CONFIG


def make_clay(name, rgb, roughness=0.9):
    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (rgb[0], rgb[1], rgb[2], 1.0)
    bsdf.inputs["Roughness"].default_value = float(CFG.get("roughness", roughness))
    bsdf.inputs["Metallic"].default_value = float(CFG.get("metallic", 0.0))
    if "Specular IOR Level" in bsdf.inputs:
        bsdf.inputs["Specular IOR Level"].default_value = 0.25
    return mat


def look_at(obj, target):
    direction = Vector(target) - obj.location
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def add_sphere(name, loc, scale, mat, parent=None):
    bpy.ops.mesh.primitive_uv_sphere_add(
        segments=32, ring_count=16, location=loc
    )
    obj = bpy.context.active_object
    obj.name = name
    obj.scale = scale
    for poly in obj.data.polygons:
        poly.use_smooth = True
    if mat is not None:
        obj.data.materials.append(mat)
    if parent is not None:
        obj.parent = parent
    return obj


def add_clay_block(name, loc, scale, rot_z, mat, parent=None):
    bpy.ops.mesh.primitive_cube_add(location=loc)
    obj = bpy.context.active_object
    obj.name = name
    obj.scale = scale
    obj.rotation_euler = (0.0, 0.0, rot_z)
    bevel = obj.modifiers.new(name="clay_soft_edges", type="BEVEL")
    bevel.width = 0.09
    bevel.segments = 3
    if mat is not None:
        obj.data.materials.append(mat)
    if parent is not None:
        obj.parent = parent
    return obj


def main():
    # Clean slate.
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for block in (bpy.data.meshes, bpy.data.curves, bpy.data.cameras, bpy.data.lights):
        pass  # leftover datablocks are harmless for a one-shot render

    scene = bpy.context.scene
    colours = CFG["colours"]

    # World: soft solid background.
    world = bpy.data.worlds.new("ClayWorld") if not bpy.data.worlds else bpy.data.worlds[0]
    scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bgc = colours["background"]
    bg.inputs[0].default_value = (bgc[0], bgc[1], bgc[2], 1.0)
    bg.inputs[1].default_value = 1.0

    mats = {
        key: make_clay(f"clay_{key}", value)
        for key, value in colours.items()
    }

    # Ground.
    bpy.ops.mesh.primitive_plane_add(size=40.0, location=(0.0, 0.0, 0.0))
    ground = bpy.context.active_object
    ground.name = "ClayGround"
    ground.data.materials.append(mats["ground"])

    # Hero group (animated via keyframes on this empty).
    hero = bpy.data.objects.new("Hero", None)
    scene.collection.objects.link(hero)
    hero.location = (0.0, 0.0, 1.05)

    if CFG["preset"] == "ball_character":
        add_sphere("Body", (0.0, 0.0, 0.0), (0.95, 0.9, 1.0), mats["body"], hero)
        add_sphere("EyeL", (-0.32, -0.82, 0.28), (0.09, 0.09, 0.11), mats["detail"], hero)
        add_sphere("EyeR", (0.32, -0.82, 0.28), (0.09, 0.09, 0.11), mats["detail"], hero)
        add_sphere("CheekL", (-0.55, -0.78, 0.02), (0.14, 0.06, 0.10), mats["accent"], hero)
        add_sphere("CheekR", (0.55, -0.78, 0.02), (0.14, 0.06, 0.10), mats["accent"], hero)
        add_sphere("TopKnot", (0.0, 0.0, 1.05), (0.22, 0.22, 0.22), mats["accent"], hero)
    else:  # clay_blocks
        add_clay_block("BlockA", (0.0, 0.0, 0.35), (0.85, 0.85, 0.35), 0.10, mats["body"], hero)
        add_clay_block("BlockB", (0.08, 0.0, 1.02), (0.65, 0.65, 0.30), -0.18, mats["accent"], hero)
        add_sphere("BlockTopBall", (-0.05, 0.0, 1.55), (0.34, 0.34, 0.34), mats["body"], hero)

    # Set dressing: two quiet clay blobs on the ground (not animated).
    add_sphere("DressingL", (-2.1, 0.7, 0.30), (0.42, 0.42, 0.30), mats["accent"])
    add_sphere("DressingR", (2.0, 0.9, 0.22), (0.30, 0.30, 0.22), mats["body"])

    # Animation: first-frame and last-frame keyframes are guaranteed present
    # in CFG["keyframes"] (see compute_keyframes); intermediate keys carry
    # the bounce / glide curve.
    for kf in CFG["keyframes"]:
        hero.location = tuple(kf["location"])
        hero.rotation_euler = (0.0, 0.0, float(kf["rotation_z"]))
        hero.keyframe_insert(data_path="location", frame=int(kf["frame"]))
        hero.keyframe_insert(data_path="rotation_euler", frame=int(kf["frame"]))

    # Camera.
    cam_data = bpy.data.cameras.new("ClayCamera")
    cam = bpy.data.objects.new("ClayCamera", cam_data)
    scene.collection.objects.link(cam)
    cam.location = (4.2, -6.4, 3.1)
    look_at(cam, (0.0, 0.0, 0.95))
    cam_data.lens = 42.0
    scene.camera = cam

    # Soft key light: one large area light + a dim fill.
    key_data = bpy.data.lights.new("ClayKey", type="AREA")
    key_data.energy = 650.0
    key_data.shape = "DISK"
    key_data.size = 5.0
    key = bpy.data.objects.new("ClayKey", key_data)
    scene.collection.objects.link(key)
    key.location = (3.5, -3.5, 6.5)
    look_at(key, (0.0, 0.0, 0.8))

    fill_data = bpy.data.lights.new("ClayFill", type="POINT")
    fill_data.energy = 120.0
    fill = bpy.data.objects.new("ClayFill", fill_data)
    scene.collection.objects.link(fill)
    fill.location = (-4.5, -2.0, 3.0)

    # Render: Cycles on CPU only (no GPU on this machine), conservative
    # samples, denoised so 32 samples still read as soft clay.
    scene.render.engine = "CYCLES"
    scene.cycles.samples = int(CFG["samples"])
    scene.cycles.device = "CPU"
    scene.cycles.use_denoising = True
    try:
        scene.cycles.denoiser = "OPENIMAGEDENOISE"
    except Exception:
        pass
    scene.cycles.seed = int(CFG["seed"])
    scene.render.resolution_x = int(CFG["width"])
    scene.render.resolution_y = int(CFG["height"])
    scene.render.resolution_percentage = 100
    scene.render.fps = int(CFG["fps"])
    scene.frame_start = int(CFG["frame_start"])
    scene.frame_end = int(CFG["frame_end"])
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = CFG["frames_dir"].rstrip("/") + "/frame_"
    scene.render.use_file_extension = True

    bpy.ops.render.render(animation=True)


main()
'''


def build_bpy_script(config: dict[str, Any]) -> str:
    """Render ``config`` into a self-contained bpy script (deterministic)."""
    payload = json.dumps(config, ensure_ascii=False, sort_keys=True)
    return _BPY_TEMPLATE.replace("__CONFIG_JSON__", payload)
