"""SCENE3D scene templates — three preschool-friendly, non-photoreal, warm scenes.

Each template is a *builder* that returns a fully-validated
:class:`~hevi.layer4_legacy.scene3d.schema.SceneSpec`.  The templates follow the
direction in ``KIDS_ANIME_DIRECTION.md`` (2–6 year old viewers) and the method in
``docs/SCENE3D_VIBE_RULES.md``:

* **Warm, non-photoreal palette** with clear silhouettes and a single consistent
  main light (the handbook's "先把光打对" lesson, §03/§12).
* **Camera path presets** (``orbit`` / ``push_in`` / ``follow``) so a ShotSpec can
  call the same template with a different move without re-authoring waypoints.
* **GLB assets** are referenced by manifest ``asset_id`` and resolved to a
  workdir copy by the renderer; procedural geometry is used where a GLB would
  blow the CPU budget (§04 "先量，再谈数字").

Templates:

* ``little_planet``  — a small warm planet, floating props, orbit camera.
  Composition and palette are *inspired by* the handbook's Little Prince planet
  design images (reference only — no upstream code or model is copied).
* ``town_street``    — a little town street with the Paris 512 buildings, trees
  and street furniture (GLB), plus a walking rigged character.
* ``playground``     — a corner of a fairground: procedural carousel + tents +
  a character walking past.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from hevi.layer4_legacy.scene3d.schema import SceneSpec, parse_scene

__all__ = [
    "TEMPLATE_NAMES",
    "TEMPLATE_DESCRIPTIONS",
    "CAMERA_PRESETS",
    "build_template",
    "list_templates",
]

TEMPLATE_NAMES = ("little_planet", "town_street", "playground")

CAMERA_PRESETS = ("orbit", "push_in", "follow")

TEMPLATE_DESCRIPTIONS: dict[str, str] = {
    "little_planet": "漂浮的暖色小星球，环绕镜头（幼儿向，非写实）",
    "town_street": "小镇街道：巴黎 512 建筑 + 行道树 + 会走路的绑骨角色",
    "playground": "游乐园一角：程序化旋转木马 + 帐篷 + 走过的角色",
}


# --------------------------------------------------------------------------- #
# Shared warm preschool lighting / sky
# --------------------------------------------------------------------------- #
def _warm_weather(*, starfield: bool = False, fog: float = 0.010) -> dict[str, Any]:
    """A warm, bright, soft preschool sky (bounded saturation, no flicker)."""
    return {
        "background_top": [0.55, 0.78, 0.95],
        "background_bottom": [0.99, 0.90, 0.72],
        "fog_color": [0.96, 0.90, 0.80],
        "fog_density": fog,
        "wind_strength": 0.8,
        "wind_speed": 1.1,
        "starfield": starfield,
        "star_count": 0 if not starfield else 900,
        "bloom_strength": 0.42,
        "bloom_radius": 0.6,
        "bloom_threshold": 0.9,
        "shadows": True,
        "fox_sway": False,
    }


def _warm_lights() -> dict[str, Any]:
    """One consistent warm key light + a soft cool fill (main light unchanged
    across every template, per the task's "主光一致" requirement)."""
    return {
        "sun_color": [1.0, 0.93, 0.78],
        "sun_intensity": 1.75,
        "sun_pos": [7.0, 12.0, 6.0],
        "ambient_color": [0.72, 0.80, 0.95],
        "ambient_intensity": 0.85,
        "rim_color": [1.0, 0.88, 0.7],
        "rim_intensity": 0.5,
    }


# --------------------------------------------------------------------------- #
# little_planet
# --------------------------------------------------------------------------- #
def _little_planet(aspect: str, duration: float, seed: int, camera_preset: str, resolution: int) -> dict[str, Any]:
    """A small warm planet with floating rocks and a strolling character.

    Composition/palette reference: the handbook's Little Prince planet design
    images (07-designs-prompts-park-prince).  Built entirely from procedural
    geometry — no upstream model or code is copied.
    """
    assets: list[dict[str, Any]] = [
        {"kind": "planet", "name": "home", "params": {"radius": 2.6, "pos": [0.0, 1.6, 0.0], "color": [0.98, 0.72, 0.42], "spin": 0.06, "ring": False}},
        {"kind": "rock", "name": "rock_a", "params": {"pos": [-2.4, 2.6, 1.1], "scale": 0.5, "color": [0.85, 0.55, 0.4]}},
        {"kind": "rock", "name": "rock_b", "params": {"pos": [2.6, 2.3, -0.9], "scale": 0.38, "color": [0.8, 0.5, 0.42]}},
        {"kind": "tree", "name": "tree_a", "params": {"pos": [1.7, 1.7, 1.5], "scale": 0.7}},
        {"kind": "grass", "name": "lawn", "params": {"count": 220, "radius": 2.3, "y": 1.7, "color": [0.62, 0.82, 0.42]}},
        # A small walker circles the planet's near face so the shot has real
        # skeletal motion (§06) without competing with the planet for attention.
        {"kind": "character", "name": "walker", "params": {
            "asset_id": "pedestrian-01-walk-anim", "target_height": 1.05, "basis": "height",
            "pos": [0.0, 2.55, 1.5], "from": [-2.0, 2.55, 1.9], "to": [2.0, 2.55, 1.9],
            "yaw_deg": 0.0, "clip": "walk", "time_scale": 1.0, "obstacle_radius": 0.3,
        }},
    ]
    return {
        "name": "little_planet",
        "duration_s": duration,
        "fps": 30,
        "resolution": resolution,
        "seed": seed,
        "camera": {
            "aspect": aspect,
            "fov": 40.0,
            "preset": camera_preset or "orbit",
            "preset_params": {"look": [0.0, 2.0, 0.0], "radius": 10.5, "height": 3.6, "steps": 4},
            "pos": [10.5, 4.4, 10.5],
            "look": [0.0, 2.0, 0.0],
        },
        "lights": _warm_lights(),
        "weather": _warm_weather(starfield=False, fog=0.004),
        "assets": assets,
    }


# --------------------------------------------------------------------------- #
# town_street
# --------------------------------------------------------------------------- #
def _town_street(aspect: str, duration: float, seed: int, camera_preset: str, resolution: int) -> dict[str, Any]:
    """A little town street: Paris 512 buildings, trees, bench, taxi, walker."""
    assets: list[dict[str, Any]] = [
        {"kind": "ground", "name": "road", "params": {"color": [0.86, 0.80, 0.70], "radius": 40.0}},
        # Buildings face the street: the P2.0 family faces +X, so yaw +90 puts the
        # wide facade toward the camera line (§06 orientation table).
        {"kind": "glb", "name": "boulangerie", "params": {"asset_id": "building-03-boulangerie", "target_height": 3.4, "basis": "height", "pos": [-3.6, 0.0, -3.2], "yaw_deg": 90.0, "obstacle_radius": 1.7}},
        {"kind": "glb", "name": "metro", "params": {"asset_id": "building-08-metro", "target_height": 3.2, "basis": "height", "pos": [4.0, 0.0, -3.4], "yaw_deg": 90.0, "obstacle_radius": 1.7}},
        # Street trees are normalised by canopy width, not total height (§17).
        {"kind": "glb", "name": "tree_green", "params": {"asset_id": "tree-01-plane-green", "target_height": 3.0, "basis": "height", "pos": [-1.4, 0.0, 3.0], "yaw_deg": 0.0, "obstacle_radius": 1.0}},
        {"kind": "glb", "name": "tree_autumn", "params": {"asset_id": "tree-02-plane-autumn", "target_height": 3.0, "basis": "height", "pos": [6.0, 0.0, 2.6], "yaw_deg": 0.0, "obstacle_radius": 1.0}},
        {"kind": "glb", "name": "bench", "params": {"asset_id": "prop-02-bench", "target_height": 1.0, "basis": "height", "pos": [1.6, 0.0, 3.4], "yaw_deg": 0.0, "obstacle_radius": 1.0}},
        {"kind": "glb", "name": "pigeons", "params": {"asset_id": "prop-06-pigeon-flock", "target_height": 0.7, "basis": "height", "pos": [-5.0, 0.0, 2.2], "yaw_deg": 0.0, "obstacle_radius": 0.9}},
        # The walker crosses the street in front of the buildings.
        {"kind": "character", "name": "walker", "params": {
            "asset_id": "pedestrian-01-walk-anim", "target_height": 1.5, "basis": "height",
            "pos": [0.0, 0.0, 1.2], "from": [-3.2, 0.0, 1.2], "to": [3.4, 0.0, 1.2],
            "yaw_deg": 0.0, "clip": "walk", "time_scale": 1.0, "obstacle_radius": 0.4,
        }},
    ]
    return {
        "name": "town_street",
        "duration_s": duration,
        "fps": 30,
        "resolution": resolution,
        "seed": seed,
        "camera": {
            "aspect": aspect,
            "fov": 44.0,
            "preset": camera_preset or "follow",
            "preset_params": {"back": 5.4, "height": 2.3, "steps": 4},
            "pos": [0.0, 2.4, 7.5],
            "look": [0.0, 1.0, 0.0],
        },
        "lights": _warm_lights(),
        "weather": _warm_weather(starfield=False, fog=0.012),
        "assets": assets,
    }


# --------------------------------------------------------------------------- #
# playground
# --------------------------------------------------------------------------- #
def _playground(aspect: str, duration: float, seed: int, camera_preset: str, resolution: int) -> dict[str, Any]:
    """A corner of a fairground: procedural carousel + tents + a walker.

    The carousel is procedural (a low-poly toon build) rather than the 8K park
    ride GLB, which is not in the committed asset set (the handbook's 04 pack is
    the deliberately-unoptimised 8K control group, §14).
    """
    assets: list[dict[str, Any]] = [
        {"kind": "ground", "name": "plaza", "params": {"color": [0.93, 0.85, 0.72], "radius": 34.0}},
        {"kind": "planet", "name": "carousel_roof", "params": {"radius": 1.9, "pos": [0.0, 3.3, 0.0], "color": [0.98, 0.45, 0.42], "spin": 0.22, "ring": False}},
        {"kind": "tree", "name": "tree_a", "params": {"pos": [-4.2, 0.0, -2.0], "scale": 0.9}},
        {"kind": "tree", "name": "tree_b", "params": {"pos": [4.6, 0.0, -2.4], "scale": 0.8}},
        {"kind": "rock", "name": "stall", "params": {"pos": [3.0, 0.35, 2.6], "scale": 0.7, "color": [0.95, 0.62, 0.4]}},
        {"kind": "rock", "name": "stall_b", "params": {"pos": [-3.2, 0.32, 2.8], "scale": 0.62, "color": [0.62, 0.8, 0.92]}},
        {"kind": "grass", "name": "lawn", "params": {"count": 260, "radius": 9.0, "y": 0.0, "color": [0.66, 0.84, 0.46]}},
        {"kind": "character", "name": "walker", "params": {
            "asset_id": "pedestrian-01-walk-anim", "target_height": 1.5, "basis": "height",
            "pos": [0.0, 0.0, 2.2], "from": [-3.0, 0.0, 2.2], "to": [3.2, 0.0, 2.2],
            "yaw_deg": 0.0, "clip": "walk", "time_scale": 1.0, "obstacle_radius": 0.4,
        }},
    ]
    return {
        "name": "playground",
        "duration_s": duration,
        "fps": 30,
        "resolution": resolution,
        "seed": seed,
        "camera": {
            "aspect": aspect,
            "fov": 45.0,
            "preset": camera_preset or "push_in",
            "preset_params": {"look": [0.0, 1.6, 0.0], "from": 11.0, "to": 5.2, "height": 2.6},
            "pos": [0.0, 2.8, 11.0],
            "look": [0.0, 1.6, 0.0],
        },
        "lights": _warm_lights(),
        "weather": _warm_weather(starfield=False, fog=0.011),
        "assets": assets,
    }


_BUILDERS = {
    "little_planet": _little_planet,
    "town_street": _town_street,
    "playground": _playground,
}


def build_template(
    name: str,
    *,
    aspect: str = "16:9",
    duration: float = 12.0,
    seed: int = 20241015,
    camera_preset: str = "",
    resolution: int = 1080,
) -> SceneSpec:
    """Build and validate a named template into a :class:`SceneSpec`.

    Raises :class:`ValueError` on an unknown template or camera preset — an
    unsupported request is refused rather than silently defaulted.
    """
    if name not in _BUILDERS:
        raise ValueError(f"unknown scene3d template {name!r} (have: {', '.join(TEMPLATE_NAMES)})")
    if camera_preset and camera_preset not in CAMERA_PRESETS:
        raise ValueError(
            f"unknown camera preset {camera_preset!r} (have: {', '.join(CAMERA_PRESETS)})"
        )
    data = _BUILDERS[name](
        aspect, float(duration), int(seed), camera_preset, int(resolution)
    )
    # Deep-copy so a caller mutating the returned spec cannot poison a later call.
    return parse_scene(copy.deepcopy(data))


def list_templates() -> list[dict[str, Any]]:
    """Describe every template (name, description, camera presets)."""
    return [
        {"name": n, "description": TEMPLATE_DESCRIPTIONS[n], "camera_presets": list(CAMERA_PRESETS)}
        for n in TEMPLATE_NAMES
    ]
