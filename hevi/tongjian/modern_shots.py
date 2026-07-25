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


# ── N0-D-033 子拍出画:轻动效 + 申生抉择点专用镜头 ──
def _kenburns(frame: Image.Image, t: float, zoom: float = 0.06, phase: int = 0):
    """缓慢推近/横移(ken-burns),给静止卡内加动。t∈[0,1],phase 决定方向,零 provider。"""
    w, h = frame.size
    z = 1.0 + zoom * (t if phase % 2 == 0 else (1 - t))
    cw, ch = int(w / z), int(h / z)
    # phase 决定裁切锚点(左/右/中),制造不同构图
    ax = {0: 0.5, 1: 0.35, 2: 0.65, 3: 0.5}.get(phase % 4, 0.5)
    x0 = int((w - cw) * ax)
    y0 = int((h - ch) * 0.5)
    return frame.crop((x0, y0, x0 + cw, y0 + ch)).resize((w, h))


def render_point_card(
    text: str,
    out_dir: Path,
    *,
    size: tuple[int, int] = (1168, 784),
    fps: int = 24,
    duration_s: float = 4.0,
    font_path: str = FONT,
    accent: tuple[int, int, int] = (214, 69, 65),
    kicker: str = "",
    variant: int = 0,
) -> Path:
    """现代要点卡(子拍通用):浅灰底 + 左色条 + kicker 小标 + 正文;带缓入+ken-burns 微动。"""
    w, h = size
    out_dir = Path(out_dir)
    fd = out_dir / "frames_point"
    fd.mkdir(parents=True, exist_ok=True)
    n = max(1, int(fps * duration_s))
    fbody = ImageFont.truetype(font_path, 40)
    fk = ImageFont.truetype(font_path, 24)
    bg0 = _grad_bg(w, h).convert("RGBA")
    lines = _wrap(text, 15)
    card_w, line_h = int(w * 0.72), 62
    card_h = 96 + len(lines) * line_h
    cx0 = (w - card_w) // 2
    cy0 = (h - card_h) // 2 - 10
    for f in range(n):
        t = f / (n - 1) if n > 1 else 1.0
        e = ease_out_back(max(0.0, min(1.0, (t - 0.04) / 0.45)))
        frame = bg0.copy()
        dy = int((1 - e) * 30)
        _soft_card(frame, (cx0, cy0 + dy, cx0 + card_w, cy0 + card_h + dy), radius=22)
        d = ImageDraw.Draw(frame)
        d.rounded_rectangle(
            [cx0 + 26, cy0 + 34 + dy, cx0 + 36, cy0 + card_h - 34 + dy],
            radius=5,
            fill=(*accent, 255),
        )
        yy = cy0 + 30 + dy
        if kicker:
            d.text((cx0 + 60, yy), kicker, font=fk, fill=(*accent, 255))
            yy += 44
        if e > 0.5:
            for ln in lines:
                d.text((cx0 + 60, yy), ln, font=fbody, fill=(*_TEXT, 255))
                yy += line_h
        frame = _kenburns(frame.convert("RGB"), t, zoom=0.05, phase=variant).convert("RGBA")
        frame.convert("RGB").save(fd / f"f_{f:04d}.png")
    return _encode(fd, out_dir / "point.mp4", fps)


def render_choice_card(
    situation: str,
    choices: list[str],
    out_dir: Path,
    *,
    size: tuple[int, int] = (1168, 784),
    fps: int = 24,
    duration_s: float = 6.0,
    font_path: str = FONT,
) -> Path:
    """申生三条路:顶部处境 + 三张分支卡依次亮起(辩白/出逃/一死),吕祖谦框架进画面。"""
    w, h = size
    out_dir = Path(out_dir)
    fd = out_dir / "frames_choice"
    fd.mkdir(parents=True, exist_ok=True)
    n = max(1, int(fps * duration_s))
    fh = ImageFont.truetype(font_path, 30)
    fc = ImageFont.truetype(font_path, 34)
    fn = ImageFont.truetype(font_path, 40)
    bg0 = _grad_bg(w, h).convert("RGBA")
    cols = [(66, 133, 209), (176, 132, 58), (176, 58, 58)]  # 三路配色
    m, top = 60, int(h * 0.34)
    cw = (w - 2 * m - 2 * 30) // 3
    chh = int(h * 0.42)
    for f in range(n):
        t = f / (n - 1) if n > 1 else 1.0
        frame = bg0.copy()
        d = ImageDraw.Draw(frame)
        # 顶部处境题
        head = "申生面前的三条路"
        bb = d.textbbox((0, 0), head, font=fh)
        d.rounded_rectangle(
            [(w - (bb[2] - bb[0])) // 2 - 22, top - 78, (w + (bb[2] - bb[0])) // 2 + 22, top - 26],
            radius=16,
            fill=(46, 50, 58, 255),
        )
        d.text(((w - (bb[2] - bb[0])) // 2, top - 72), head, font=fh, fill=(245, 246, 248, 255))
        for i, (label, col) in enumerate(zip(choices[:3], cols, strict=False)):
            start = 0.15 + i * 0.22  # 依次亮起
            e = ease_out_back(max(0.0, min(1.0, (t - start) / 0.4)))
            if e <= 0:
                continue
            x = m + i * (cw + 30)
            dy = int((1 - e) * 26)
            _soft_card(frame, (x, top + dy, x + cw, top + chh + dy), radius=18)
            dd = ImageDraw.Draw(frame)
            dd.rounded_rectangle([x, top + dy, x + cw, top + 10 + dy], radius=6, fill=(*col, 255))
            dd.ellipse(
                [x + cw // 2 - 26, top + 40 + dy, x + cw // 2 + 26, top + 92 + dy], fill=(*col, 40)
            )
            dd.text((x + cw // 2 - 13, top + 48 + dy), "一二三"[i], font=fn, fill=(*col, 255))
            for j, ln in enumerate(_wrap(label, 6)):
                bb2 = dd.textbbox((0, 0), ln, font=fc)
                dd.text(
                    (x + (cw - (bb2[2] - bb2[0])) // 2, top + 120 + j * 44 + dy),
                    ln,
                    font=fc,
                    fill=(*_TEXT, 255),
                )
        frame.convert("RGB").save(fd / f"f_{f:04d}.png")
    return _encode(fd, out_dir / "choice.mp4", fps)


def render_question_card(
    question: str,
    out_dir: Path,
    *,
    size: tuple[int, int] = (1168, 784),
    fps: int = 24,
    duration_s: float = 4.0,
    font_path: str = FONT,
) -> Path:
    """设身处地一问:深色留白定格 + 居中大问,给"换作是你"一个停顿镜头。"""
    w, h = size
    out_dir = Path(out_dir)
    fd = out_dir / "frames_q"
    fd.mkdir(parents=True, exist_ok=True)
    n = max(1, int(fps * duration_s))
    fq = ImageFont.truetype(font_path, 52)
    lines = _wrap(question, 12)
    for f in range(n):
        t = f / (n - 1) if n > 1 else 1.0
        e = max(0.0, min(1.0, (t - 0.05) / 0.5))  # 缓入
        val = int(28 + 6 * (1 - abs(0.5 - t) * 2))  # 极缓明暗呼吸
        frame = Image.new("RGB", (w, h), (val, val + 3, val + 8)).convert("RGBA")
        d = ImageDraw.Draw(frame)
        yy = (h - len(lines) * 72) // 2
        for ln in lines:
            bb = d.textbbox((0, 0), ln, font=fq)
            d.text(
                ((w - (bb[2] - bb[0])) // 2, yy), ln, font=fq, fill=(236, 238, 242, int(255 * e))
            )
            yy += 72
        # 底部一道渐显强调线
        if e > 0.6:
            d.rounded_rectangle(
                [w // 2 - 40, yy + 18, w // 2 + 40, yy + 24], radius=3, fill=(214, 69, 65, 255)
            )
        frame.convert("RGB").save(fd / f"f_{f:04d}.png")
    return _encode(fd, out_dir / "question.mp4", fps)
