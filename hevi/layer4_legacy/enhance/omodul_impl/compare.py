"""Before/after comparison sheets for the enhancement ops (real pixels)."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

_LABEL_H = 34
_PAD = 12
_BG = (24, 24, 28)
_FG = (238, 238, 238)


def _font(size: int = 20) -> ImageFont.ImageFont:
    for candidate in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ):
        if Path(candidate).is_file():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


def _load(path: str | Path) -> Image.Image:
    img = Image.open(path)
    return img.convert("RGB") if img.mode not in ("RGB", "RGBA") else img


def build_comparison_sheet(
    before: str | Path,
    after: str | Path,
    output_path: str | Path,
    *,
    title: str = "",
    labels: tuple[str, str] = ("BEFORE", "AFTER"),
) -> dict[str, object]:
    """Compose a labelled before/after sheet. Returns measured sheet geometry."""
    left = _load(before)
    right = _load(after)
    # Normalise both panels to the same height for a clean side-by-side.
    target_h = max(left.height, right.height)

    def _fit(img: Image.Image) -> Image.Image:
        if img.height == target_h:
            return img
        w = max(1, round(img.width * target_h / img.height))
        return img.resize((w, target_h), Image.Resampling.LANCZOS)

    left, right = _fit(left), _fit(right)
    title_h = _LABEL_H if title else 0
    width = _PAD + left.width + _PAD + right.width + _PAD
    height = _PAD + title_h + left.height + _LABEL_H + _PAD
    sheet = Image.new("RGB", (width, height), _BG)
    draw = ImageDraw.Draw(sheet)
    font = _font(20)
    small = _font(16)

    y = _PAD
    if title:
        draw.text((_PAD, y), title, fill=_FG, font=font)
        y += title_h
    lx = _PAD
    rx = _PAD + left.width + _PAD
    draw.text((lx, y), labels[0], fill=(255, 190, 120), font=small)
    draw.text((rx, y), labels[1], fill=(140, 235, 170), font=small)
    y += _LABEL_H
    if left.mode == "RGBA":
        bg = Image.new("RGB", left.size, (60, 60, 66))
        bg.paste(left, mask=left.split()[3])
        left = bg
    if right.mode == "RGBA":
        bg = Image.new("RGB", right.size, (60, 60, 66))
        bg.paste(right, mask=right.split()[3])
        right = bg
    sheet.paste(left, (lx, y))
    sheet.paste(right, (rx, y))

    dest = Path(output_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(dest)
    return {
        "sheet": str(dest),
        "width": sheet.width,
        "height": sheet.height,
        "before": str(before),
        "after": str(after),
    }


__all__ = ["build_comparison_sheet"]
