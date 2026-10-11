"""Physical product footage, background removal, and product card compositing (oskill layer)."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFilter, ImageFont


def remove_product_background(
    input_image_path: str | Path,
    output_png_path: str | Path,
    *,
    session: Any = None,
) -> Path:
    """Remove background from product photo using rembg (u2net on CPU)."""
    import rembg

    inp = Image.open(input_image_path).convert("RGBA")
    if session is None:
        session = rembg.new_session("u2net")

    cutout = rembg.remove(inp, session=session)
    dest = Path(output_png_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    cutout.save(dest, format="PNG")
    return dest


THEMES: dict[str, dict[str, Any]] = {
    "light": {
        "bg_top": (245, 246, 250),
        "bg_bottom": (222, 229, 240),
        "title": (22, 24, 34),
        "tag_fill": (255, 240, 230),
        "tag_outline": (255, 120, 50),
        "tag_text": (214, 78, 18),
        "price": (226, 32, 42),
        "button": (238, 52, 62),
        "button_text": (255, 255, 255),
    },
    "dark": {
        "bg_top": (16, 18, 26),
        "bg_bottom": (32, 38, 54),
        "title": (245, 247, 252),
        "tag_fill": (44, 40, 30),
        "tag_outline": (255, 196, 92),
        "tag_text": (255, 205, 110),
        "price": (255, 196, 92),
        "button": (255, 176, 32),
        "button_text": (24, 20, 12),
    },
    "warm": {
        "bg_top": (252, 244, 234),
        "bg_bottom": (240, 222, 202),
        "title": (74, 44, 24),
        "tag_fill": (255, 236, 214),
        "tag_outline": (222, 120, 44),
        "tag_text": (170, 78, 20),
        "price": (196, 40, 44),
        "button": (224, 108, 36),
        "button_text": (255, 255, 255),
    },
}


def _fit_font(
    draw: ImageDraw.ImageDraw,
    text: str,
    *,
    font_path: str,
    start_size: int,
    max_width: int,
    min_size: int = 14,
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Shrink a TrueType font until ``text`` fits within ``max_width`` pixels."""
    size = max(min_size, int(start_size))
    while size > min_size:
        try:
            font = ImageFont.truetype(font_path, size)
        except Exception:
            return ImageFont.load_default()
        try:
            left, _, right, _ = draw.textbbox((0, 0), text, font=font)
        except Exception:
            return font
        if (right - left) <= max_width:
            return font
        size -= 2
    try:
        return ImageFont.truetype(font_path, min_size)
    except Exception:
        return ImageFont.load_default()


def composite_product_card_frame(
    cutout_path: str | Path,
    width: int,
    height: int,
    *,
    zoom_factor: float = 1.0,
    pan_offset_y: float = 0.0,
    product_title: str = "精选正品",
    price_tag: str = "¥99",
    cta_text: str = "立即抢购",
    selling_points: list[str] | None = None,
    theme: str = "light",
    font_path: str = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
) -> Image.Image:
    """Composite a clean, non-overlapping product card.

    Vertical zones are reserved explicitly and the bottom band is kept free so
    burned-in subtitles never collide with the price/CTA. Layout (fractions of
    height): product image ~0.06-0.44, title 0.50, selling points 0.60, price
    0.69, CTA button 0.77, subtitle-safe zone >= 0.85.
    """
    palette = THEMES.get(theme, THEMES["light"])

    # 1. Background gradient
    canvas = Image.new("RGBA", (width, height), (*palette["bg_top"], 255))
    draw = ImageDraw.Draw(canvas)
    top = palette["bg_top"]
    bottom = palette["bg_bottom"]
    for y in range(height):
        ratio = y / max(1, height - 1)
        color = tuple(int(top[i] + (bottom[i] - top[i]) * ratio) for i in range(3))
        draw.line([(0, y), (width, y)], fill=(*color, 255))

    # 2. Product cutout with drop shadow (upper display area)
    cutout = Image.open(cutout_path).convert("RGBA")
    max_pw = int(width * 0.62 * zoom_factor)
    max_ph = int(height * 0.38 * zoom_factor)
    cutout.thumbnail((max_pw, max_ph), Image.Resampling.LANCZOS)
    pw, ph = cutout.size
    px = (width - pw) // 2
    py = int(height * 0.26 - ph / 2 + pan_offset_y)

    shadow = Image.new("RGBA", (pw + 80, ph + 80), (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_draw.ellipse([20, ph + 10, pw + 60, ph + 55], fill=(0, 0, 0, 90))
    shadow = shadow.filter(ImageFilter.GaussianBlur(16))
    canvas.alpha_composite(shadow, (px - 40, py - 40))
    canvas.alpha_composite(cutout, (px, py))

    # 3. Typography
    title_font = _fit_font(
        draw,
        product_title,
        font_path=font_path,
        start_size=int(width * 0.052),
        max_width=int(width * 0.88),
    )
    price_font = _fit_font(
        draw,
        price_tag,
        font_path=font_path,
        start_size=int(width * 0.045),
        max_width=int(width * 0.8),
    )
    try:
        tag_font = ImageFont.truetype(font_path, max(14, int(width * 0.026)))
        cta_font = ImageFont.truetype(font_path, max(16, int(width * 0.036)))
    except Exception:
        tag_font = ImageFont.load_default()
        cta_font = ImageFont.load_default()

    # Title (single dedicated line)
    title_y = int(height * 0.48)
    draw.text((width // 2, title_y), product_title, fill=(*palette["title"], 255), font=title_font, anchor="mm")

    # Selling-point badges (single dedicated line, evenly spaced)
    points = (selling_points or ["权威实测", "官方正品", "极速发货"])[:3]
    tag_y = int(height * 0.575)
    tag_h = max(24, int(height * 0.05))
    tag_w = int(width * 0.26)
    gap = int(width * 0.03)
    total_w = len(points) * tag_w + max(0, len(points) - 1) * gap
    start_x = (width - total_w) // 2
    for i, pt in enumerate(points):
        tx0 = start_x + i * (tag_w + gap)
        draw.rounded_rectangle(
            [tx0, tag_y - tag_h // 2, tx0 + tag_w, tag_y + tag_h // 2],
            radius=tag_h // 2,
            fill=(*palette["tag_fill"], 255),
            outline=(*palette["tag_outline"], 255),
            width=2,
        )
        draw.text((tx0 + tag_w // 2, tag_y), pt, fill=(*palette["tag_text"], 255), font=tag_font, anchor="mm")

    # Price (dedicated line)
    price_y = int(height * 0.66)
    draw.text((width // 2, price_y), price_tag, fill=(*palette["price"], 255), font=price_font, anchor="mm")

    # CTA button (dedicated line, above the subtitle-safe zone)
    btn_y = int(height * 0.77)
    btn_h = max(34, int(height * 0.075))
    btn_w = int(width * 0.62)
    draw.rounded_rectangle(
        [(width - btn_w) // 2, btn_y - btn_h // 2, (width + btn_w) // 2, btn_y + btn_h // 2],
        radius=btn_h // 2,
        fill=(*palette["button"], 255),
    )
    draw.text((width // 2, btn_y), cta_text, fill=(*palette["button_text"], 255), font=cta_font, anchor="mm")

    return canvas.convert("RGB")


def render_product_card_animation_frames(
    cutout_path: str | Path,
    output_dir: str | Path,
    width: int,
    height: int,
    *,
    duration_s: float = 3.0,
    fps: int = 25,
    product_title: str = "精选正品",
    price_tag: str = "¥99",
    cta_text: str = "立即抢购",
    selling_points: list[str] | None = None,
    theme: str = "light",
) -> list[Path]:
    """Render a sequence of frames with subtle Ken Burns zoom and breathing."""
    dest = Path(output_dir)
    dest.mkdir(parents=True, exist_ok=True)
    total_frames = int(round(duration_s * fps))
    frame_paths: list[Path] = []

    for i in range(total_frames):
        t = i / max(1, total_frames - 1)
        # Ken Burns slow smooth zoom-in from 0.98 to 1.05
        zoom = 0.98 + 0.07 * (1.0 - math.cos(t * math.pi / 2))
        pan_y = -10.0 * math.sin(t * math.pi)

        frame = composite_product_card_frame(
            cutout_path=cutout_path,
            width=width,
            height=height,
            zoom_factor=zoom,
            pan_offset_y=pan_y,
            product_title=product_title,
            price_tag=price_tag,
            cta_text=cta_text,
            selling_points=selling_points,
            theme=theme,
        )
        fpath = dest / f"frame_{i:04d}.png"
        frame.save(fpath, format="PNG")
        frame_paths.append(fpath)

    return frame_paths
