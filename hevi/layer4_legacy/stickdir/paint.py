"""逐帧绘制的画法层 —— 背景 / 角色 / 道具 / 隐喻。

纯 PIL 绘制, 确定性(无随机), CPU-only。角色与 :mod:`pose` 的关节坐标同构:
输入归一化关节(身高≈1, 脚在地面 y=0), 输出屏幕像素。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFont

from hevi.layer4_legacy.stickdir import pose, styles

RGB = tuple[int, int, int]
Point = tuple[float, float]

FONT_REGULAR = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
FONT_BOLD = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"


@dataclass(frozen=True)
class Canvas:
    """一次绘制任务的画布尺寸与安全区。"""

    w: int
    h: int
    margin: float = 0.02

    @property
    def safe(self) -> tuple[float, float, float, float]:
        mx, my = self.w * self.margin, self.h * self.margin
        return (mx, my, self.w - mx, self.h - my)


def font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    path = FONT_BOLD if bold else FONT_REGULAR
    try:
        return ImageFont.truetype(path, size)
    except OSError:  # pragma: no cover - 字体缺失时的兜底
        return ImageFont.load_default(size)


def _accent(dna: styles.StyleDNA, i: int) -> RGB:
    return dna.accents[i % len(dna.accents)]


def _mix(a: RGB, b: RGB, t: float) -> RGB:
    return tuple(int(round(a[k] * (1 - t) + b[k] * t)) for k in range(3))


def _noise(x: int, y: int, seed: int = 7) -> float:
    """确定性伪噪声(0..1)。"""
    n = (x * 73856093) ^ (y * 19349663) ^ (seed * 83492791)
    n = (n ^ (n >> 13)) * 1274126177
    return ((n ^ (n >> 16)) & 0xFFFF) / 65535.0


# ---------------------------------------------------------------------------
# 背景
# ---------------------------------------------------------------------------


def draw_background(img: Image.Image, dna: styles.StyleDNA) -> None:
    """按风格铺背景。"""
    d = ImageDraw.Draw(img)
    w, h = img.size
    if dna.gradient is not None:
        top, bottom = dna.gradient
        for y in range(h):
            d.line([(0, y), (w, y)], fill=_mix(top, bottom, y / max(h - 1, 1)))
    else:
        d.rectangle([0, 0, w, h], fill=dna.bg)
    if dna.floor_grid:
        _draw_floor_grid(d, dna, w, h)
    if dna.paper_texture:
        _draw_paper(dna, img, w, h)


def _draw_floor_grid(d: ImageDraw.ImageDraw, dna: styles.StyleDNA, w: int, h: int) -> None:
    """浅灰透视地面网格(Style 2A)。"""
    horizon = int(h * 0.62)
    grid = _mix(dna.bg, (170, 178, 190), 0.5)
    vpx, vpy = w / 2, horizon - int(h * 0.28)
    for i in range(-8, 9):
        x_bottom = w / 2 + i * (w / 12.0)
        d.line([(vpx, vpy), (x_bottom, h)], fill=grid, width=2)
    y = horizon
    step = 6.0
    while y < h:
        d.line([(0, y), (w, y)], fill=grid, width=2)
        y += step
        step *= 1.28


def _draw_paper(dna: styles.StyleDNA, img: Image.Image, w: int, h: int) -> None:
    """纸张纹理(Style 3, 确定性)。"""
    px = img.load()
    step = 3
    for y in range(0, h, step):
        for x in range(0, w, step):
            n = _noise(x, y)
            if n < 0.12:
                r, g, b = px[x, y]
                k = 0.90 + n * 0.5
                px[x, y] = (int(r * k), int(g * k), int(b * k))


# ---------------------------------------------------------------------------
# 角色
# ---------------------------------------------------------------------------


def _polyline(d: ImageDraw.ImageDraw, pts: list[Point], color: RGB, width: int) -> None:
    if len(pts) >= 2:
        d.line(pts, fill=color, width=width, joint="curve")


def draw_character(
    d: ImageDraw.ImageDraw,
    dna: styles.StyleDNA,
    joints: dict[str, Point],
    *,
    scale: float,
    origin: Point,
    line_w: int,
    blink: bool = False,
) -> None:
    """把归一化关节映射到屏幕并绘制角色。

    ``scale`` 是"归一化身高 → 像素"的比例;``origin`` 是脚部着地点的屏幕坐标。
    """

    def m(p: Point) -> Point:
        return (origin[0] + p[0] * scale, origin[1] - p[1] * scale)

    pts = {k: m(v) for k, v in joints.items()}
    ink = dna.ink

    # 躯干/四肢骨骼
    for a, b in pose.BONES:
        _polyline(d, [pts[a], pts[b]], ink, line_w)

    head_c = pts["head"]
    r = max(6, int(scale * pose.HEAD * 0.92))

    if dna.filled_head:  # Style 3: 白色填充圆头 + 卡通表情
        d.ellipse(
            [head_c[0] - r, head_c[1] - r, head_c[0] + r, head_c[1] + r],
            fill=(246, 240, 226),
            outline=ink,
            width=max(2, line_w // 2),
        )
        _draw_cartoon_face(d, head_c, r, ink, blink=blink)
    else:  # Style 1/2: 空心圆头(圆内为背景色)
        d.ellipse(
            [head_c[0] - r, head_c[1] - r, head_c[0] + r, head_c[1] + r], outline=ink, width=line_w
        )

    if dna.beanie_tshirt:
        _draw_beanie_tshirt(d, dna, pts, scale, line_w, head_c, r)
    if dna.filled_head:
        _draw_hide_costume(d, dna, pts, scale, line_w)


def _draw_cartoon_face(d: ImageDraw.ImageDraw, c: Point, r: int, ink: RGB, *, blink: bool) -> None:
    ex = r * 0.42
    ey = c[1] - r * 0.12
    er = max(2, int(r * 0.14))
    if blink:
        d.line([(c[0] - ex - er, ey), (c[0] - ex + er, ey)], fill=ink, width=max(2, int(r * 0.10)))
        d.line([(c[0] + ex - er, ey), (c[0] + ex + er, ey)], fill=ink, width=max(2, int(r * 0.10)))
    else:
        d.ellipse([c[0] - ex - er, ey - er, c[0] - ex + er, ey + er], fill=ink)
        d.ellipse([c[0] + ex - er, ey - er, c[0] + ex + er, ey + er], fill=ink)
    # 眉毛
    d.line(
        [(c[0] - ex - er, ey - er * 2.4), (c[0] - ex + er, ey - er * 2.9)],
        fill=ink,
        width=max(2, int(r * 0.09)),
    )
    d.line(
        [(c[0] + ex - er, ey - er * 2.9), (c[0] + ex + er, ey - er * 2.4)],
        fill=ink,
        width=max(2, int(r * 0.09)),
    )
    # 嘴
    d.arc(
        [c[0] - r * 0.34, c[1] + r * 0.10, c[0] + r * 0.34, c[1] + r * 0.55],
        20,
        160,
        fill=ink,
        width=max(2, int(r * 0.10)),
    )


def _draw_beanie_tshirt(
    d: ImageDraw.ImageDraw,
    dna: styles.StyleDNA,
    pts: dict[str, Point],
    scale: float,
    line_w: int,
    head_c: Point,
    r: int,
) -> None:
    red = (214, 40, 40)
    yellow = (250, 214, 40)
    dark = (30, 30, 34)
    # 毛线帽(无绒球): 头顶的红色圆帽
    cap = [head_c[0] - r * 1.02, head_c[1] - r * 1.25, head_c[0] + r * 1.02, head_c[1] + r * 0.35]
    d.pieslice(cap, 180, 360, fill=red, outline=dark, width=max(2, line_w // 2))
    # 帽檐
    d.line(
        [
            (head_c[0] - r * 1.05, head_c[1] - r * 0.18),
            (head_c[0] + r * 1.05, head_c[1] - r * 0.18),
        ],
        fill=dark,
        width=max(3, int(line_w * 1.1)),
    )
    # 黄 T 恤(躯干多边形)
    chest, hips = pts["chest"], pts["hips"]
    sh_r, sh_l = pts["shR"], pts["shL"]
    tw = scale * 0.02
    body = [
        (sh_l[0] - tw, sh_l[1]),
        (sh_r[0] + tw, sh_r[1]),
        (hips[0] + tw * 1.4, hips[1] + scale * 0.02),
        (hips[0] - tw * 1.4, hips[1] + scale * 0.02),
    ]
    d.polygon(body, fill=yellow)
    # 短裤
    hip_r, hip_l = pts["hipR"], pts["hipL"]
    shorts = [
        (hip_l[0] - tw, hip_l[1]),
        (hip_r[0] + tw, hip_r[1]),
        (hip_r[0] + tw * 1.2, hip_r[1] + scale * 0.10),
        (hip_l[0] - tw * 1.2, hip_l[1] + scale * 0.10),
    ]
    d.polygon(shorts, fill=dark)


def _draw_hide_costume(
    d: ImageDraw.ImageDraw, dna: styles.StyleDNA, pts: dict[str, Point], scale: float, line_w: int
) -> None:
    """Style 3 兽皮服装(赭棕躯干) + 一小块兽皮披肩。"""
    hide = (150, 104, 62)
    chest, hips = pts["chest"], pts["hips"]
    sh_r, sh_l = pts["shR"], pts["shL"]
    body = [
        (sh_l[0] - scale * 0.03, sh_l[1]),
        (sh_r[0] + scale * 0.03, sh_r[1]),
        (hips[0] + scale * 0.035, hips[1] + scale * 0.03),
        (hips[0] - scale * 0.035, hips[1] + scale * 0.03),
    ]
    d.polygon(body, fill=hide, outline=(60, 40, 24))
    # 披肩边缘锯齿
    y = chest[1]
    for k in range(5):
        x = sh_l[0] + (sh_r[0] - sh_l[0]) * (k + 0.5) / 5
        d.line([(x, y), (x, y + scale * 0.05)], fill=(60, 40, 24), width=max(2, line_w // 3))


# ---------------------------------------------------------------------------
# 道具
# ---------------------------------------------------------------------------


def draw_prop(
    d: ImageDraw.ImageDraw,
    dna: styles.StyleDNA,
    prop: str,
    *,
    anchor: Point,
    scale: float,
    line_w: int,
) -> None:
    """在角色旁边画道具(简单矢量图形)。"""
    if prop == "none":
        return
    c1, c2 = _accent(dna, 0), _accent(dna, 1)
    ax, ay = anchor
    s = scale
    lw = max(2, line_w - 2)
    if prop == "line":
        d.line([(ax - s * 0.5, ay), (ax + s * 0.5, ay - s * 0.06)], fill=c1, width=max(3, lw))
    elif prop == "panel":
        _glass_panel(d, ax + s * 0.30, ay - s * 0.55, s * 0.34, s * 0.24, c1, c2)
    elif prop == "door":
        d.rectangle([ax + s * 0.34, ay - s * 0.78, ax + s * 0.70, ay], outline=c2, width=lw)
        d.ellipse([ax + s * 0.60, ay - s * 0.42, ax + s * 0.66, ay - s * 0.36], fill=c2)
    elif prop == "box":
        d.rectangle([ax + s * 0.28, ay - s * 0.26, ax + s * 0.54, ay], outline=c2, width=lw)
        d.line([(ax + s * 0.28, ay - s * 0.26), (ax + s * 0.34, ay - s * 0.34)], fill=c2, width=lw)
        d.line([(ax + s * 0.54, ay - s * 0.26), (ax + s * 0.60, ay - s * 0.34)], fill=c2, width=lw)
    elif prop == "arrow":
        d.line(
            [(ax - s * 0.55, ay - s * 0.55), (ax + s * 0.35, ay - s * 0.55)],
            fill=c1,
            width=max(3, lw),
        )
        d.polygon(
            [
                (ax + s * 0.35, ay - s * 0.62),
                (ax + s * 0.47, ay - s * 0.55),
                (ax + s * 0.35, ay - s * 0.48),
            ],
            fill=c1,
        )
    elif prop == "clock":
        cx, cy, r = ax + s * 0.42, ay - s * 0.62, s * 0.16
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=c2, width=lw)
        d.line([(cx, cy), (cx, cy - r * 0.6)], fill=c2, width=lw)
        d.line([(cx, cy), (cx + r * 0.45, cy)], fill=c2, width=lw)
    elif prop == "chart":
        base = ay
        for k, hh in enumerate((0.16, 0.28, 0.40)):
            x = ax + s * 0.30 + k * s * 0.10
            d.rectangle([x, base - s * hh, x + s * 0.06, base], fill=_accent(dna, k))
    elif prop == "spear":
        d.line(
            [(ax + s * 0.30, ay - s * 0.95), (ax + s * 0.34, ay - s * 0.10)],
            fill=(90, 62, 34),
            width=max(3, lw),
        )
        d.polygon(
            [
                (ax + s * 0.32, ay - s * 1.08),
                (ax + s * 0.27, ay - s * 0.92),
                (ax + s * 0.37, ay - s * 0.92),
            ],
            fill=(200, 200, 205),
        )
    elif prop == "fire":
        _draw_fire(d, ax + s * 0.34, ay, s * 0.16)
    elif prop == "rock":
        d.ellipse(
            [ax + s * 0.26, ay - s * 0.18, ax + s * 0.52, ay],
            fill=(120, 110, 100),
            outline=(60, 55, 50),
        )
    elif prop == "rope":
        d.arc(
            [ax + s * 0.24, ay - s * 0.30, ax + s * 0.60, ay],
            200,
            340,
            fill=(150, 110, 60),
            width=lw,
        )
        d.arc(
            [ax + s * 0.30, ay - s * 0.24, ax + s * 0.66, ay + s * 0.06],
            20,
            160,
            fill=(150, 110, 60),
            width=lw,
        )
    elif prop == "map":
        d.rectangle(
            [ax + s * 0.26, ay - s * 0.34, ax + s * 0.56, ay - s * 0.14],
            fill=(232, 220, 190),
            outline=c2,
            width=lw,
        )
        d.line(
            [(ax + s * 0.30, ay - s * 0.28), (ax + s * 0.52, ay - s * 0.20)],
            fill=c2,
            width=max(2, lw // 2),
        )
    elif prop == "lantern":
        cx, cy = ax + s * 0.42, ay - s * 0.50
        d.rectangle(
            [cx - s * 0.07, cy - s * 0.12, cx + s * 0.07, cy + s * 0.12],
            fill=_accent(dna, 2),
            outline=(60, 50, 30),
            width=max(2, lw // 2),
        )
        d.line([(cx, cy - s * 0.12), (cx, cy - s * 0.20)], fill=(60, 50, 30), width=max(2, lw // 2))
    elif prop == "book":
        d.rectangle(
            [ax + s * 0.26, ay - s * 0.26, ax + s * 0.56, ay - s * 0.06],
            fill=(240, 235, 220),
            outline=c2,
            width=lw,
        )
        d.line(
            [(ax + s * 0.41, ay - s * 0.26), (ax + s * 0.41, ay - s * 0.06)],
            fill=c2,
            width=max(2, lw // 2),
        )
    elif prop == "gear":
        cx, cy, r = ax + s * 0.44, ay - s * 0.60, s * 0.14
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=c2, width=lw)
        d.ellipse(
            [cx - r * 0.35, cy - r * 0.35, cx + r * 0.35, cy + r * 0.35],
            outline=c2,
            width=max(2, lw // 2),
        )
        for k in range(6):
            a = k * math.pi / 3
            d.line(
                [
                    (cx + math.cos(a) * r, cy + math.sin(a) * r),
                    (cx + math.cos(a) * r * 1.4, cy + math.sin(a) * r * 1.4),
                ],
                fill=c2,
                width=max(2, lw // 2),
            )
    elif prop == "glass":
        d.line(
            [(ax - s * 0.7, ay - s * 1.18), (ax + s * 0.7, ay - s * 1.18)],
            fill=c1,
            width=max(3, lw),
        )


def _glass_panel(
    d: ImageDraw.ImageDraw, cx: float, cy: float, w: float, h: float, c1: RGB, c2: RGB
) -> None:
    d.rounded_rectangle(
        [cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2],
        radius=max(3, int(h * 0.18)),
        outline=c1,
        width=3,
        fill=_mix(c1, (255, 255, 255), 0.72),
    )
    d.line([(cx - w * 0.30, cy), (cx + w * 0.30, cy)], fill=c2, width=3)
    d.line([(cx - w * 0.18, cy - h * 0.20), (cx + w * 0.20, cy - h * 0.20)], fill=c2, width=2)


def _draw_fire(d: ImageDraw.ImageDraw, cx: float, ground: float, s: float) -> None:
    d.polygon(
        [(cx, ground - s * 2.0), (cx - s * 0.7, ground), (cx + s * 0.7, ground)],
        fill=(230, 120, 30),
    )
    d.polygon(
        [(cx, ground - s * 1.3), (cx - s * 0.4, ground), (cx + s * 0.4, ground)],
        fill=(250, 200, 60),
    )
    for k in (-1, 0, 1):
        d.line(
            [(cx + k * s * 0.8, ground), (cx + k * s * 1.2, ground + s * 0.25)],
            fill=(90, 62, 34),
            width=3,
        )


# ---------------------------------------------------------------------------
# 视觉隐喻(场景级)
# ---------------------------------------------------------------------------


def _scene_fill(dna: styles.StyleDNA, tint: float = 0.30) -> RGB:
    """隐喻填充色:向背景靠拢的低对比色(角色/前景始终可辨)。"""
    return _mix(dna.bg, (128, 128, 138), tint)


def _scene_line(dna: styles.StyleDNA) -> RGB:
    """隐喻描边色:比背景略深/略浅, 不淹没角色。"""
    return _mix(dna.bg, (40, 44, 60) if sum(dna.bg) > 380 else (210, 214, 230), 0.55)


def draw_metaphor(
    d: ImageDraw.ImageDraw,
    dna: styles.StyleDNA,
    metaphor: str,
    canvas: Canvas,
    *,
    ground_y: float,
) -> None:
    """在场景里画一个视觉隐喻元素(低对比, 不与角色抢视线)。"""
    if metaphor == "none":
        return
    w, h = canvas.w, canvas.h
    c1, c2, c3 = _accent(dna, 0), _accent(dna, 1), _accent(dna, 2)
    lw = max(3, int(h * 0.004))
    soft = _scene_fill(dna, 0.34)
    line = _scene_line(dna)
    faint = _scene_fill(dna, 0.20)
    if metaphor == "ladder":
        x0, y1 = w * 0.12, ground_y
        y0 = h * 0.20
        d.line([(x0, y0), (x0, y1)], fill=line, width=lw)
        d.line([(x0 + w * 0.09, y0), (x0 + w * 0.09, y1)], fill=line, width=lw)
        for k in range(6):
            y = y0 + (y1 - y0) * k / 5
            d.line([(x0, y), (x0 + w * 0.09, y)], fill=line, width=lw)
    elif metaphor == "abyss":
        d.polygon([(w * 0.30, ground_y), (w * 0.70, ground_y), (w * 0.58, h * 0.98), (w * 0.42, h * 0.98)],
                  fill=_mix(dna.bg, (8, 8, 12), 0.80))
    elif metaphor == "mountain":
        d.polygon([(w * 0.08, ground_y), (w * 0.30, h * 0.30), (w * 0.54, ground_y)], fill=soft)
        d.polygon([(w * 0.26, ground_y), (w * 0.30, h * 0.30), (w * 0.34, h * 0.42)], fill=_mix(soft, (255, 255, 255), 0.55))
    elif metaphor == "treadmill":
        d.rounded_rectangle([w * 0.18, ground_y - h * 0.02, w * 0.70, ground_y + h * 0.06],
                            radius=int(h * 0.02), outline=line, width=lw)
        for k in range(6):
            x = w * 0.20 + (w * 0.48) * k / 5
            d.line([(x, ground_y - h * 0.02), (x, ground_y + h * 0.06)], fill=line, width=2)
    elif metaphor == "maze":
        for k in range(4):
            d.rectangle([w * (0.12 + k * 0.04), h * (0.30 + k * 0.05), w * (0.62 - k * 0.04), h * (0.86 - k * 0.05)],
                        outline=line, width=lw)
    elif metaphor == "iceberg":
        d.polygon([(w * 0.22, ground_y), (w * 0.44, h * 0.40), (w * 0.66, ground_y)], fill=_mix(dna.bg, (240, 246, 252), 0.55))
        d.polygon([(w * 0.30, ground_y), (w * 0.44, h * 0.88), (w * 0.58, ground_y)], fill=_mix(dna.bg, (110, 150, 190), 0.60))
    elif metaphor == "domino":
        for k in range(4):
            x = w * (0.16 + k * 0.13)
            d.rectangle([x, ground_y - h * 0.14 + k * h * 0.02, x + w * 0.05, ground_y], fill=soft, outline=line, width=2)
    elif metaphor == "funnel":
        d.polygon([(w * 0.14, h * 0.20), (w * 0.86, h * 0.20), (w * 0.56, h * 0.64), (w * 0.44, h * 0.64)], outline=line, width=lw)
        d.line([(w * 0.50, h * 0.64), (w * 0.50, ground_y)], fill=line, width=lw)
    elif metaphor == "bridge":
        d.arc([w * 0.12, h * 0.40, w * 0.88, ground_y + h * 0.32], 180, 360, fill=line, width=max(4, lw))
        d.line([(w * 0.12, ground_y - h * 0.06), (w * 0.88, ground_y - h * 0.06)], fill=line, width=max(4, lw))
    elif metaphor == "mirror":
        d.rectangle([w * 0.62, h * 0.24, w * 0.82, h * 0.58], outline=line, width=lw)
        d.line([(w * 0.65, h * 0.53), (w * 0.79, h * 0.29)], fill=faint, width=2)
    elif metaphor == "magnet":
        d.arc([w * 0.60, h * 0.28, w * 0.86, h * 0.52], 180, 360, fill=line, width=max(6, lw))
        d.line([(w * 0.60, h * 0.40), (w * 0.60, h * 0.54)], fill=c3, width=max(6, lw))
        d.line([(w * 0.86, h * 0.40), (w * 0.86, h * 0.54)], fill=c3, width=max(6, lw))
    elif metaphor == "cage":
        d.rectangle([w * 0.58, h * 0.28, w * 0.84, h * 0.72], outline=line, width=lw)
        for k in range(4):
            x = w * (0.62 + k * 0.05)
            d.line([(x, h * 0.28), (x, h * 0.72)], fill=line, width=2)
    elif metaphor == "horizon":
        d.line([(0, h * 0.58), (w, h * 0.58)], fill=line, width=max(3, lw))
        d.ellipse([w * 0.60, h * 0.42, w * 0.78, h * 0.58], fill=_mix(dna.bg, c3, 0.45))
    elif metaphor == "hourglass":
        cx, cy = w * 0.72, h * 0.42
        s = h * 0.10
        d.polygon([(cx - s, cy - s), (cx + s, cy - s), (cx, cy)], outline=line, width=lw)
        d.polygon([(cx - s, cy + s), (cx + s, cy + s), (cx, cy)], outline=line, width=lw)
        d.line([(cx - s, cy - s), (cx + s, cy - s)], fill=line, width=lw)
        d.line([(cx - s, cy + s), (cx + s, cy + s)], fill=line, width=lw)

__all__ = [
    "Canvas",
    "FONT_BOLD",
    "FONT_REGULAR",
    "draw_background",
    "draw_character",
    "draw_metaphor",
    "draw_prop",
    "font",
]
