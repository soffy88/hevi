"""Stitches keyframe proofs into a high-resolution overview contact sheet (Gate 2)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont


def create_proof_sheet(
    keyframes: list[dict[str, Any]],
    out_path: Path | str,
    title: str = "RISO B-ROLL PROOF SHEET // 样帧总览",
) -> Path:
    """Generate a clean contact sheet of all rendered keyframe proofs.

    keyframes: list of dicts with:
      - 'keyframe_png': Path
      - 'clip_id': str
      - 'template': str
      - 'duration': float
      - 'palette': str
    """
    out_file = Path(out_path).resolve()
    out_file.parent.mkdir(parents=True, exist_ok=True)

    n = len(keyframes)
    if n == 0:
        raise ValueError("No keyframes provided for proof sheet")

    # Grid dimensions: 4 columns or 3 columns
    cols = 4 if n >= 4 else n
    rows = (n + cols - 1) // cols

    thumb_w = 400
    thumb_h = int(thumb_w * (1920 / 1080))  # ~711px
    card_pad = 30
    header_h = 140
    footer_h = 60

    total_w = card_pad + cols * (thumb_w + card_pad)
    total_h = header_h + rows * (thumb_h + 90 + card_pad) + footer_h

    sheet = Image.new("RGB", (total_w, total_h), color=(244, 238, 225))
    draw = ImageDraw.Draw(sheet)

    # Header
    draw.rectangle([0, 0, total_w, header_h], fill=(15, 30, 54))
    draw.text((card_pad, 36), title, fill=(244, 238, 225))
    draw.text(
        (card_pad, 84),
        f"TOTAL CLIPS: {n}  //  COLOR SEPARATION: 2-COLOR SPOT  //  RESOLUTION: 1080x1920 30FPS",
        fill=(255, 42, 133),
    )

    for i, item in enumerate(keyframes):
        c = i % cols
        r = i // cols

        x = card_pad + c * (thumb_w + card_pad)
        y = header_h + card_pad + r * (thumb_h + 90 + card_pad)

        img_path = Path(item["keyframe_png"])
        if img_path.exists():
            thumb = Image.open(img_path).convert("RGB")
            thumb = thumb.resize((thumb_w, thumb_h), Image.Resampling.LANCZOS)
            sheet.paste(thumb, (x, y))

            # Border around thumbnail
            draw.rectangle([x, y, x + thumb_w, y + thumb_h], outline=(15, 30, 54), width=3)
        else:
            draw.rectangle([x, y, x + thumb_w, y + thumb_h], fill=(230, 220, 205), outline=(15, 30, 54))
            draw.text((x + 20, y + thumb_h // 2), "[MISSING PROOF]", fill=(200, 30, 30))

        # Metadata caption below thumbnail
        info_y = y + thumb_h + 10
        clip_id = item.get("clip_id", f"clip_{i+1:02d}")
        tpl = item.get("template", "unknown")
        dur = item.get("duration", 0.0)
        pal = item.get("palette", "")

        draw.rectangle([x, info_y, x + thumb_w, info_y + 70], fill=(255, 255, 255), outline=(15, 30, 54), width=2)
        draw.text((x + 10, info_y + 10), f"#{i+1:02d} [{clip_id}] // {tpl.upper()}", fill=(15, 30, 54))
        draw.text((x + 10, info_y + 38), f"DURATION: {dur:.1f}s | {pal}", fill=(100, 100, 100))

    sheet.save(out_file, format="PNG")
    return out_file
