"""Contact sheets are review projections, never canonical evidence."""

from __future__ import annotations

from pathlib import Path


def build_contact_sheet(
    frame_paths: list[str | Path],
    output: str | Path,
    *,
    columns: int = 5,
    max_frames: int | None = None,
    tile_width: int | None = None,
    tile_height: int | None = None,
    timestamps_ms: list[int] | None = None,
    words: list[str] | None = None,
    labels: list[str] | None = None,
) -> Path:
    if not frame_paths:
        raise ValueError("FRAME_EXTRACTION_FAILED:no_frames")
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError as exc:
        raise RuntimeError("CONTACT_SHEET_FAILED:pillow_unavailable") from exc

    limit = max_frames if max_frames is not None else 25
    active_paths = frame_paths[:limit]
    images: list[Image.Image] = [Image.open(path).convert("RGB") for path in active_paths]

    # Target tile sizing
    orig_w = max(image.width for image in images)
    orig_h = max(image.height for image in images)
    tw = tile_width or (320 if orig_w > 480 else orig_w)
    th = tile_height or int(round(tw * (orig_h / orig_w)))

    has_banner = bool(words or labels or timestamps_ms)
    banner_h = 36 if has_banner else 0
    cell_h = th + banner_h

    rows = (len(images) + columns - 1) // columns
    sheet = Image.new("RGB", (tw * columns, cell_h * rows), "#111115")
    draw = ImageDraw.Draw(sheet)

    for index, image in enumerate(images):
        col = index % columns
        row = index // columns
        x, y = col * tw, row * cell_h

        # Resize image tile
        if image.size != (tw, th):
            resized = image.resize((tw, th), Image.Resampling.LANCZOS)
        else:
            resized = image
        sheet.paste(resized, (x, y))

        # Top-left index or timecode badge
        ts_text = ""
        if timestamps_ms and index < len(timestamps_ms):
            sec = timestamps_ms[index] / 1000.0
            ts_text = f"{int(sec // 60):02d}:{sec % 60:04.1f}"
        badge = ts_text if ts_text else str(index + 1)
        badge_w = max(24, len(badge) * 8 + 8)
        draw.rectangle((x, y, x + badge_w, y + 20), fill="#000000CC")
        draw.text((x + 4, y + 2), badge, fill="#FFFFFF")

        # Bottom banner with spoken words / annotations
        if has_banner:
            banner_y = y + th
            draw.rectangle((x, banner_y, x + tw, banner_y + banner_h), fill="#1c1c24")
            draw.line((x, banner_y, x + tw, banner_y), fill="#333340", width=1)
            caption = ""
            if words and index < len(words) and words[index]:
                caption = str(words[index])
            elif labels and index < len(labels) and labels[index]:
                caption = str(labels[index])
            if caption:
                # Truncate if too long for tile width
                max_chars = max(10, tw // 14)
                if len(caption) > max_chars:
                    caption = caption[: max_chars - 1] + "…"
                draw.text((x + 6, banner_y + 8), caption, fill="#FFDD66")

    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(destination, format="JPEG", quality=90)
    return destination
