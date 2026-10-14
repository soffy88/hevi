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
from itertools import pairwise
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from scipy import ndimage

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
            self.bleed = 5.2
            self.grain = 0.0
            self.dry_brush = 0.48
            self.fill_opacity = 0.34
            self.fill_blur = 5.0
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
            _e("child_head", (265, 250, 335, 320), "warm", 5),
            _p("child_body", [(272, 322), (328, 322), (345, 425), (255, 425)], "accent", 4),
        ],
        "decor": [
            {"host": "adult_body", "kind": "line", "points": [(220, 285), (270, 350)], "scale": 0.65},
            {"host": "child_body", "kind": "line", "points": [(275, 350), (235, 390)], "scale": 0.55},
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
            _e("hero_head", (235, 95, 365, 225), "warm", 3),
            _p("hero_body", [(225, 225), (375, 225), (410, 360), (190, 360)], "green", 2),
        ],
        "decor": [
            {"host": "hero_head", "kind": "line", "points": [(270, 160), (285, 170)], "scale": 0.35},
            {"host": "hero_head", "kind": "line", "points": [(320, 170), (335, 160)], "scale": 0.35},
        ],
    }


# ---------------------------------------------------------------------------
# Scene catalogue (kids-first, plus the legacy explainer scenes)
# ---------------------------------------------------------------------------


def _p(shape_id: str, points: list[tuple[float, float]], role: str = "warm", z: int = 1) -> dict[str, Any]:
    return {"id": shape_id, "kind": "polygon", "points": points, "role": role, "z": z}


def _e(shape_id: str, box: tuple[float, float, float, float], role: str = "warm", z: int = 1) -> dict[str, Any]:
    return {"id": shape_id, "kind": "ellipse", "box": box, "role": role, "z": z}


def scene_fox_share() -> dict[str, Any]:
    return {
        "shapes": [
            _e("fox_body", (170, 300, 470, 620), "accent", 3),
            _e("fox_head", (110, 180, 330, 400), "warm", 4),
            _p("fox_ear_a", [(140, 200), (185, 120), (225, 200)], "warm", 5),
            _p("fox_ear_b", [(235, 200), (280, 120), (315, 205)], "warm", 5),
            _p("fox_tail", [(430, 430), (560, 330), (600, 470), (470, 540)], "accent", 2),
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
    scene_key: str, cfg: HanddrawStyleConfig, size: tuple[int, int], seed: int = 0
) -> tuple[Image.Image, list[dict[str, Any]]]:
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

    # 2. Ink layer.
    ink_mask = np.zeros((big[1], big[0]), dtype=bool)
    for shape in scaled_shapes:
        ink_mask |= _render_outline(shape, big, recipe)
    for decor in scaled_decor:
        ink_mask |= _decor_outline(decor, big, recipe)

    if recipe.bleed:
        blurred = ndimage.gaussian_filter(ink_mask.astype(np.float32), recipe.bleed * scale)
        ink_mask = blurred > 0.28
    ink_rgba = np.zeros((big[1], big[0], 4), dtype=np.uint8)
    ink_rgba[..., 0], ink_rgba[..., 1], ink_rgba[..., 2] = recipe.ink
    ink_rgba[..., 3] = np.where(ink_mask, 255, 0).astype(np.uint8)

    composed = Image.fromarray(fill_rgba)
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
) -> dict[str, Any]:
    """Generate a transparent, style-differentiated illustration plus part metadata."""
    if scene_key not in ILLUSTRATION_BUILDERS:
        raise ValueError(
            f"Unknown scene key '{scene_key}'. Supported: {sorted(ILLUSTRATION_BUILDERS)}"
        )
    cfg = get_style_config(style_id)
    image, parts = _render_scene(scene_key, cfg, size, seed=seed)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path)
    return {
        "source": str(output_path),
        "width": image.width,
        "height": image.height,
        "parts": parts,
        "style_id": cfg.style_id,
    }
