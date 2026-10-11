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
    font_path: str = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
) -> Image.Image:
    """Composite clean product card with drop shadow, stickers, price, and CTA."""
    # 1. Background gradient (clean modern e-commerce card)
    canvas = Image.new("RGBA", (width, height), (245, 246, 250, 255))
    draw = ImageDraw.Draw(canvas)

    # Gradient overlay
    for y in range(height):
        ratio = y / height
        r = int(245 - 20 * ratio)
        g = int(246 - 15 * ratio)
        b = int(250 - 5 * ratio)
        draw.line([(0, y), (width, y)], fill=(r, g, b, 255))

    # 2. Product cutout with drop shadow
    cutout = Image.open(cutout_path).convert("RGBA")

    # Fit product in central display area
    max_pw = int(width * 0.75 * zoom_factor)
    max_ph = int(height * 0.45 * zoom_factor)
    cutout.thumbnail((max_pw, max_ph), Image.Resampling.LANCZOS)
    pw, ph = cutout.size

    # Position product
    px = (width - pw) // 2
    py = int((height * 0.35) - (ph // 2) + pan_offset_y)

    # Generate drop shadow
    shadow = Image.new("RGBA", (pw + 60, ph + 60), (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    # Ellipse shadow base
    shadow_draw.ellipse(
        [15, ph + 10, pw + 45, ph + 45],
        fill=(0, 0, 0, 80),
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(14))
    canvas.alpha_composite(shadow, (px - 30, py - 30))

    # Paste product
    canvas.alpha_composite(cutout, (px, py))

    # 3. Product Title & Selling Point Badges
    try:
        font_large = ImageFont.truetype(font_path, int(width * 0.065))
        font_med = ImageFont.truetype(font_path, int(width * 0.045))
        font_small = ImageFont.truetype(font_path, int(width * 0.038))
    except Exception:
        font_large = ImageFont.load_default()
        font_med = ImageFont.load_default()
        font_small = ImageFont.load_default()

    # Product Title
    title_y = int(height * 0.62)
    draw.text((width // 2, title_y), product_title, fill=(20, 20, 30, 255), font=font_large, anchor="mm")

    # Selling points tags
    points = selling_points or ["权威实测", "官方正品", "极速发货"]
    tag_y = title_y + int(height * 0.055)
    tag_spacing = int(width * 0.28)
    start_tag_x = (width - (len(points) - 1) * tag_spacing) // 2
    for i, pt in enumerate(points[:3]):
        tx = start_tag_x + i * tag_spacing
        tag_w = int(width * 0.24)
        tag_h = int(height * 0.036)
        draw.rounded_rectangle(
            [tx - tag_w // 2, tag_y - tag_h // 2, tx + tag_w // 2, tag_y + tag_h // 2],
            radius=8,
            fill=(255, 240, 230, 255),
            outline=(255, 120, 50, 255),
            width=2,
        )
        draw.text((tx, tag_y), pt, fill=(220, 80, 20, 255), font=font_small, anchor="mm")

    # 4. Price & CTA Banner
    bottom_y = int(height * 0.82)
    # Price
    draw.text((width // 2, bottom_y), price_tag, fill=(230, 30, 40, 255), font=font_large, anchor="mm")

    # CTA Button
    btn_y = bottom_y + int(height * 0.075)
    btn_w = int(width * 0.72)
    btn_h = int(height * 0.065)
    draw.rounded_rectangle(
        [(width - btn_w) // 2, btn_y - btn_h // 2, (width + btn_w) // 2, btn_y + btn_h // 2],
        radius=int(btn_h // 2),
        fill=(240, 50, 60, 255),
    )
    draw.text((width // 2, btn_y), cta_text, fill=(255, 255, 255, 255), font=font_med, anchor="mm")

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
        )
        fpath = dest / f"frame_{i:04d}.png"
        frame.save(fpath, format="PNG")
        frame_paths.append(fpath)

    return frame_paths
