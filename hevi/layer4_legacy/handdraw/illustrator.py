"""Hevi Handdraw Line: CPU-only deterministic illustration generator.

Renders vector-like illustration assets with distinct dark ink outlines
and colored semantic parts, ensuring full compatibility with the
stroke-tracing and brush-painting contracts of sweety-handdraw-video.
Zero external API calls. 100% CPU.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from hevi.layer4_legacy.handdraw.styles import HanddrawStyleConfig, get_style_config


def _hex_to_rgb(hex_code: str) -> tuple[int, int, int]:
    clean = hex_code.lstrip("#")
    return int(clean[0:2], 16), int(clean[2:4], 16), int(clean[4:6], 16)


# ---------------------------------------------------------------------------
# Topic 1: 为什么越生气越容易做错决定 (Anger & Decisions)
# ---------------------------------------------------------------------------


def draw_anger_brain(
    output_path: Path,
    style_cfg: HanddrawStyleConfig,
    size: tuple[int, int] = (600, 600),
) -> dict[str, Any]:
    """Scene 1.1: 人物情绪激动与激活的杏仁核。"""
    w, h = size
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    ink = _hex_to_rgb(style_cfg.ink_color)
    accent = _hex_to_rgb(style_cfg.accent_color)
    skin = (245, 215, 185)
    cloth = (80, 130, 180) if style_cfg.style_id != "8" else (90, 90, 95)
    brain_c = accent if style_cfg.style_id != "1" else (240, 240, 240)

    # 1. Torso (lower portion)
    d.rectangle((180, 420, 420, 560), fill=cloth, outline=ink, width=5)
    # 2. Neck
    d.rectangle((270, 360, 330, 430), fill=skin, outline=ink, width=4)
    # 3. Head & Face (profile/front)
    d.ellipse((190, 170, 410, 390), fill=skin, outline=ink, width=5)
    # Eyebrows & Eyes (anger shape)
    d.line([(230, 260), (280, 280)], fill=ink, width=4)
    d.line([(370, 260), (320, 280)], fill=ink, width=4)
    d.ellipse((250, 290, 275, 315), fill=ink)
    d.ellipse((325, 290, 350, 315), fill=ink)
    # Mouth (open exclamation)
    d.ellipse((270, 330, 330, 375), fill=ink)
    # 4. Active amygdala brain pulse (top/forehead area)
    d.ellipse((220, 60, 380, 180), fill=brain_c, outline=ink, width=5)
    # Brain gyri curves inside
    d.arc((240, 80, 320, 140), start=30, end=210, fill=ink, width=4)
    d.arc((280, 90, 360, 160), start=180, end=350, fill=ink, width=4)
    # Radiating stress sparks
    for angle in [30, 60, 90, 120, 150]:
        rad = math.radians(angle)
        x1 = 300 + 90 * math.cos(rad)
        y1 = 120 - 70 * math.sin(rad)
        x2 = 300 + 130 * math.cos(rad)
        y2 = 120 - 100 * math.sin(rad)
        d.line([(x1, y1), (x2, y2)], fill=accent, width=4)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path)

    # Normalised polygon parts
    parts = [
        {
            "id": "brain_amygdala",
            "polygon": [[0.15, 0.0], [0.85, 0.0], [0.85, 0.35], [0.15, 0.35]],
        },
        {
            "id": "head",
            "polygon": [[0.2, 0.28], [0.8, 0.28], [0.8, 0.68], [0.2, 0.68]],
        },
        {
            "id": "torso",
            "polygon": [[0.2, 0.65], [0.8, 0.65], [0.8, 1.0], [0.2, 1.0]],
        },
    ]
    return {
        "source": str(output_path),
        "width": w,
        "height": h,
        "parts": parts,
    }


def draw_balance_scale(
    output_path: Path,
    style_cfg: HanddrawStyleConfig,
    size: tuple[int, int] = (600, 600),
) -> dict[str, Any]:
    """Scene 1.2: 情绪冲动与理智决策的天平失衡。"""
    w, h = size
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    ink = _hex_to_rgb(style_cfg.ink_color)
    accent = _hex_to_rgb(style_cfg.accent_color)
    logic_col = (100, 175, 120) if style_cfg.style_id != "1" else (220, 220, 220)
    pan_col = (210, 190, 150) if style_cfg.style_id != "1" else (235, 235, 235)

    # 1. Left pan with heavy anger weight (drawn first, visually lowest)
    d.line([(100, 320), (70, 420)], fill=ink, width=3)
    d.line([(100, 320), (170, 420)], fill=ink, width=3)
    # Pan bowl as a closed filled crescent so it owns a solid fillable region
    d.pieslice((60, 392, 180, 452), start=0, end=180, fill=pan_col, outline=ink, width=4)
    # Heavy stone on left pan (red/accent)
    d.polygon([(80, 420), (160, 420), (145, 358), (95, 358)], fill=accent, outline=ink)

    # 2. Right pan with light logic block
    d.line([(500, 180), (450, 270)], fill=ink, width=3)
    d.line([(500, 180), (550, 270)], fill=ink, width=3)
    d.pieslice((440, 242, 560, 302), start=0, end=180, fill=pan_col, outline=ink, width=4)
    d.rectangle((475, 240, 525, 272), fill=logic_col, outline=ink, width=4)

    # 3. Tilted Beam (anger on left side heavier -> tilts down to left)
    # Left at y=320, Right at y=170
    d.line([(100, 320), (500, 180)], fill=ink, width=8)
    d.ellipse((285, 235, 315, 265), fill=ink)

    # 4. Base / Fulcrum (center triangular stand)
    d.polygon([(260, 520), (340, 520), (300, 250)], fill=pan_col, outline=ink)
    d.rectangle((210, 510, 390, 550), fill=pan_col, outline=ink, width=5)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path)

    parts = [
        {
            "id": "left_pan",
            "polygon": [[0.03, 0.56], [0.32, 0.56], [0.32, 0.80], [0.03, 0.80]],
        },
        {
            "id": "right_pan",
            "polygon": [[0.62, 0.28], [0.97, 0.28], [0.97, 0.52], [0.62, 0.52]],
        },
        {
            "id": "tilted_beam",
            "polygon": [[0.01, 0.13], [0.99, 0.13], [0.99, 0.57], [0.01, 0.57]],
        },
        {
            "id": "scale_stand",
            "polygon": [[0.26, 0.55], [0.74, 0.55], [0.74, 0.98], [0.26, 0.98]],
        },
    ]
    return {
        "source": str(output_path),
        "width": w,
        "height": h,
        "parts": parts,
    }


def draw_calm_decision(
    output_path: Path,
    style_cfg: HanddrawStyleConfig,
    size: tuple[int, int] = (600, 600),
) -> dict[str, Any]:
    """Scene 1.3: 前额叶皮层回归平静，看清最优解。"""
    w, h = size
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    ink = _hex_to_rgb(style_cfg.ink_color)
    accent = _hex_to_rgb(style_cfg.accent_color)
    bulb_col = (250, 220, 80) if style_cfg.style_id != "1" else (240, 240, 240)
    card_col = (235, 245, 255) if style_cfg.style_id != "1" else (245, 245, 245)

    # 1. Calm Lightbulb (top center)
    d.ellipse((220, 70, 380, 230), fill=bulb_col, outline=ink, width=5)
    d.rectangle((260, 225, 340, 270), fill=ink)
    d.arc((270, 260, 330, 290), start=0, end=180, fill=ink, width=4)
    # Filament inside bulb
    d.line([(270, 170), (290, 130), (310, 170), (330, 130)], fill=ink, width=4)
    # Radiating glow lines
    for angle in [0, 45, 90, 135, 180, 225, 315]:
        rad = math.radians(angle)
        x1 = 300 + 95 * math.cos(rad)
        y1 = 150 - 95 * math.sin(rad)
        x2 = 300 + 135 * math.cos(rad)
        y2 = 150 - 135 * math.sin(rad)
        d.line([(x1, y1), (x2, y2)], fill=accent, width=4)

    # 2. Decision Card / Clear Road (bottom center)
    d.rounded_rectangle((120, 320, 480, 540), radius=25, fill=card_col, outline=ink, width=5)
    # Checkmark inside card
    d.line([(180, 430), (250, 490), (420, 370)], fill=accent, width=12)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path)

    parts = [
        {
            "id": "wisdom_bulb",
            "polygon": [[0.14, 0.0], [0.86, 0.0], [0.86, 0.50], [0.14, 0.50]],
        },
        {
            "id": "decision_card",
            "polygon": [[0.10, 0.49], [0.90, 0.49], [0.90, 0.98], [0.10, 0.98]],
        },
    ]
    return {
        "source": str(output_path),
        "width": w,
        "height": h,
        "parts": parts,
    }


# ---------------------------------------------------------------------------
# Topic 2: 复利效应 (Compound Interest Effect)
# ---------------------------------------------------------------------------


def draw_snowball_effect(
    output_path: Path,
    style_cfg: HanddrawStyleConfig,
    size: tuple[int, int] = (600, 600),
) -> dict[str, Any]:
    """Scene 2.1: 滚雪球比喻，坡度与长路。"""
    w, h = size
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    ink = _hex_to_rgb(style_cfg.ink_color)
    accent = _hex_to_rgb(style_cfg.accent_color)
    snow_col = (230, 245, 255) if style_cfg.style_id != "1" else (245, 245, 245)

    # 1. Slope (from top-left to bottom-right)
    d.polygon([(40, 160), (560, 480), (560, 560), (40, 560)], fill=snow_col, outline=ink)
    d.line([(40, 160), (560, 480)], fill=ink, width=6)

    # 2. Small snowball (top left of slope)
    d.ellipse((100, 120, 160, 180), fill=(255, 255, 255), outline=ink, width=4)

    # 3. Medium rolling snowball (middle)
    d.ellipse((220, 200, 320, 300), fill=(250, 250, 255), outline=ink, width=5)

    # 4. Giant snowball (bottom right)
    d.ellipse((360, 260, 540, 440), fill=accent if style_cfg.style_id == "10" else (245, 250, 255), outline=ink, width=6)
    # Snow texture swirls inside giant ball
    d.arc((390, 290, 510, 410), start=40, end=200, fill=ink, width=4)
    d.arc((410, 310, 490, 390), start=210, end=350, fill=ink, width=4)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path)

    parts = [
        {
            "id": "mountain_slope",
            "polygon": [[0.05, 0.18], [0.95, 0.18], [0.95, 0.95], [0.05, 0.95]],
            "exclude_polygons": [
                [[0.50, 0.41], [0.78, 0.41], [0.78, 0.75], [0.50, 0.75]],
            ],
        },
        {
            "id": "giant_snowball",
            "polygon": [[0.50, 0.41], [0.78, 0.41], [0.78, 0.75], [0.50, 0.75]],
        },
    ]
    return {
        "source": str(output_path),
        "width": w,
        "height": h,
        "parts": parts,
    }


def draw_growth_curves(
    output_path: Path,
    style_cfg: HanddrawStyleConfig,
    size: tuple[int, int] = (600, 600),
) -> dict[str, Any]:
    """Scene 2.2: 线性增长 vs 复利指数曲线（实色累积区对比）。"""
    w, h = size
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    ink = _hex_to_rgb(style_cfg.ink_color)
    accent = _hex_to_rgb(style_cfg.accent_color)
    grid_col = (205, 212, 222)
    linear_col = (200, 208, 216) if style_cfg.style_id != "1" else (232, 232, 232)
    exp_col = (245, 150, 90) if style_cfg.style_id == "10" else (240, 180, 110)

    base_y = 500

    # 1. Coordinate Axes — full frame bars (drawn first, owns only its own pixels)
    # Y-axis bar: x 60..76
    d.rectangle((60, 90, 76, base_y + 16), fill=grid_col, outline=ink, width=5)
    # X-axis bar: y 500..516
    d.rectangle((60, base_y, 540, base_y + 16), fill=grid_col, outline=ink, width=5)
    # Arrow heads
    d.polygon([(52, 90), (84, 90), (68, 58)], fill=ink)
    d.polygon([(540, base_y + 3), (540, base_y + 13), (562, base_y + 8)], fill=ink)

    # 2. Linear accumulation block (left, gentle ramp)
    d.polygon([(84, base_y), (290, base_y), (290, 400), (84, base_y)],
              fill=linear_col, outline=ink, width=5)
    d.line([(84, base_y), (290, 400)], fill=ink, width=6)

    # 3. Exponential accumulation block (right, hockey-stick surge)
    exp_pts = []
    for step in range(40):
        t = step / 39.0
        x = 300 + t * 230
        val = (math.exp(3.0 * t) - 1.0) / (math.exp(3.0) - 1.0)
        y = base_y - val * 390
        exp_pts.append((x, y))
    area_poly = exp_pts + [(530, base_y), (300, base_y)]
    d.polygon(area_poly, fill=exp_col, outline=ink, width=5)
    d.line(exp_pts, fill=accent, width=8)

    # 4. Star marker at the inflection apex
    cx, cy = exp_pts[-1]
    star = []
    for step in range(10):
        r = 20 if step % 2 == 0 else 8
        ang = math.radians(step * 36 - 90)
        star.append((cx + r * math.cos(ang), cy - 30 + r * math.sin(ang)))
    d.polygon(star, fill=accent, outline=ink, width=3)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path)

    parts = [
        {
            "id": "axes_frame",
            "polygon": [[0.05, 0.07], [0.95, 0.07], [0.95, 0.97], [0.05, 0.97]],
            "exclude_polygons": [
                [[0.06, 0.65], [0.44, 0.65], [0.44, 0.84], [0.06, 0.96]],
                [[0.43, 0.18], [0.78, 0.18], [0.78, 0.84], [0.43, 0.84]],
            ],
        },
        {
            "id": "linear_ramp",
            "polygon": [[0.06, 0.65], [0.44, 0.65], [0.44, 0.96], [0.06, 0.96]],
        },
        {
            "id": "exponential_surge",
            "polygon": [[0.43, 0.18], [0.78, 0.18], [0.78, 0.84], [0.43, 0.84]],
        },
    ]
    return {
        "source": str(output_path),
        "width": w,
        "height": h,
        "parts": parts,
    }


def draw_coin_pyramid(
    output_path: Path,
    style_cfg: HanddrawStyleConfig,
    size: tuple[int, int] = (600, 600),
) -> dict[str, Any]:
    """Scene 2.3: 随时间积累的复利资产塔与复利之星。"""
    w, h = size
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    ink = _hex_to_rgb(style_cfg.ink_color)
    accent = _hex_to_rgb(style_cfg.accent_color)
    gold = (245, 205, 60) if style_cfg.style_id != "1" else (235, 235, 235)
    base_col = (180, 200, 220) if style_cfg.style_id != "1" else (225, 225, 225)

    # 1. Base pedestal
    d.rectangle((100, 480, 500, 550), fill=base_col, outline=ink, width=5)

    # 2. Coin stacks: 3 tiers
    # Tier 1 (bottom 4 coins)
    for i, x in enumerate([140, 220, 300, 380]):
        d.rounded_rectangle((x, 410, x + 70, 475), radius=8, fill=gold, outline=ink, width=4)
        d.text((x + 25, 430), "¥", fill=ink)
    # Tier 2 (middle 3 coins)
    for i, x in enumerate([180, 260, 340]):
        d.rounded_rectangle((x, 335, x + 70, 400), radius=8, fill=gold, outline=ink, width=4)
        d.text((x + 25, 355), "¥", fill=ink)
    # Tier 3 (top 2 coins)
    for i, x in enumerate([220, 300]):
        d.rounded_rectangle((x, 260, x + 70, 325), radius=8, fill=gold, outline=ink, width=4)
        d.text((x + 25, 280), "¥", fill=ink)

    # 3. Top Star of Compounding
    cx, cy, r_outer, r_inner = 300, 150, 65, 28
    star_pts = []
    for step in range(10):
        r = r_outer if step % 2 == 0 else r_inner
        angle = math.radians(step * 36 - 90)
        star_pts.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))
    d.polygon(star_pts, fill=accent, outline=ink)
    # Sparkle rays
    for angle in [0, 45, 90, 135, 180, 225, 270, 315]:
        rad = math.radians(angle)
        x1 = cx + 80 * math.cos(rad)
        y1 = cy + 80 * math.sin(rad)
        x2 = cx + 115 * math.cos(rad)
        y2 = cy + 115 * math.sin(rad)
        d.line([(x1, y1), (x2, y2)], fill=accent, width=4)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path)

    parts = [
        {
            "id": "compounding_star",
            "polygon": [[0.20, 0.05], [0.80, 0.05], [0.80, 0.45], [0.20, 0.45]],
        },
        {
            "id": "coin_stacks",
            "polygon": [[0.10, 0.40], [0.90, 0.40], [0.90, 0.98], [0.10, 0.98]],
        },
    ]
    return {
        "source": str(output_path),
        "width": w,
        "height": h,
        "parts": parts,
    }


# Map of standard scene templates
ILLUSTRATION_BUILDERS = {
    "anger_brain": draw_anger_brain,
    "balance_scale": draw_balance_scale,
    "calm_decision": draw_calm_decision,
    "snowball_effect": draw_snowball_effect,
    "growth_curves": draw_growth_curves,
    "coin_pyramid": draw_coin_pyramid,
}


def build_scene_illustration(
    scene_key: str,
    output_path: Path,
    style_id: str | int = "8",
    size: tuple[int, int] = (600, 600),
) -> dict[str, Any]:
    """Generate illustration and parts metadata for a named scene."""
    if scene_key not in ILLUSTRATION_BUILDERS:
        raise ValueError(
            f"Unknown scene key '{scene_key}'. Supported: {list(ILLUSTRATION_BUILDERS.keys())}"
        )
    cfg = get_style_config(style_id)
    return ILLUSTRATION_BUILDERS[scene_key](output_path, cfg, size)
