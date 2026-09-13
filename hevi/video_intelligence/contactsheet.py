"""Contact sheets are review projections, never canonical evidence."""

from __future__ import annotations

from pathlib import Path


def build_contact_sheet(frame_paths: list[str | Path], output: str | Path, *, columns: int = 5) -> Path:
    if not frame_paths:
        raise ValueError("FRAME_EXTRACTION_FAILED:no_frames")
    try:
        from PIL import Image, ImageDraw
    except ImportError as exc:
        raise RuntimeError("CONTACT_SHEET_FAILED:pillow_unavailable") from exc
    images = [Image.open(path).convert("RGB") for path in frame_paths[:25]]
    width = max(image.width for image in images)
    height = max(image.height for image in images)
    rows = (len(images) + columns - 1) // columns
    sheet = Image.new("RGB", (width * columns, height * rows), "black")
    draw = ImageDraw.Draw(sheet)
    for index, image in enumerate(images):
        x, y = (index % columns) * width, (index // columns) * height
        sheet.paste(image, (x, y))
        draw.rectangle((x, y, x + 20, y + 20), fill="black")
        draw.text((x + 4, y + 2), str(index + 1), fill="white")
    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(destination, format="JPEG", quality=90)
    return destination
