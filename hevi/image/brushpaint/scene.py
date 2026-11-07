"""Scene specs for the brush engine.

A scene is a plain JSON object -- simple enough for an LLM to fill in
from a template::

    {
      "name": "pond_night",
      "seed": 7,
      "step": 14,
      "background": "#0d1730",
      "layers": [
        {"type": "swirl_sky", "palette": ["#16264f", "#2d4a7a"],
         "vortices": [{"x": 0.42, "y": 0.26, "r": 0.2, "s": 1.6}]},
        {"type": "moon", "x": 0.78, "y": 0.16, "r": 0.07},
        {"type": "water", "from": 0.66, "palette": ["#1d3d5c", "#101f38"],
         "reflect_x": 0.78}
      ]
    }

Layers paint back-to-front: later layers win where regions overlap,
and (unless a layer pins its own ``"order": [lo, hi]``) reveal bands
are assigned in layer order, background first.

The four bundled templates are original compositions written for this
package; they double as the example scene files and as the storyfilm
brush provider's scene library.
"""

from __future__ import annotations

import copy
import json
import zlib
from pathlib import Path
from typing import Any

from .engine import Layer, Scene, hex_to_rgb
from .primitives import PRIMITIVES, SpecError

__all__ = [
    "SpecError",
    "TEMPLATES",
    "parse_scene",
    "load_scene_file",
    "get_template",
    "list_templates",
    "pick_template_for_text",
]


def parse_scene(spec: dict[str, Any]) -> Scene:
    if not isinstance(spec, dict):
        raise SpecError("scene spec must be a JSON object")
    raw_layers = spec.get("layers")
    if not isinstance(raw_layers, list) or not raw_layers:
        raise SpecError("scene spec needs a non-empty 'layers' list")
    seed = spec.get("seed", 42)
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise SpecError("scene 'seed' must be an integer")
    step = spec.get("step", 14)
    if not isinstance(step, (int, float)) or step < 4:
        raise SpecError("scene 'step' must be a number >= 4")
    try:
        background = hex_to_rgb(str(spec.get("background", "#0d1730")))
    except ValueError as exc:
        raise SpecError(f"scene background: {exc}") from exc

    layers: list[Layer] = []
    n = len(raw_layers)
    for i, raw in enumerate(raw_layers):
        if not isinstance(raw, dict):
            raise SpecError(f"layers[{i}] must be an object")
        kind = raw.get("type")
        if kind not in PRIMITIVES:
            raise SpecError(
                f"layers[{i}]: unknown type {kind!r}; valid types: {sorted(PRIMITIVES)}"
            )
        params = {k: v for k, v in raw.items() if k not in ("type", "order")}
        field = PRIMITIVES[kind](params)
        band = raw.get("order")
        if band is None:
            lo, hi = i / n, (i + 1) / n
        else:
            if (
                not isinstance(band, (list, tuple))
                or len(band) != 2
                or not all(isinstance(x, (int, float)) for x in band)
                or not 0.0 <= float(band[0]) < float(band[1]) <= 1.0
            ):
                raise SpecError(f"layers[{i}]: 'order' must be [lo, hi] with 0 <= lo < hi <= 1")
            lo, hi = float(band[0]), float(band[1])
        layers.append(Layer(field=field, order_lo=lo, order_hi=hi))
    return Scene(
        background=background,
        layers=layers,
        step=float(step),
        seed=seed,
        name=str(spec.get("name", "scene")),
    )


def load_scene_file(path: str | Path) -> tuple[dict[str, Any], Scene]:
    p = Path(path)
    try:
        spec = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise
    except json.JSONDecodeError as exc:
        raise SpecError(f"{p}: invalid JSON: {exc}") from exc
    return spec, parse_scene(spec)


# ---------------------------------------------------------------------------
# Bundled templates (original compositions).
# ---------------------------------------------------------------------------

TEMPLATES: dict[str, dict[str, Any]] = {
    "pond_night": {
        "name": "pond_night",
        "seed": 7,
        "step": 14,
        "background": "#0d1730",
        "layers": [
            {
                "type": "swirl_sky",
                "palette": ["#131f42", "#1d3263", "#2d4a7a", "#3f6e8f"],
                "horizon": 0.62,
                "vortices": [
                    {"x": 0.4, "y": 0.27, "r": 0.21, "s": 1.7},
                    {"x": 0.78, "y": 0.15, "r": 0.09, "s": 1.1},
                ],
                "sway": 2.2,
            },
            {"type": "stars", "count": 10, "seed": 31,
             "region": {"x0": 0.05, "x1": 0.95, "y0": 0.04, "y1": 0.4}},
            {"type": "moon", "x": 0.78, "y": 0.15, "r": 0.06},
            {"type": "hills", "base": 0.6, "amp": 0.03, "freq": 1.4,
             "palette": ["#14294d", "#1d3a63", "#18304f"]},
            {"type": "water", "from": 0.68,
             "palette": ["#1d3d5c", "#16264f", "#101f38"],
             "reflect_x": 0.78, "reflect_width": 0.05},
            {"type": "cypress", "x": 0.15, "base": 0.7, "height": 0.52,
             "width": 0.08, "palette": ["#16261a", "#1f3b26", "#2c4a2b", "#3d5a2a"]},
            {"type": "meadow", "from": 0.93,
             "palette": ["#14231c", "#1d3a26", "#2c4a2b"], "flower_density": 0.03},
        ],
    },
    "meadow_dawn": {
        "name": "meadow_dawn",
        "seed": 12,
        "step": 14,
        "background": "#f2e3c2",
        "layers": [
            {
                "type": "swirl_sky",
                "palette": ["#f5c877", "#f0bd72", "#e8b06a", "#dfe0c8"],
                "horizon": 0.58, "base_flow": 0.4, "wave": 0.25,
                "vortices": [{"x": 0.24, "y": 0.2, "r": 0.16, "s": 1.0}],
                "sway": 1.4,
            },
            {"type": "moon", "x": 0.24, "y": 0.19, "r": 0.052,
             "palette": ["#ffe066", "#ffd43b", "#ffc94d"],
             "halo_palette": ["#ffd9a0", "#f5c877", "#eeb96e"]},
            {"type": "clouds",
             "palette": ["#fff6e0", "#fbeed2", "#f3ddba"],
             "blobs": [
                 {"x": 0.55, "y": 0.13, "rx": 0.17, "ry": 0.032},
                 {"x": 0.82, "y": 0.27, "rx": 0.13, "ry": 0.028},
             ]},
            {"type": "hills", "base": 0.56, "amp": 0.025, "freq": 1.2,
             "palette": ["#9cba6d", "#84a356", "#6d8c4e"]},
            {"type": "tree", "x": 0.16, "base": 0.88, "canopy_r": 0.08,
             "canopy_h": 0.24,
             "palette": ["#5d8a4a", "#6f9c52", "#87b364", "#4a743c"]},
            {"type": "house", "x": 0.68, "base": 0.8, "w": 0.19, "h": 0.12,
             "roof_h": 0.06,
             "wall_palette": ["#efd9ae", "#e3c491"],
             "roof_palette": ["#c05a3a", "#a84e33"],
             "window_palette": ["#8a6a4a", "#77572f"]},
            {"type": "meadow", "from": 0.8,
             "palette": ["#87b364", "#74915a", "#5d8a4a", "#9cc474"],
             "flower_density": 0.09},
        ],
    },
    "river_dusk": {
        "name": "river_dusk",
        "seed": 21,
        "step": 14,
        "background": "#2a1836",
        "layers": [
            {
                "type": "swirl_sky",
                "palette": ["#3a2350", "#7a3a5e", "#c65a3a", "#e88a4a"],
                "horizon": 0.52, "base_flow": 0.45, "wave": 0.3,
                "vortices": [{"x": 0.5, "y": 0.44, "r": 0.13, "s": 0.8}],
                "sway": 1.6,
            },
            {"type": "moon", "x": 0.5, "y": 0.42, "r": 0.075,
             "palette": ["#ffd9a0", "#ffc98a", "#ffb37a"],
             "halo_palette": ["#e88a4a", "#c65a3a", "#7a3a5e"]},
            {"type": "clouds",
             "palette": ["#8a4a6a", "#6e3a5e", "#54304e"],
             "blobs": [
                 {"x": 0.22, "y": 0.16, "rx": 0.19, "ry": 0.03},
                 {"x": 0.78, "y": 0.1, "rx": 0.15, "ry": 0.026},
             ]},
            {"type": "hills", "base": 0.5, "amp": 0.04, "freq": 1.1, "phase": 2.1,
             "palette": ["#4a2c4e", "#3a2350", "#2a1836"]},
            {"type": "water", "from": 0.56,
             "palette": ["#54304e", "#3f2445", "#2a1836"],
             "reflect_x": 0.5, "reflect_width": 0.07,
             "glitter_palette": ["#ffb37a", "#ffd9a0", "#e88a4a"]},
            {"type": "tree", "x": 0.85, "base": 0.6, "canopy_r": 0.058,
             "canopy_h": 0.13,
             "palette": ["#38244a", "#2e1e3e", "#241830"],
             "trunk_palette": ["#1d1226", "#241830"]},
            {"type": "meadow", "from": 0.94,
             "palette": ["#241830", "#2c1c33"], "flower_density": 0.0},
        ],
    },
    "village_night": {
        "name": "village_night",
        "seed": 33,
        "step": 15,
        "background": "#0a1226",
        "layers": [
            {
                "type": "swirl_sky",
                "palette": ["#0e1a38", "#16264f", "#22346a"],
                "horizon": 0.55,
                "vortices": [{"x": 0.3, "y": 0.22, "r": 0.17, "s": 1.2}],
                "sway": 1.8,
            },
            {"type": "stars", "count": 12, "seed": 97, "r_min": 0.014, "r_max": 0.03,
             "region": {"x0": 0.04, "x1": 0.96, "y0": 0.03, "y1": 0.42}},
            {"type": "moon", "x": 0.86, "y": 0.13, "r": 0.05},
            {"type": "hills", "base": 0.52, "amp": 0.045, "freq": 0.9, "phase": 1.3,
             "palette": ["#101e33", "#14263f", "#0d1a2c"]},
            {"type": "house", "x": 0.3, "base": 0.78, "w": 0.16, "h": 0.1,
             "roof_h": 0.05,
             "wall_palette": ["#3d5484", "#344a75"],
             "roof_palette": ["#0c1626", "#0a1220"]},
            {"type": "house", "x": 0.52, "base": 0.82, "w": 0.2, "h": 0.13,
             "roof_h": 0.065,
             "wall_palette": ["#465e90", "#3d5484"],
             "roof_palette": ["#0e1a2e", "#0c1626"]},
            {"type": "house", "x": 0.76, "base": 0.79, "w": 0.15, "h": 0.09,
             "roof_h": 0.045,
             "wall_palette": ["#3d5484", "#344a75"],
             "roof_palette": ["#0c1626", "#0a1220"]},
            {"type": "cypress", "x": 0.08, "base": 0.8, "height": 0.34,
             "width": 0.06, "palette": ["#0d1f16", "#142a1e", "#1d3a26"]},
            {"type": "meadow", "from": 0.9,
             "palette": ["#0d1a14", "#12261c", "#1a3020"], "flower_density": 0.015},
        ],
    },
}


def list_templates() -> list[str]:
    return sorted(TEMPLATES)


def get_template(name: str) -> dict[str, Any]:
    try:
        return copy.deepcopy(TEMPLATES[name])
    except KeyError:
        raise SpecError(
            f"unknown template {name!r}; valid templates: {sorted(TEMPLATES)}"
        ) from None


# Keyword routing for free-text beats (storyfilm brush provider).
# English + Chinese cues; first matching group wins.
_KEYWORD_GROUPS: list[tuple[str, tuple[str, ...]]] = [
    ("river_dusk", ("sunset", "dusk", "evening glow", "river", "stream",
                    "黄昏", "傍晚", "晚霞", "河", "溪")),
    ("meadow_dawn", ("dawn", "morning", "sunrise", "meadow", "field",
                     "grassland", "清晨", "早晨", "日出", "田野", "草原", "草地")),
    ("village_night", ("village", "houses", "home", "village night",
                       "村", "房子", "家", "窗")),
    ("pond_night", ("pond", "lake", "moon", "night", "star",
                    "池塘", "湖", "月", "夜", "星")),
]


def pick_template_for_text(text: str) -> str:
    """Deterministically map a free-text beat description to a template."""
    haystack = (text or "").lower()
    for name, keys in _KEYWORD_GROUPS:
        if any(k in haystack for k in keys):
            return name
    names = list_templates()
    return names[zlib.crc32(haystack.encode("utf-8")) % len(names)]
