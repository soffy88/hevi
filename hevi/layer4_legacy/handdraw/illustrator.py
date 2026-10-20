"""Hevi Handdraw Line: CPU-only, style-differentiated, deterministic illustrator.

Each of the four supported styles renders with its own recipe (F4):

* ``1``  极简黑白线条   crisp uniform black line, no fill, no texture, pure monochrome
* ``8``  水墨写意       tapered brush strokes, ink bleed, dry-brush 飞白, red seal
* ``10`` 情绪叙事淡彩速写 thin loose indigo sketch line, one saturated accent, translucent wash
* ``17`` 墨线绘本       clean pen line, flat watercolour fills with visible paper grain

The illustration is always transparent outside the drawn shapes: there is no
opaque square backdrop.  All randomness comes from a seeded ``random.Random``
so the same (scene, style) always yields the same PNG.

Zero external API calls. 100% CPU.
"""

from __future__ import annotations

import math
import random
import zlib
from itertools import pairwise
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from scipy import ndimage

from hevi.layer4_legacy.handdraw.rough_stroke import roughen_polyline
from hevi.layer4_legacy.handdraw.styles import HanddrawStyleConfig, get_style_config

SUPERSAMPLE = 2


def _hex_to_rgb(hex_code: str) -> tuple[int, int, int]:
    clean = hex_code.lstrip("#")
    return int(clean[0:2], 16), int(clean[2:4], 16), int(clean[4:6], 16)


def _mix(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Style recipes
# ---------------------------------------------------------------------------


class _Recipe:
    """Concrete drawing parameters derived from a style config."""

    def __init__(self, cfg: HanddrawStyleConfig, rng: random.Random) -> None:
        self.cfg = cfg
        self.rng = rng
        self.sid = cfg.style_id
        self.ink = _hex_to_rgb(cfg.ink_color)
        self.accent = _hex_to_rgb(cfg.accent_color)
        self.marker = _hex_to_rgb(cfg.marker_color)
        self.paper = _hex_to_rgb(cfg.paper_color)

        if self.sid == "1":
            self.stroke_width = 7.0
            self.jitter = 0.0
            self.taper = 0.0
            self.bleed = 0.0
            self.grain = 0.0
            self.dry_brush = 0.0
            self.fill_opacity = 0.0
            self.fill_blur = 0.0
        elif self.sid == "8":
            self.stroke_width = 8.5
            self.jitter = 2.0
            self.taper = 0.55
            self.bleed = 4.0
            self.grain = 0.28
            self.dry_brush = 0.14
            self.fill_opacity = 0.52
            self.fill_blur = 7.0
        elif self.sid == "10":
            self.stroke_width = 3.2
            self.jitter = 5.5
            self.taper = 0.40
            self.bleed = 0.25
            self.grain = 0.90
            self.dry_brush = 0.0
            self.fill_opacity = 0.45
            self.fill_blur = 2.7
        else:  # 17 墨线绘本
            self.stroke_width = 5.4
            self.jitter = 1.1
            self.taper = 0.22
            self.bleed = 0.8
            self.grain = 0.9
            self.dry_brush = 0.0
            self.fill_opacity = 0.72
            self.fill_blur = 1.0

    # -- palette ---------------------------------------------------------
    def fill_color(self, role: str) -> tuple[int, int, int]:
        """Semantic role -> colour, honouring each style's palette recipe."""
        if self.sid == "1":
            # Pure black & white: every fill is a near-white paper tone.
            return {"warm": (250, 250, 250), "cool": (240, 240, 240), "accent": (232, 232, 232)}.get(
                role, (247, 247, 247)
            )
        if self.sid == "8":
            # Ink wash: greys plus the red seal; no saturated colour elsewhere.
            return {
                "warm": (226, 222, 216),
                "cool": (198, 202, 206),
                "accent": self.accent,
                "green": (206, 210, 204),
            }.get(role, (214, 212, 208))
        if self.sid == "10":
            # Almost bare paper; a single saturated accent is allowed.
            return {
                "warm": (250, 246, 240),
                "cool": (236, 240, 245),
                "accent": self.accent,
                "green": (226, 238, 228),
            }.get(role, (244, 244, 242))
        # 17 墨线绘本: warm flat storybook watercolour.
        return {
            "warm": (247, 216, 190),
            "cool": (200, 216, 228),
            "accent": self.accent,
            "green": self.marker,
        }.get(role, (240, 226, 205))


# ---------------------------------------------------------------------------
# Low level brushes
# ---------------------------------------------------------------------------


def _resample(points: list[tuple[float, float]], step: float = 1.5) -> list[tuple[float, float]]:
    if len(points) < 2:
        return points
    out = [points[0]]
    for a, b in pairwise(points):
        distance = math.hypot(b[0] - a[0], b[1] - a[1])
        count = max(1, int(distance / step))
        for index in range(1, count + 1):
            t = index / count
            out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
    return out


def _stamp_stroke(
    mask: np.ndarray,
    points: list[tuple[float, float]],
    width: float,
    recipe: _Recipe,
    *,
    taper: bool = False,
) -> None:
    """Rasterise a textured brush stroke in a tight local crop.

    The former implementation compared every point against a full-canvas NumPy
    grid. This version limits raster work to the path bounding box, keeping the
    same seeded jitter, taper and dry-brush policy while making CPU previews
    tractable at 1600x1600 supersampled resolution.
    """
    dense = _resample(points)
    if len(dense) < 2:
        return
    total = len(dense)
    pad = max(3, math.ceil(width / 2 + recipe.jitter + 2))
    height, width_px = mask.shape
    x0 = max(0, math.floor(min(point[0] for point in dense) - pad))
    y0 = max(0, math.floor(min(point[1] for point in dense) - pad))
    x1 = min(width_px, math.ceil(max(point[0] for point in dense) + pad + 1))
    y1 = min(height, math.ceil(max(point[1] for point in dense) + pad + 1))
    if x1 <= x0 or y1 <= y0:
        return

    local = Image.new("L", (x1 - x0, y1 - y0), 0)
    draw = ImageDraw.Draw(local)
    previous: tuple[float, float] | None = None
    previous_radius = width / 2
    for index, (x, y) in enumerate(dense):
        t = index / max(1, total - 1)
        radius = width / 2
        if taper:
            radius *= 1.0 - recipe.taper * abs(2 * t - 1) ** 1.5
        if recipe.dry_brush and recipe.rng.random() < recipe.dry_brush:
            previous = None
            continue
        jx = recipe.rng.uniform(-recipe.jitter, recipe.jitter)
        jy = recipe.rng.uniform(-recipe.jitter, recipe.jitter)
        point = (x + jx - x0, y + jy - y0)
        radius = max(0.6, radius)
        if previous is not None:
            line_width = max(1, round(previous_radius + radius))
            draw.line((previous, point), fill=255, width=line_width)
        draw.ellipse(
            (point[0] - radius, point[1] - radius,
             point[0] + radius, point[1] + radius),
            fill=255,
        )
        previous = point
        previous_radius = radius

    painted = np.asarray(local, dtype=np.uint8) > 0
    mask[y0:y1, x0:x1] |= painted


def _shape_points(shape: dict[str, Any]) -> list[tuple[float, float]]:
    kind = shape["kind"]
    if kind == "polygon":
        return [(float(x), float(y)) for x, y in shape["points"]]
    if kind == "ellipse":
        x0, y0, x1, y1 = shape["box"]
        steps = 72
        return [
            (
                (x0 + x1) / 2 + (x1 - x0) / 2 * math.cos(2 * math.pi * i / steps),
                (y0 + y1) / 2 + (y1 - y0) / 2 * math.sin(2 * math.pi * i / steps),
            )
            for i in range(steps)
        ]
    raise ValueError(kind)


def _shape_mask(size: tuple[int, int], shape: dict[str, Any]) -> np.ndarray:
    layer = Image.new("L", size, 0)
    draw = ImageDraw.Draw(layer)
    if shape["kind"] == "polygon":
        draw.polygon([(float(x), float(y)) for x, y in shape["points"]], fill=255)
    elif shape["kind"] == "ellipse":
        draw.ellipse(tuple(float(v) for v in shape["box"]), fill=255)
    else:
        raise ValueError(shape["kind"])
    return np.array(layer) > 127


def _grain_mask(size: tuple[int, int], strength: float, rng: random.Random) -> np.ndarray:
    """Generate reproducible paper grain without Pillow's global-RNG noise."""
    w, h = size
    seeded = np.random.default_rng(rng.randrange(1 << 63))
    noise = seeded.normal(loc=128.0, scale=32.0, size=(h, w)).clip(0, 255).astype(np.float32)
    tile = seeded.random((h, w)).astype(np.float32)
    return (0.5 * noise / 255.0 + 0.5 * tile) < strength


def _render_outline(
    shape: dict[str, Any],
    size: tuple[int, int],
    recipe: _Recipe,
) -> np.ndarray:
    mask = np.zeros((size[1], size[0]), dtype=bool)
    points = _shape_points(shape)
    closed = [*points, points[0]]
    _stamp_stroke(mask, closed, recipe.stroke_width, recipe, taper=recipe.taper > 0)
    return mask


def _render_outline_rough(
    shape: dict[str, Any],
    size: tuple[int, int],
    recipe: _Recipe,
    *,
    roughness: float,
    bowing: float,
    seed: int,
) -> np.ndarray:
    """Outline drawn with the rough technique: jittered, bowed, double-stroked.

    Each pass is stamped narrower than the legacy stroke so the two passes
    stay distinguishable instead of merging into one thick line.
    """
    mask = np.zeros((size[1], size[0]), dtype=bool)
    points = _shape_points(shape)
    result = roughen_polyline(
        points, roughness=roughness, bowing=bowing, seed=seed, double_stroke=True, closed=True
    )
    for one_pass in result.passes:
        _stamp_stroke(
            mask, [*one_pass, one_pass[0]], recipe.stroke_width * 0.62, recipe,
            taper=recipe.taper > 0,
        )
    return mask


def _stamp_rough(
    mask: np.ndarray,
    points: list[tuple[float, float]],
    width: float,
    recipe: _Recipe,
    *,
    roughness: float,
    bowing: float,
    seed: int,
) -> None:
    result = roughen_polyline(
        points, roughness=roughness, bowing=bowing, seed=seed, double_stroke=True, closed=False
    )
    for one_pass in result.passes:
        _stamp_stroke(mask, list(one_pass), width * 0.62, recipe)


def _decor_outline_rough(
    decor: dict[str, Any],
    size: tuple[int, int],
    recipe: _Recipe,
    *,
    roughness: float,
    bowing: float,
    seed: int,
) -> np.ndarray:
    mask = np.zeros((size[1], size[0]), dtype=bool)
    kind = decor["kind"]
    if kind == "line":
        _stamp_rough(
            mask, [(float(x), float(y)) for x, y in decor["points"]],
            recipe.stroke_width * decor.get("scale", 0.7), recipe,
            roughness=roughness, bowing=bowing, seed=seed,
        )
    elif kind == "arc":
        cx, cy, rx, ry = decor["box"]
        start, end = decor["start"], decor["end"]
        steps = max(12, int(abs(end - start) / 3))
        points = [
            (
                cx + rx * math.cos(math.radians(start + (end - start) * i / steps)),
                cy + ry * math.sin(math.radians(start + (end - start) * i / steps)),
            )
            for i in range(steps + 1)
        ]
        _stamp_rough(
            mask, points, recipe.stroke_width * decor.get("scale", 0.6), recipe,
            roughness=roughness, bowing=bowing, seed=seed,
        )
    elif kind == "rays":
        cx, cy, r0, r1 = decor["box"]
        for ray_idx, angle in enumerate(decor["angles"]):
            rad = math.radians(angle)
            _stamp_rough(
                mask,
                [(cx + r0 * math.cos(rad), cy + r0 * math.sin(rad)),
                 (cx + r1 * math.cos(rad), cy + r1 * math.sin(rad))],
                recipe.stroke_width * decor.get("scale", 0.55), recipe,
                roughness=roughness, bowing=bowing, seed=seed + ray_idx,
            )
    else:
        raise ValueError(kind)
    return mask


def _decor_outline(
    decor: dict[str, Any],
    size: tuple[int, int],
    recipe: _Recipe,
) -> np.ndarray:
    mask = np.zeros((size[1], size[0]), dtype=bool)
    kind = decor["kind"]
    if kind == "line":
        _stamp_stroke(mask, [(float(x), float(y)) for x, y in decor["points"]], recipe.stroke_width * decor.get("scale", 0.7), recipe)
    elif kind == "arc":
        cx, cy, rx, ry = decor["box"]
        start, end = decor["start"], decor["end"]
        steps = max(12, int(abs(end - start) / 3))
        points = [
            (
                cx + rx * math.cos(math.radians(start + (end - start) * i / steps)),
                cy + ry * math.sin(math.radians(start + (end - start) * i / steps)),
            )
            for i in range(steps + 1)
        ]
        _stamp_stroke(mask, points, recipe.stroke_width * decor.get("scale", 0.6), recipe)
    elif kind == "rays":
        cx, cy, r0, r1 = decor["box"]
        for angle in decor["angles"]:
            rad = math.radians(angle)
            _stamp_stroke(
                mask,
                [(cx + r0 * math.cos(rad), cy + r0 * math.sin(rad)), (cx + r1 * math.cos(rad), cy + r1 * math.sin(rad))],
                recipe.stroke_width * decor.get("scale", 0.55),
                recipe,
            )
    else:
        raise ValueError(kind)
    return mask


def scene_crosswalk() -> dict[str, Any]:
    """Child-height road crossing: zebra lines, signal and adult/child pair."""
    return {
        "shapes": [
            _p("road", [(0, 450), (640, 450), (640, 700), (0, 700)], "cool", 0),
            _p("crossing_1", [(90, 470), (155, 470), (180, 660), (115, 660)], "warm", 1),
            _p("crossing_2", [(220, 470), (285, 470), (310, 660), (245, 660)], "warm", 1),
            _p("crossing_3", [(350, 470), (415, 470), (440, 660), (375, 660)], "warm", 1),
            _p("crossing_4", [(480, 470), (545, 470), (570, 660), (505, 660)], "warm", 1),
            _p("signal_post", [(515, 100), (545, 100), (545, 420), (515, 420)], "cool", 2),
            _p("signal_box", [(475, 100), (590, 100), (590, 305), (475, 305)], "warm", 3),
            _e("signal_red", (505, 120, 560, 175), "accent", 4),
            _e("signal_green", (505, 220, 560, 275), "green", 4),
            _e("adult_head", (145, 130, 245, 230), "warm", 4),
            _p("adult_body", [(155, 235), (235, 235), (260, 420), (130, 420)], "cool", 3),
            _p("child_ear_left", [(265, 270), (273, 238), (289, 267)], "warm", 6),
            _p("child_ear_right", [(311, 267), (328, 238), (335, 272)], "warm", 6),
            _e("child_head", (265, 250, 335, 320), "warm", 5),
            _e("child_eye_left", (279, 276, 286, 285), "cool", 7),
            _e("child_eye_right", (313, 276, 320, 285), "cool", 7),
            _e("child_muzzle", (289, 291, 311, 307), "cool", 7),
            _p("child_nose", [(297, 290), (303, 290), (300, 295)], "accent", 8),
            _p("child_body", [(272, 322), (328, 322), (345, 425), (255, 425)], "accent", 4),
        ],
        "decor": [
            {"host": "adult_body", "kind": "line", "points": [(220, 285), (270, 350)], "scale": 0.65},
            {"host": "child_body", "kind": "line", "points": [(275, 350), (235, 390)], "scale": 0.55},
            {"host": "child_head", "kind": "line", "points": [(285, 300), (270, 296)], "scale": 0.35},
            {"host": "child_head", "kind": "line", "points": [(315, 300), (330, 296)], "scale": 0.35},
        ],
    }


def scene_hand_washing() -> dict[str, Any]:
    """Hand-washing at a low sink with soap bubbles."""
    return {
        "shapes": [
            _p("sink_stand", [(130, 455), (500, 455), (470, 650), (160, 650)], "cool", 1),
            _p("sink_bowl", [(100, 380), (530, 380), (480, 460), (150, 460)], "warm", 3),
            _p("faucet", [(300, 275), (340, 275), (340, 375), (320, 375), (320, 330), (285, 330)], "cool", 4),
            _e("soap", (385, 335, 445, 385), "green", 4),
            _e("hand_left", (205, 350, 275, 400), "warm", 5),
            _e("hand_right", (280, 350, 350, 400), "warm", 5),
            _e("bubble_a", (220, 265, 255, 300), "cool", 6),
            _e("bubble_b", (375, 250, 405, 280), "accent", 6),
            _e("bubble_c", (415, 280, 438, 303), "cool", 6),
            _e("bear_ear_left", (220, 86, 266, 132), "warm", 4),
            _e("bear_ear_right", (334, 86, 380, 132), "warm", 4),
            _e("bear_inner_ear_left", (231, 97, 255, 121), "cool", 6),
            _e("bear_inner_ear_right", (345, 97, 369, 121), "cool", 6),
            _e("hero_head", (235, 95, 365, 225), "warm", 3),
            _e("bear_eye_left", (263, 140, 278, 157), "cool", 7),
            _e("bear_eye_right", (322, 140, 337, 157), "cool", 7),
            _e("bear_muzzle", (270, 163, 330, 200), "cool", 7),
            _e("bear_nose", (293, 163, 307, 176), "accent", 8),
            _e("hero_body", (215, 220, 385, 376), "green", 2),
            _e("bear_paw_left", (193, 324, 246, 367), "warm", 6),
            _e("bear_paw_right", (354, 324, 407, 367), "warm", 6),
        ],
        "decor": [
            {"host": "hero_head", "kind": "line", "points": [(270, 160), (285, 170)], "scale": 0.35},
            {"host": "hero_head", "kind": "line", "points": [(320, 170), (335, 160)], "scale": 0.35},
            {"host": "bear_muzzle", "kind": "arc", "box": (294, 179, 14, 10), "start": 15, "end": 165},
        ],
    }


def scene_bear_night() -> dict[str, Any]:
    """A calm bedtime scene with an identifiable bear cub and warm night lamp."""
    return {
        "shapes": [
            _e("moon", (55, 70, 190, 205), "accent", 2),
            _p("star_one", [(235, 85), (247, 111), (276, 114), (254, 133), (261, 161), (235, 145), (210, 161), (216, 133), (194, 114), (223, 111)], "accent", 3),
            _p("star_two", [(460, 135), (471, 158), (495, 162), (477, 178), (482, 202), (460, 189), (439, 202), (444, 178), (425, 162), (450, 158)], "cool", 3),
            _e("lamp_base", (390, 475, 520, 510), "warm", 2),
            _p("lamp_shade", [(405, 335), (505, 335), (527, 400), (383, 400)], "warm", 4),
            _p("lamp_stand", [(447, 400), (463, 400), (463, 478), (447, 478)], "cool", 3),
            _e("bear_body", (155, 355, 340, 615), "warm", 3),
            _e("bear_ear_left", (156, 200, 220, 264), "warm", 4),
            _e("bear_ear_right", (285, 200, 349, 264), "warm", 4),
            _e("bear_head", (177, 210, 329, 370), "warm", 5),
            _e("bear_inner_ear_left", (171, 216, 203, 249), "cool", 6),
            _e("bear_inner_ear_right", (301, 216, 333, 249), "cool", 6),
            _e("bear_eye_left", (210, 265, 224, 282), "cool", 7),
            _e("bear_eye_right", (281, 265, 295, 282), "cool", 7),
            _e("bear_muzzle", (221, 290, 277, 327), "cool", 7),
            _e("bear_nose", (242, 289, 256, 302), "accent", 8),
            _p("ground", [(-10, 600), (630, 600), (630, 700), (-10, 700)], "cool", 0),
        ],
        "decor": [
            {"host": "bear_muzzle", "kind": "arc", "box": (245, 306, 17, 13), "start": 15, "end": 165},
            {"host": "bear_body", "kind": "line", "points": [(217, 480), (280, 480)], "scale": 0.55},
        ],
    }


# ---------------------------------------------------------------------------
# Scene catalogue (kids-first, plus the legacy explainer scenes)
# ---------------------------------------------------------------------------


def _p(shape_id: str, points: list[tuple[float, float]], role: str = "warm", z: int = 1) -> dict[str, Any]:
    return {"id": shape_id, "kind": "polygon", "points": points, "role": role, "z": z}


def _e(shape_id: str, box: tuple[float, float, float, float], role: str = "warm", z: int = 1) -> dict[str, Any]:
    return {"id": shape_id, "kind": "ellipse", "box": box, "role": role, "z": z}



def scene_puppy_gratitude() -> dict[str, Any]:
    """Friendly puppy with drooping ears, broad muzzle and a thank-you card."""
    return {
        "shapes": [
            _e("puppy_body", (160, 360, 340, 625), "warm", 3),
            _e("puppy_ear_left", (138, 195, 204, 340), "warm", 4),
            _e("puppy_ear_right", (296, 195, 362, 340), "warm", 4),
            _e("puppy_head", (168, 195, 332, 372), "warm", 5),
            _e("puppy_patch", (273, 224, 320, 278), "accent", 6),
            _e("puppy_eye_left", (208, 258, 224, 278), "cool", 7),
            _e("puppy_eye_right", (274, 258, 290, 278), "cool", 7),
            _e("puppy_muzzle", (220, 288, 282, 332), "paper", 7),
            _e("puppy_nose", (242, 290, 260, 306), "cool", 8),
            _p("thank_you_card", [(405, 315), (560, 315), (560, 500), (405, 500)], "paper", 3),
            _p("card_fold", [(405, 315), (482, 370), (560, 315)], "warm", 4),
            _e("card_heart", (457, 390, 508, 441), "accent", 5),
            _p("ground", [(-20, 620), (630, 620), (630, 700), (-20, 700)], "cool", 0),
        ],
        "decor": [
            {"host": "puppy_muzzle", "kind": "arc", "box": (238, 309, 18, 12), "start": 15, "end": 165},
        ],
    }


def scene_rabbit_sadness() -> dict[str, Any]:
    """Rabbit with long ears beside a friendly and repairable block tower."""
    return {
        "shapes": [
            _e("rabbit_body", (150, 365, 330, 625), "warm", 3),
            _p("rabbit_ear_left", [(185, 240), (173, 95), (224, 214)], "warm", 4),
            _p("rabbit_ear_right", [(261, 214), (306, 95), (299, 244)], "warm", 4),
            _p("rabbit_inner_ear_left", [(188, 202), (184, 128), (208, 205)], "accent", 5),
            _p("rabbit_inner_ear_right", [(273, 203), (293, 130), (287, 215)], "accent", 5),
            _e("rabbit_head", (162, 192, 324, 372), "warm", 5),
            _e("rabbit_eye_left", (202, 258, 218, 277), "cool", 7),
            _e("rabbit_eye_right", (268, 258, 284, 277), "cool", 7),
            _e("rabbit_muzzle", (218, 290, 270, 326), "paper", 7),
            _p("rabbit_nose", [(238, 294), (251, 294), (245, 304)], "accent", 8),
            _p("block_one", [(370, 480), (432, 480), (432, 540), (370, 540)], "accent", 4),
            _p("block_two", [(432, 540), (494, 540), (494, 600), (432, 600)], "green", 4),
            _p("block_three", [(494, 480), (556, 480), (556, 540), (494, 540)], "cool", 4),
            _e("comfort_heart", (420, 365, 470, 415), "accent", 3),
            _p("ground", [(-20, 620), (630, 620), (630, 700), (-20, 700)], "cool", 0),
        ],
        "decor": [
            {"host": "rabbit_muzzle", "kind": "arc", "box": (232, 311, 23, 12), "start": 200, "end": 340},
        ],
    }


def scene_cat_courage() -> dict[str, Any]:
    """Cat cub with triangle ears, whiskers and colourful stepping stones."""
    return {
        "shapes": [
            _e("cat_body", (150, 360, 335, 622), "warm", 3),
            _p("cat_ear_left", [(157, 250), (170, 170), (224, 220)], "warm", 5),
            _p("cat_ear_right", [(270, 220), (324, 170), (333, 256)], "warm", 5),
            _p("cat_inner_ear_left", [(174, 225), (180, 192), (207, 220)], "accent", 6),
            _p("cat_inner_ear_right", [(284, 220), (315, 193), (316, 231)], "accent", 6),
            _e("cat_head", (164, 205, 328, 370), "warm", 5),
            _e("cat_eye_left", (202, 255, 218, 276), "cool", 7),
            _e("cat_eye_right", (274, 255, 290, 276), "cool", 7),
            _p("cat_nose", [(239, 290), (253, 290), (246, 301)], "accent", 8),
            _p("whisker_left_top", [(205, 302), (165, 293)], "cool", 5),
            _p("whisker_left_bottom", [(207, 313), (169, 322)], "cool", 5),
            _p("whisker_right_top", [(284, 302), (324, 293)], "cool", 5),
            _p("whisker_right_bottom", [(282, 313), (320, 322)], "cool", 5),
            _p("step_one", [(358, 565), (424, 565), (424, 610), (358, 610)], "accent", 4),
            _p("step_two", [(424, 515), (490, 515), (490, 560), (424, 560)], "green", 4),
            _p("step_three", [(490, 465), (556, 465), (556, 510), (490, 510)], "cool", 4),
            _p("ground", [(-20, 620), (630, 620), (630, 700), (-20, 700)], "cool", 0),
        ],
        "decor": [
            {"host": "cat_body", "kind": "line", "points": [(216, 490), (274, 490)], "scale": 0.6},
        ],
    }


def scene_seed_growth() -> dict[str, Any]:
    """A visible seedling, soil-filled pot and rabbit gardener."""
    return {
        "shapes": [
            _e("rabbit_body", (100, 410, 252, 630), "warm", 3),
            _p("rabbit_ear_left", [(132, 285), (124, 150), (163, 280)], "warm", 4),
            _p("rabbit_ear_right", [(177, 280), (220, 155), (211, 300)], "warm", 4),
            _e("rabbit_head", (108, 255, 229, 390), "warm", 5),
            _e("rabbit_eye_left", (140, 302, 152, 319), "cool", 7),
            _e("rabbit_eye_right", (186, 302, 198, 319), "cool", 7),
            _e("plant_pot", (350, 495, 535, 620), "accent", 3),
            _p("soil", [(350, 510), (535, 510), (520, 535), (365, 535)], "cool", 5),
            _p("stem", [(443, 510), (443, 395), (451, 350)], "green", 6),
            _e("leaf_left", (388, 390, 447, 435), "green", 5),
            _e("leaf_right", (444, 356, 500, 402), "green", 5),
            _e("sun", (455, 95, 545, 185), "accent", 3),
            _p("ground", [(-20, 620), (630, 620), (630, 700), (-20, 700)], "cool", 0),
        ],
        "decor": [
            {"host": "rabbit_head", "kind": "arc", "box": (153, 346, 28, 13), "start": 15, "end": 165},
        ],
    }


def scene_fox_share() -> dict[str, Any]:
    return {
        "shapes": [
            _e("fox_body", (170, 300, 470, 620), "accent", 3),
            _e("fox_head", (110, 180, 330, 400), "warm", 4),
            _p("fox_ear_a", [(140, 200), (185, 120), (225, 200)], "warm", 5),
            _p("fox_ear_b", [(235, 200), (280, 120), (315, 205)], "warm", 5),
            _p("fox_inner_ear_a", [(158, 187), (185, 145), (210, 190)], "cool", 6),
            _p("fox_inner_ear_b", [(250, 190), (278, 145), (298, 190)], "cool", 6),
            _e("fox_eye_left", (163, 260, 184, 283), "cool", 7),
            _e("fox_eye_right", (256, 260, 277, 283), "cool", 7),
            _e("fox_muzzle_left", (174, 300, 226, 344), "cool", 6),
            _e("fox_muzzle_right", (215, 300, 267, 344), "cool", 6),
            _p("fox_nose", [(211, 303), (230, 303), (220, 316)], "accent", 8),
            _p("fox_tail", [(430, 430), (560, 330), (600, 470), (470, 540)], "accent", 2),
            _e("fox_paw_left", (210, 535, 275, 590), "warm", 5),
            _e("fox_paw_right", (345, 535, 410, 590), "warm", 5),
            _e("apple", (470, 470, 590, 590), "green", 6),
            _p("apple_leaf", [(525, 470), (585, 430), (555, 480)], "green", 7),
            _p("ground", [(-20, 600), (620, 600), (620, 680), (-20, 680)], "cool", 0),
        ],
        "decor": [
            {"host": "fox_head", "kind": "arc", "box": (180, 300, 30, 22), "start": 200, "end": 340},
            {"host": "fox_body", "kind": "line", "points": [(260, 470), (380, 470)], "scale": 0.6},
        ],
    }


def scene_turn_taking() -> dict[str, Any]:
    return {
        "shapes": [
            _e("kid_a", (150, 320, 320, 520), "accent", 4),
            _e("kid_a_head", (175, 200, 295, 330), "warm", 5),
            _e("kid_b", (400, 320, 570, 520), "cool", 3),
            _e("kid_b_head", (425, 200, 545, 330), "warm", 4),
            _p("swing_frame", [(280, 180), (300, 180), (330, 560), (310, 560)], "green", 2),
            _p("swing_seat", [(250, 430), (350, 430), (350, 460), (250, 460)], "accent", 6),
            _p("ground", [(-20, 560), (620, 560), (620, 660), (-20, 660)], "cool", 0),
            _e("ball", (60, 470, 150, 560), "accent", 5),
        ],
        "decor": [
            {"host": "kid_a_head", "kind": "arc", "box": (235, 285, 24, 18), "start": 200, "end": 340},
            {"host": "kid_b_head", "kind": "arc", "box": (485, 285, 24, 18), "start": 200, "end": 340},
        ],
    }


def scene_brush_teeth() -> dict[str, Any]:
    return {
        "shapes": [
            _e("tooth", (200, 150, 460, 520), "warm", 4),
            _p("tooth_left_root", [(240, 470), (280, 620), (330, 480)], "warm", 3),
            _p("tooth_right_root", [(340, 480), (390, 620), (425, 470)], "warm", 3),
            _p("brush_handle", [(430, 380), (620, 300), (640, 350), (450, 430)], "accent", 5),
            _p("brush_head", [(370, 330), (440, 300), (470, 390), (395, 420)], "cool", 6),
            _p("paste", [(380, 300), (450, 268), (462, 300), (392, 332)], "green", 7),
            _p("sparkle", [(520, 130), (540, 175), (585, 195), (540, 215), (520, 260), (500, 215), (455, 195), (500, 175)], "accent", 8),
        ],
        "decor": [
            {"host": "tooth", "kind": "arc", "box": (300, 300, 60, 40), "start": 200, "end": 340},
            {"host": "brush_head", "kind": "line", "points": [(395, 350), (455, 330)], "scale": 0.5},
        ],
    }


def scene_stars_nature() -> dict[str, Any]:
    return {
        "shapes": [
            _e("moon", (90, 110, 280, 300), "accent", 3),
            _p("tree_trunk", [(430, 320), (490, 320), (500, 620), (420, 620)], "warm", 4),
            _e("tree_crown", (330, 110, 610, 380), "green", 5),
            _p("star", [(150, 400), (185, 470), (260, 480), (205, 530), (220, 605), (150, 565), (80, 605), (95, 530), (40, 480), (115, 470)], "accent", 6),
            _p("ground", [(-20, 610), (620, 610), (620, 700), (-20, 700)], "cool", 0),
        ],
        "decor": [
            {"host": "tree_crown", "kind": "arc", "box": (470, 250, 90, 70), "start": 190, "end": 350},
            {"host": "moon", "kind": "arc", "box": (215, 205, 45, 40), "start": 120, "end": 260},
        ],
    }


def scene_feelings() -> dict[str, Any]:
    return {
        "shapes": [
            _e("face", (180, 150, 460, 430), "warm", 4),
            _e("eye_left", (245, 250, 285, 290), "cool", 6),
            _e("eye_right", (355, 250, 395, 290), "cool", 6),
            _p("smile", [(250, 340), (280, 375), (360, 375), (390, 340), (360, 400), (280, 400)], "accent", 5),
            _p("heart_left", [(120, 470), (170, 430), (220, 470), (170, 540)], "accent", 3),
            _p("heart_right", [(420, 470), (470, 430), (520, 470), (470, 540)], "accent", 3),
        ],
        "decor": [
            {"host": "face", "kind": "arc", "box": (320, 300, 70, 30), "start": 200, "end": 340},
        ],
    }


def scene_courage() -> dict[str, Any]:
    return {
        "shapes": [
            _p("hill", [(200, 620), (330, 300), (470, 620)], "green", 2),
            _e("child", (300, 380, 400, 560), "accent", 4),
            _e("child_head", (315, 300, 385, 385), "warm", 5),
            _e("sun", (60, 90, 220, 250), "accent", 1),
            _p("flag_pole", [(330, 220), (342, 220), (342, 330), (330, 330)], "cool", 3),
            _p("flag", [(342, 225), (440, 255), (342, 290)], "accent", 6),
            _p("ground", [(-20, 610), (620, 610), (620, 700), (-20, 700)], "cool", 0),
        ],
        "decor": [
            {"host": "sun", "kind": "rays", "box": (140, 170, 95, 135), "angles": [0, 45, 90, 135, 180, 225, 270, 315]},
        ],
    }


def scene_tidy_up() -> dict[str, Any]:
    return {
        "shapes": [
            _p("toy_box", [(120, 380), (500, 380), (480, 620), (140, 620)], "warm", 3),
            _p("box_lid", [(100, 330), (520, 330), (500, 395), (120, 395)], "accent", 4),
            _e("block_a", (180, 430, 270, 520), "green", 6),
            _e("block_b", (300, 430, 390, 520), "cool", 6),
            _p("block_c", [(230, 540), (320, 540), (320, 610), (230, 610)], "accent", 6),
            _p("ground", [(-20, 610), (620, 610), (620, 700), (-20, 700)], "cool", 0),
        ],
        "decor": [
            {"host": "toy_box", "kind": "line", "points": [(160, 480), (460, 480)], "scale": 0.5},
        ],
    }


# Legacy explainer scenes retained for backward compatibility.
def scene_anger_brain() -> dict[str, Any]:
    return {
        "shapes": [
            _e("head", (170, 170, 430, 430), "warm", 4),
            _p("torso", [(180, 420), (420, 420), (450, 620), (150, 620)], "cool", 2),
            _e("amygdala", (230, 60, 370, 170), "accent", 5),
            _p("ground", [(-20, 600), (620, 600), (620, 690), (-20, 690)], "cool", 0),
        ],
        "decor": [
            {"host": "amygdala", "kind": "rays", "box": (300, 115, 80, 130), "angles": [30, 60, 90, 120, 150], "scale": 0.5},
            {"host": "head", "kind": "line", "points": [(250, 300), (290, 315)], "scale": 0.5},
            {"host": "head", "kind": "line", "points": [(350, 300), (310, 315)], "scale": 0.5},
        ],
    }


def scene_balance_scale() -> dict[str, Any]:
    return {
        "shapes": [
            _p("beam", [(70, 300), (530, 170), (530, 205), (70, 335)], "warm", 4),
            _e("pan_left", (60, 350, 210, 440), "cool", 3),
            _e("pan_right", (400, 200, 550, 290), "cool", 3),
            _p("stand", [(270, 250), (330, 250), (370, 560), (230, 560)], "warm", 2),
            _p("ground", [(-20, 550), (620, 550), (620, 640), (-20, 640)], "cool", 0),
        ],
        "decor": [
            {"host": "beam", "kind": "line", "points": [(300, 235), (300, 300)], "scale": 0.8},
        ],
    }


def scene_calm_decision() -> dict[str, Any]:
    return {
        "shapes": [
            _e("bulb", (230, 80, 370, 230), "accent", 4),
            _p("card", [(120, 320), (480, 320), (480, 540), (120, 540)], "cool", 3),
            _p("check", [(180, 430), (230, 480), (420, 360), (400, 400), (235, 520), (160, 460)], "accent", 5),
        ],
        "decor": [
            {"host": "bulb", "kind": "rays", "box": (300, 155, 90, 130), "angles": [0, 45, 90, 135, 180, 225, 270, 315], "scale": 0.5},
        ],
    }


def scene_snowball_effect() -> dict[str, Any]:
    return {
        "shapes": [
            _e("snowball_small", (90, 120, 170, 200), "cool", 5),
            _e("snowball_mid", (210, 200, 320, 310), "cool", 4),
            _e("snowball_big", (350, 260, 560, 470), "accent", 3),
            _p("slope", [(0, 120), (620, 460), (620, 640), (0, 300)], "warm", 0),
        ],
        "decor": [
            {"host": "snowball_big", "kind": "arc", "box": (455, 365, 90, 80), "start": 40, "end": 200},
        ],
    }


def scene_growth_curves() -> dict[str, Any]:
    return {
        "shapes": [
            _p("axes", [(60, 90), (78, 90), (78, 516), (60, 516)], "cool", 2),
            _p("axis_x", [(60, 500), (560, 500), (560, 518), (60, 518)], "cool", 2),
            _p("linear", [(84, 500), (290, 500), (290, 400)], "cool", 3),
            _p("exponential", [(300, 500), (430, 300), (530, 120), (530, 500)], "accent", 4),
        ],
        "decor": [
            {"host": "exponential", "kind": "line", "points": [(300, 500), (380, 420), (450, 300), (510, 170)], "scale": 0.8},
        ],
    }


def scene_coin_pyramid() -> dict[str, Any]:
    return {
        "shapes": [
            _p("base", [(100, 480), (500, 480), (500, 550), (100, 550)], "cool", 2),
            _p("tier1", [(140, 410), (460, 410), (460, 480), (140, 480)], "accent", 3),
            _p("tier2", [(190, 340), (410, 340), (410, 410), (190, 410)], "accent", 4),
            _p("tier3", [(240, 270), (360, 270), (360, 340), (240, 340)], "accent", 5),
            _p("star", [(300, 130), (322, 185), (380, 190), (335, 228), (348, 285), (300, 252), (252, 285), (265, 228), (220, 190), (278, 185)], "accent", 6),
        ],
        "decor": [
            {"host": "star", "kind": "rays", "box": (300, 205, 75, 110), "angles": [0, 45, 90, 135, 180, 225, 270, 315], "scale": 0.45},
        ],
    }


ILLUSTRATION_BUILDERS = {
    # kids-first
    "fox_share": scene_fox_share,
    "turn_taking": scene_turn_taking,
    "brush_teeth": scene_brush_teeth,
    "stars_nature": scene_stars_nature,
    "feelings": scene_feelings,
    "courage": scene_courage,
    "tidy_up": scene_tidy_up,
    "crosswalk": scene_crosswalk,
    "hand_washing": scene_hand_washing,
    "bear_night": scene_bear_night,
    "seed_growth": scene_seed_growth,
    "cat_courage": scene_cat_courage,
    "rabbit_sadness": scene_rabbit_sadness,
    "puppy_gratitude": scene_puppy_gratitude,
    # legacy explainer
    "anger_brain": scene_anger_brain,
    "balance_scale": scene_balance_scale,
    "calm_decision": scene_calm_decision,
    "snowball_effect": scene_snowball_effect,
    "growth_curves": scene_growth_curves,
    "coin_pyramid": scene_coin_pyramid,
}


# ---------------------------------------------------------------------------
# Renderer
# ---------------------------------------------------------------------------


def _normalise_polygon(points: list[tuple[float, float]], width: int, height: int) -> list[list[float]]:
    # Shapes such as the ground intentionally extend beyond the illustration
    # frame. Clamp vertices to its transparent canvas before exporting polygons.
    return [
        [round(min(1.0, max(0.0, x / width)), 6),
         round(min(1.0, max(0.0, y / height)), 6)]
        for x, y in points
    ]


def _convex_hull(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    pts = sorted(set(points))
    if len(pts) <= 2:
        return pts

    def cross(o: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> float:
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list[tuple[float, float]] = []
    for point in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], point) <= 0:
            lower.pop()
        lower.append(point)
    upper: list[tuple[float, float]] = []
    for point in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], point) <= 0:
            upper.pop()
        upper.append(point)
    return lower[:-1] + upper[:-1]


def _render_scene(
    scene_key: str,
    cfg: HanddrawStyleConfig,
    size: tuple[int, int],
    seed: int = 0,
    *,
    stroke_style: str = "legacy",
    rough_roughness: float = 2.0,
    rough_bowing: float = 2.0,
) -> tuple[Image.Image, list[dict[str, Any]]]:
    if stroke_style not in ("legacy", "rough"):
        raise ValueError(
            f"unsupported stroke_style: {stroke_style!r} (expected 'legacy' or 'rough')"
        )
    if stroke_style == "rough":
        for _name, _value in (("rough_roughness", rough_roughness), ("rough_bowing", rough_bowing)):
            if not isinstance(_value, (int, float)) or isinstance(_value, bool) \
                    or not math.isfinite(float(_value)) or float(_value) < 0:
                raise ValueError(f"{_name} must be a finite number >= 0, got {_value!r}")
    rng = random.Random(f"{scene_key}:{cfg.style_id}:v2:{int(seed)}")
    recipe = _Recipe(cfg, rng)
    spec = ILLUSTRATION_BUILDERS[scene_key]()

    scale = SUPERSAMPLE
    big = (size[0] * scale, size[1] * scale)
    scaled_shapes = []
    for shape in spec["shapes"]:
        item = dict(shape)
        if shape["kind"] == "polygon":
            item["points"] = [(x * scale, y * scale) for x, y in shape["points"]]
        else:
            item["box"] = tuple(v * scale for v in shape["box"])
        scaled_shapes.append(item)
    # Style 10 intentionally uses a smaller, airy vignette composition. The
    # watercolor sketch needs a larger quiet-paper margin than the other recipes.
    composition_scale = {"1": 1.0, "8": 0.90, "10": 0.72, "17": 0.82}[cfg.style_id]
    if composition_scale < 1.0:
        cx, cy = big[0] / 2, big[1] / 2
        size_factor = composition_scale
        for item in scaled_shapes:
            if item["kind"] == "polygon":
                item["points"] = [
                    (cx + (x - cx) * size_factor, cy + (y - cy) * size_factor)
                    for x, y in item["points"]
                ]
            else:
                x0, y0, x1, y1 = item["box"]
                item["box"] = (
                    cx + (x0 - cx) * size_factor,
                    cy + (y0 - cy) * size_factor,
                    cx + (x1 - cx) * size_factor,
                    cy + (y1 - cy) * size_factor,
                )
    scaled_decor = []
    for decor in spec["decor"]:
        item = dict(decor)
        if decor["kind"] in ("line",):
            item["points"] = [(x * scale, y * scale) for x, y in decor["points"]]
        else:
            item["box"] = tuple(v * scale for v in decor["box"])
        if composition_scale < 1.0:
            cx, cy = big[0] / 2, big[1] / 2
            size_factor = composition_scale
            if decor["kind"] == "line":
                item["points"] = [
                    (cx + (x - cx) * size_factor, cy + (y - cy) * size_factor)
                    for x, y in item["points"]
                ]
            else:
                x0, y0, rx, ry = item["box"]
                item["box"] = (
                    cx + (x0 - cx) * size_factor,
                    cy + (y0 - cy) * size_factor,
                    rx * size_factor,
                    ry * size_factor,
                )
        scaled_decor.append(item)

    # 1. Watercolour / wash fills, painted first so ink sits on top.
    fill_rgba = np.zeros((big[1], big[0], 4), dtype=np.uint8)
    if recipe.fill_opacity > 0:
        for shape in sorted(scaled_shapes, key=lambda s: s["z"]):
            mask = _shape_mask(big, shape)
            if not mask.any():
                continue
            colour = recipe.fill_color(shape["role"])
            layer = np.zeros((big[1], big[0], 4), dtype=np.uint8)
            layer[..., 0], layer[..., 1], layer[..., 2] = colour
            alpha = np.where(mask, int(255 * recipe.fill_opacity), 0).astype(np.uint8)
            if recipe.fill_blur:
                alpha = np.array(
                    Image.fromarray(alpha).filter(ImageFilter.GaussianBlur(recipe.fill_blur * scale))
                )
            if recipe.grain:
                grain = _grain_mask(big, recipe.grain * 0.35, rng)
                alpha = np.where(grain & mask, (alpha * 0.55).astype(np.uint8), alpha)
            layer[..., 3] = alpha
            # Normal (not additive) compositing keeps wash edges soft, not saturated.
            base = Image.fromarray(fill_rgba)
            base.alpha_composite(Image.fromarray(layer))
            fill_rgba = np.array(base)

    # 2. Ink layer.  The legacy branch is the original code path, untouched;
    # stroke_style="rough" swaps only how outlines/decor are stamped.
    ink_mask = np.zeros((big[1], big[0]), dtype=bool)
    if stroke_style == "rough":
        base_seed = int(seed) * 10007 + zlib.crc32(f"{scene_key}:{cfg.style_id}".encode())
        r_rough = min(50.0, float(rough_roughness) * scale)
        r_bow = min(50.0, float(rough_bowing) * scale)
        for shape_idx, shape in enumerate(scaled_shapes):
            ink_mask |= _render_outline_rough(
                shape, big, recipe, roughness=r_rough, bowing=r_bow, seed=base_seed + shape_idx
            )
        for decor_idx, decor in enumerate(scaled_decor):
            ink_mask |= _decor_outline_rough(
                decor, big, recipe, roughness=r_rough, bowing=r_bow,
                seed=base_seed + 1000 + decor_idx,
            )
    else:
        for shape in scaled_shapes:
            ink_mask |= _render_outline(shape, big, recipe)
        for decor in scaled_decor:
            ink_mask |= _decor_outline(decor, big, recipe)

    composed = Image.fromarray(fill_rgba)
    if recipe.sid == "8":
        # Keep the core brush edge dark, and render the water-soluble edge as
        # a separate semitransparent grey wash. Thresholding the blur made the
        # old result simply look like a wider, heavy black outline.
        ink_float = ink_mask.astype(np.float32)
        halo = ndimage.gaussian_filter(ink_float, recipe.bleed * scale)
        wash = np.zeros((big[1], big[0], 4), dtype=np.uint8)
        wash[..., :3] = (67, 70, 69)
        wash[..., 3] = np.clip(halo * 95, 0, 105).astype(np.uint8)
        composed.alpha_composite(Image.fromarray(wash))

        core = np.zeros((big[1], big[0], 4), dtype=np.uint8)
        core[..., :3] = recipe.ink
        core[..., 3] = np.where(ink_mask, 218, 0).astype(np.uint8)
        composed.alpha_composite(Image.fromarray(core))

        # Dry-brush fly-white: short fibers cut into nearby ink, repeatable for
        # a fixed seed and clipped to the dilated contour so they cannot mark
        # unrelated clean paper or create flashing visual noise.
        ys, xs = np.where(ink_mask)
        if len(xs):
            scratch = Image.new("L", big, 0)
            scratch_draw = ImageDraw.Draw(scratch)
            for _ in range(max(18, len(xs) // 2100)):
                chosen = recipe.rng.randrange(len(xs))
                cx, cy = int(xs[chosen]), int(ys[chosen])
                angle = recipe.rng.uniform(-0.8, 0.8)
                length = recipe.rng.uniform(4.0, 15.0) * scale
                dx, dy = math.cos(angle) * length / 2, math.sin(angle) * length / 2
                scratch_draw.line(
                    (cx - dx, cy - dy, cx + dx, cy + dy),
                    fill=255, width=max(1, round(recipe.rng.uniform(0.35, 0.9) * scale)),
                )
            scratch_mask = np.asarray(scratch, dtype=np.uint8) > 0
            scratch_mask &= ndimage.binary_dilation(ink_mask, iterations=max(2, 3 * scale))
            fly_white = np.zeros((big[1], big[0], 4), dtype=np.uint8)
            fly_white[..., :3] = (249, 244, 236)
            fly_white[..., 3] = np.where(scratch_mask, 210, 0).astype(np.uint8)
            composed.alpha_composite(Image.fromarray(fly_white))
    else:
        if recipe.bleed:
            blurred = ndimage.gaussian_filter(ink_mask.astype(np.float32), recipe.bleed * scale)
            ink_mask = blurred > 0.28
        ink_rgba = np.zeros((big[1], big[0], 4), dtype=np.uint8)
        ink_rgba[..., 0], ink_rgba[..., 1], ink_rgba[..., 2] = recipe.ink
        ink_rgba[..., 3] = np.where(ink_mask, 255, 0).astype(np.uint8)
        composed.alpha_composite(Image.fromarray(ink_rgba))

    # 3. Style 8: a red seal stamp as the signature accent.
    if cfg.style_id == "8":
        seal = Image.new("RGBA", big, (0, 0, 0, 0))
        draw = ImageDraw.Draw(seal)
        s = int(52 * scale)
        x, y = int(big[0] - s - 26 * scale), int(big[1] - s - 26 * scale)
        draw.rounded_rectangle((x, y, x + s, y + s), radius=int(6 * scale), fill=(*recipe.accent, 235))
        draw.line((x + s * 0.28, y + s * 0.28, x + s * 0.72, y + s * 0.72), fill=(255, 255, 255, 220), width=max(2, int(3 * scale)))
        draw.line((x + s * 0.72, y + s * 0.28, x + s * 0.28, y + s * 0.72), fill=(255, 255, 255, 220), width=max(2, int(3 * scale)))
        composed.alpha_composite(seal)

    small = composed.resize(size, Image.Resampling.LANCZOS)

    # 4. Parts: front-most shapes first so greedy ownership matches drawing depth.
    parts: list[dict[str, Any]] = []
    for shape in sorted(scaled_shapes, key=lambda s: -s["z"]):
        if shape["kind"] == "polygon":
            points = [(x, y) for x, y in shape["points"]]
        else:
            points = _shape_points(shape)
        hull = _convex_hull(points) or points
        if len(hull) < 3:
            hull = points
        parts.append(
            {
                "id": shape["id"],
                "polygon": _normalise_polygon(hull, big[0], big[1]),
            }
        )
    return small, parts


def build_scene_illustration(
    scene_key: str,
    output_path: Path,
    style_id: str | int = "8",
    size: tuple[int, int] = (600, 600),
    seed: int = 0,
    *,
    stroke_style: str = "legacy",
    rough_roughness: float = 2.0,
    rough_bowing: float = 2.0,
) -> dict[str, Any]:
    """Generate a transparent, style-differentiated illustration plus part metadata.

    ``stroke_style`` is ``"legacy"`` (default; output identical to before
    this option existed) or ``"rough"`` (rough-style hand-drawn strokes:
    vertex jitter + segment bowing + double stroke, see
    :mod:`hevi.layer4_legacy.handdraw.rough_stroke`).  ``rough_roughness``
    / ``rough_bowing`` are in output-image coordinates and only take
    effect with ``stroke_style="rough"``.
    """
    if scene_key not in ILLUSTRATION_BUILDERS:
        raise ValueError(
            f"Unknown scene key '{scene_key}'. Supported: {sorted(ILLUSTRATION_BUILDERS)}"
        )
    cfg = get_style_config(style_id)
    image, parts = _render_scene(
        scene_key, cfg, size, seed=seed,
        stroke_style=stroke_style, rough_roughness=rough_roughness, rough_bowing=rough_bowing,
    )
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path)
    return {
        "source": str(output_path),
        "width": image.width,
        "height": image.height,
        "parts": parts,
        "style_id": cfg.style_id,
        "stroke_style": stroke_style,
    }
