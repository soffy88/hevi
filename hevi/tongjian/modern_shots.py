"""现代白话讲解风镜头(N0-D-022 白话优先·视觉层，opt-in)——扁平信息卡,零 provider。

对照 quote_shots.py 的古典纸雕(竹简/剪纸对勘/竖排题字),本模块给白话样片一套**现代讲解风**:
- render_modern_title:横排白话要点卡(左侧色条 + 大字白话标题),取代竖排文言题字落款;
- render_modern_compare:两张扁平圆角对比卡(《左传》/《史记》做彩色小 chip),取代剪纸双半幅;
- 文言原文仅作**右下小角标**(可选),不占画面主体。

背景走干净浅灰(非宣纸做旧),整体现代信息图观感。仅白话样片装配调用,不改古典产线。
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from hevi.tongjian.map_anim import ease_out_back
from hevi.tongjian.quote_shots import FONT, _encode

# ── 现代扁平调色 ──
_BG_TOP = (244, 245, 247)
_BG_BOT = (232, 234, 238)
_CARD = (255, 255, 255)
_CARD_BD = (223, 226, 231)
_TEXT = (33, 37, 41)
_SUBTLE = (110, 118, 128)
_SHADOW = (17, 20, 24)


def _grad_bg(w: int, h: int) -> Image.Image:
    """干净浅灰竖向微渐变底(非宣纸做旧)。"""
    bg = Image.new("RGB", (w, h), _BG_TOP)
    px = bg.load()
    for y in range(h):
        t = y / max(1, h - 1)
        r = int(_BG_TOP[0] + (_BG_BOT[0] - _BG_TOP[0]) * t)
        g = int(_BG_TOP[1] + (_BG_BOT[1] - _BG_TOP[1]) * t)
        b = int(_BG_TOP[2] + (_BG_BOT[2] - _BG_TOP[2]) * t)
        for x in range(w):
            px[x, y] = (r, g, b)
    return bg


def _soft_card(base: Image.Image, box, radius: int = 18, shadow: int = 10) -> None:
    """在 base(RGBA)上画带柔和投影的白色圆角卡。box=(x0,y0,x1,y1)。就地绘制。"""
    x0, y0, x1, y1 = box
    sh = Image.new("RGBA", base.size, (0, 0, 0, 0))
    sd = ImageDraw.Draw(sh)
    sd.rounded_rectangle([x0, y0 + shadow, x1, y1 + shadow], radius=radius, fill=(*_SHADOW, 46))
    sh = sh.filter(__import__("PIL.ImageFilter", fromlist=["GaussianBlur"]).GaussianBlur(9))
    base.alpha_composite(sh)
    d = ImageDraw.Draw(base)
    d.rounded_rectangle(box, radius=radius, fill=(*_CARD, 255), outline=(*_CARD_BD, 255), width=2)


def _wrap(s: str, per: int) -> list[str]:
    return [s[i : i + per] for i in range(0, len(s), per)] or [""]


def render_modern_title(
    title: str,
    out_dir: Path,
    *,
    size: tuple[int, int] = (1168, 784),
    fps: int = 24,
    duration_s: float = 4.0,
    font_path: str = FONT,
    accent: tuple[int, int, int] = (214, 69, 65),
    wenyan: str = "",
) -> Path:
    """现代白话要点卡:浅灰底 + 居中大字白话标题 + 左侧色条;可选文言原文作右下小角标。"""
    w, h = size
    out_dir = Path(out_dir)
    fd = out_dir / "frames_mtitle"
    fd.mkdir(parents=True, exist_ok=True)
    n = max(1, int(fps * duration_s))
    fbig = ImageFont.truetype(font_path, 48)
    fsmall = ImageFont.truetype(font_path, 22)
    bg0 = _grad_bg(w, h).convert("RGBA")
    lines = _wrap(title, 13)
    card_w, line_h = int(w * 0.68), 70
    card_h = 80 + len(lines) * line_h
    cx0 = (w - card_w) // 2
    cy0 = (h - card_h) // 2 - 20
    for f in range(n):
        t = f / (n - 1) if n > 1 else 1.0
        e = ease_out_back(max(0.0, min(1.0, (t - 0.05) / 0.5)))
        frame = bg0.copy()
        dy = int((1 - e) * 34)
        _soft_card(frame, (cx0, cy0 + dy, cx0 + card_w, cy0 + card_h + dy), radius=22)
        d = ImageDraw.Draw(frame)
        # 左侧强调色条
        d.rounded_rectangle(
            [cx0 + 26, cy0 + 30 + dy, cx0 + 36, cy0 + card_h - 30 + dy],
            radius=5,
            fill=(*accent, 255),
        )
        if e > 0.6:
            yy = cy0 + 44 + dy
            for ln in lines:
                d.text((cx0 + 60, yy), ln, font=fbig, fill=(*_TEXT, 255))
                yy += line_h
        # 文言点睛:原文一行居中显在卡片下方(白话为主、文言点睛;避开底部字幕带)
        if wenyan and e > 0.9:
            tag = "「" + wenyan + "」"
            bb = d.textbbox((0, 0), tag, font=fsmall)
            tw = bb[2] - bb[0]
            ty = cy0 + card_h + dy + 34
            # 左侧引文竖条 + 原文(弱化灰),整体居中
            d.text(((w - tw) // 2, ty), tag, font=fsmall, fill=(*_SUBTLE, 240))
        frame.convert("RGB").save(fd / f"f_{f:04d}.png")
    return _encode(fd, out_dir / "modern_title.mp4", fps)


def render_modern_compare(
    dual,
    out_dir: Path,
    *,
    size: tuple[int, int] = (1168, 784),
    fps: int = 24,
    duration_s: float = 5.0,
    font_path: str = FONT,
) -> Path:
    """现代两栏对比卡:浅灰底 + 顶部『两种记载·{维度}』chip + 左右两张扁平白卡(源作彩色 chip)。"""
    w, h = size
    out_dir = Path(out_dir)
    fd = out_dir / "frames_mcompare"
    fd.mkdir(parents=True, exist_ok=True)
    n = max(1, int(fps * duration_s))
    fhead = ImageFont.truetype(font_path, 30)
    fchip = ImageFont.truetype(font_path, 25)
    fbody = ImageFont.truetype(font_path, 28)
    a0, a1 = dual.accounts[0], dual.accounts[1]
    bg0 = _grad_bg(w, h).convert("RGBA")
    card_w, card_h = int(w * 0.42), int(h * 0.56)
    top = int(h * 0.26)
    gap = 30
    lx = w // 2 - gap - card_w
    rx = w // 2 + gap
    chip_cols = [(214, 69, 65), (54, 116, 217)]  # 左传红 / 史记蓝(现代色)
    for f in range(n):
        t = f / (n - 1) if n > 1 else 1.0
        e = ease_out_back(max(0.0, min(1.0, (t - 0.05) / 0.5)))
        frame = bg0.copy()
        d = ImageDraw.Draw(frame)
        # 顶部对比题 chip
        head = f"两种记载 · {dual.dimension}"
        bb = d.textbbox((0, 0), head, font=fhead)
        hw = bb[2] - bb[0]
        hx = (w - hw) // 2
        d.rounded_rectangle(
            [hx - 22, top - 74, hx + hw + 22, top - 22], radius=16, fill=(46, 50, 58, 255)
        )
        d.text((hx, top - 68), head, font=fhead, fill=(245, 246, 248, 255))
        for i, (x, acc, col) in enumerate(((lx, a0, chip_cols[0]), (rx, a1, chip_cols[1]))):
            dy = int((1 - e) * (28 + i * 10))
            _soft_card(frame, (x, top + dy, x + card_w, top + card_h + dy), radius=18)
            if e > 0.75:
                dd = ImageDraw.Draw(frame)
                # 源 chip(彩色圆角标签)
                src = acc.source_display
                sb = dd.textbbox((0, 0), src, font=fchip)
                sw = sb[2] - sb[0]
                dd.rounded_rectangle(
                    [x + 24, top + 24 + dy, x + 24 + sw + 28, top + 24 + 42 + dy],
                    radius=13,
                    fill=(*col, 255),
                )
                dd.text((x + 38, top + 30 + dy), src, font=fchip, fill=(255, 255, 255, 255))
                yy = top + 92 + dy
                for ln in _wrap(acc.summary, 12):
                    dd.text((x + 26, yy), ln, font=fbody, fill=(*_TEXT, 255))
                    yy += 40
        frame.convert("RGB").save(fd / f"f_{f:04d}.png")
    return _encode(fd, out_dir / "modern_compare.mp4", fps)
