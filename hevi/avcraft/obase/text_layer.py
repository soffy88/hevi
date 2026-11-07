"""文字图层：Pillow 把标题渲染成透明 PNG（ffmpeg 静态版无 drawtext，用 overlay 合成）。"""

from __future__ import annotations

from pathlib import Path

_FONT_CANDIDATES = (
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
)


def find_font(prefer: str | None = None) -> str | None:
    for p in ((prefer,) if prefer else ()) + _FONT_CANDIDATES:
        if p and Path(p).exists():
            return p
    return None


def _rgba(c: str) -> tuple:
    c = c.lstrip("#")
    if len(c) == 6:
        c += "ff"
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4, 6))


def render_text_png(text: str, dst: str | Path, *, fontsize: int = 96, color: str = "#FFFFFF",
                    font: str | None = None, pad: int = 16, stroke: int = 0,
                    stroke_color: str = "#000000") -> dict:
    """单行文字 → 透明 PNG。返回 {path,w,h,char_x}，char_x[i] = 前 i+1 个字符的右边界（像素，含 pad），供打字机逐字揭示。"""
    from PIL import Image, ImageDraw, ImageFont

    fp = find_font(font)
    f = ImageFont.truetype(fp, fontsize) if fp else ImageFont.load_default()
    l, t, r, b = f.getbbox(text, stroke_width=stroke)
    w, h = (r - l) + 2 * pad, (b - t) + 2 * pad
    w += w % 2
    h += h % 2
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(im).text((pad - l, pad - t), text, font=f, fill=_rgba(color),
                            stroke_width=stroke, stroke_fill=_rgba(stroke_color))
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    im.save(dst)
    char_x = [min(w, int(round(pad - l + f.getlength(text[: i + 1])))) for i in range(len(text))]
    return {"path": str(dst), "w": w, "h": h, "char_x": char_x, "font": fp}
