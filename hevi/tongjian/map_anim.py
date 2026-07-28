"""G0-D 确定性分层动画引擎 —— HEVI-EXPLAINER-PIPELINE-SPEC-001 §5 / §9 deterministic_layers。

质量杆不是"SVG transition 完事":2.5D 层深 + 随层接触阴影 + 落定回弹缓动 + 云朵慢漂,
且**纸雕材质**:撕边(deckle 锯齿 + 撕纸白芯) + 有机纸纤维纹理(fbm 噪声)。
运动/材质工艺 = 一次性模板资产,摊销全系列。零 provider、零色塌(色从注册表确定性绘制)。

确定性:所有"随机"都用固定 seed(np.random.default_rng / random.Random),复现一致、逐帧不抖。
层图按 (state_id, force_id, size) 缓存,只算一次,逐帧只做平移/渐显/阴影。

模板:animate_establish(S1 全图铺陈)。S3 撕裂 animate_tear 后续。
输出:帧序列 → ffmpeg mp4。
"""

from __future__ import annotations

import math
import random
import subprocess
from itertools import pairwise
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter

from hevi.tongjian.force_colors import get_force_color
from hevi.tongjian.map_state import MapState

PAPER = (232, 224, 204)
_FIBRE_CACHE: dict[tuple[int, int, int], np.ndarray] = {}
_LAYER_CACHE: dict[tuple, Image.Image] = {}


def _fibre(w: int, h: int, seed: int = 7) -> np.ndarray:
    """有机纸纤维噪声场(多倍频 fbm,确定性)。返回零均值 float 场 ~[-1,1] 量级。"""
    key = (w, h, seed)
    if key in _FIBRE_CACHE:
        return _FIBRE_CACHE[key]
    rng = np.random.default_rng(seed)
    acc = np.zeros((h, w), dtype=np.float64)
    amp = 1.0
    for freq in (4, 8, 16, 32, 96):
        low = rng.standard_normal((freq, freq))
        low = (low - low.min()) / (low.max() - low.min() + 1e-9) * 255
        up = (
            np.asarray(
                Image.fromarray(low.astype(np.uint8)).resize((w, h), Image.BICUBIC),
                dtype=np.float64,
            )
            / 255.0
            - 0.5
        )
        acc += up * amp
        amp *= 0.55
    # 叠一层细的横向纤维条纹(纸的抄网纹)
    yy = np.arange(h)[:, None]
    acc += 0.12 * np.sin(yy * 0.9 + acc * 3.0)
    acc -= acc.mean()
    acc /= acc.std() + 1e-9
    _FIBRE_CACHE[key] = acc
    return acc


def _paper_bg(w: int, h: int) -> Image.Image:
    """做旧皮纸底(有机纤维纹 + 轻微暗角)。"""
    fib = _fibre(w, h, seed=11)
    base = np.asarray(PAPER, dtype=np.float64) + (fib * 5.0)[..., None]
    # 轻微暗角(桌面聚光感)
    yy, xx = np.mgrid[0:h, 0:w]
    r = ((xx / w - 0.5) ** 2 + (yy / h - 0.5) ** 2) ** 0.5
    base -= (np.clip(r - 0.35, 0, None) * 55)[..., None]
    return Image.fromarray(np.clip(base, 0, 255).astype(np.uint8), "RGB").convert("RGBA")


def _deckle(
    pts: list[tuple[float, float]], amp: float, step: float, seed: int
) -> list[tuple[float, float]]:
    """把多边形边细分并沿法向加噪 → 撕纸锯齿边(固定 seed,逐帧一致不抖)。"""
    rng = random.Random(seed)
    n = len(pts)
    out: list[tuple[float, float]] = []
    for i in range(n):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % n]
        dx, dy = x1 - x0, y1 - y0
        length = math.hypot(dx, dy) or 1.0
        px, py = -dy / length, dx / length  # 法向单位
        segs = max(1, int(length / step))
        for s in range(segs):
            t = s / segs
            # 两级噪声:粗撕痕 + 细毛边
            off = (rng.random() - 0.5) * 2 * amp + (rng.random() - 0.5) * amp * 0.4
            out.append((x0 + dx * t + px * off, y0 + dy * t + py * off))
    return out


def _chaikin(pts, iters=2):
    """Chaikin 切角平滑:棱角凸多边形 → 有机圆润疆界(去"块状粗糙")。"""
    for _ in range(iters):
        new = []
        n = len(pts)
        for i in range(n):
            x0, y0 = pts[i]
            x1, y1 = pts[(i + 1) % n]
            new.append((0.75 * x0 + 0.25 * x1, 0.75 * y0 + 0.25 * y1))
            new.append((0.25 * x0 + 0.75 * x1, 0.25 * y0 + 0.75 * y1))
        pts = new
    return pts


def _force_layer(ms: MapState, fp, w: int, h: int) -> Image.Image:
    """单势力→RGBA 层。有机疆界(Chaikin)+撕边+撕纸白芯+水墨积墨+中心提亮+细软描边+纤维。缓存。"""
    key = (ms.state_id, fp.force_id, w, h)
    if key in _LAYER_CACHE:
        return _LAYER_CACHE[key]
    proj = ms.projection
    sx, sy = w / proj.svg_w, h / proj.svg_h
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    fc = get_force_color(fp.force_id)
    r, g, b = fc.rgb
    a = int(255 * (0.92 if fc.tier == 0 else 0.72))
    seed = abs(hash(fp.force_id)) % 100000
    for ri, ring in enumerate(fp.rings):
        base_pts = [(proj.ll(lo, la)[0] * sx, proj.ll(lo, la)[1] * sy) for lo, la in ring]
        sm = _chaikin(base_pts, 2)  # 有机化
        torn = _deckle(sm, amp=2.6, step=6.0, seed=seed + ri)
        closed = [*torn, torn[0]]
        rs = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        rd = ImageDraw.Draw(rs)
        # 撕纸白芯(略大浅边)
        pale = tuple(min(255, int(c * 0.5 + 235 * 0.5)) for c in (r, g, b))
        rd.polygon(
            _deckle(_chaikin(base_pts, 2), amp=4.5, step=6, seed=seed + ri + 500), fill=(*pale, a)
        )
        rd.polygon(torn, fill=(r, g, b, a))
        shape_alpha = rs.split()[3]
        # 水墨积墨:边缘暗色内渗(去平涂,给体量)
        ink = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        ImageDraw.Draw(ink).line(
            closed, fill=(int(r * 0.5), int(g * 0.5), int(b * 0.5), 160), width=18
        )
        ink = ink.filter(ImageFilter.GaussianBlur(8))
        ink.putalpha(ImageChops.multiply(ink.split()[3], shape_alpha))
        rs = Image.alpha_composite(rs, ink)
        # 中心提亮(体量感,内缩浅色低透明)
        cx = sum(p[0] for p in torn) / len(torn)
        cy = sum(p[1] for p in torn) / len(torn)
        glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        inner = [(cx + (px - cx) * 0.62, cy + (py - cy) * 0.62) for px, py in torn]
        hi = tuple(min(255, int(c * 1.12)) for c in (r, g, b))
        ImageDraw.Draw(glow).polygon(inner, fill=(*hi, 60))
        glow = glow.filter(ImageFilter.GaussianBlur(22))
        glow.putalpha(ImageChops.multiply(glow.split()[3], shape_alpha))
        rs = Image.alpha_composite(rs, glow)
        # 细软墨线描边(替代粗黑)
        ImageDraw.Draw(rs).line(closed, fill=(60, 45, 30, 140), width=1)
        layer = Image.alpha_composite(layer, rs)
    # 纤维颗粒(只在 alpha>0 处可见)
    arr = np.asarray(layer, dtype=np.float64)
    grain = _fibre(w, h, seed=seed % 97 + 3) * 6.0
    arr[..., :3] = np.clip(arr[..., :3] + grain[..., None], 0, 255)
    layer = Image.fromarray(arr.astype(np.uint8), "RGBA")
    _LAYER_CACHE[key] = layer
    return layer


def _shadow_from(layer: Image.Image, dx: float, dy: float, blur: float, alpha: int) -> Image.Image:
    """从层剪影生成接触阴影。层深越落定,阴影越贴、越实。"""
    sil = layer.split()[3]
    sh = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    sh.paste(Image.new("RGBA", layer.size, (18, 12, 6, alpha)), (int(dx), int(dy)), sil)
    return sh.filter(ImageFilter.GaussianBlur(blur))


def _place(layer: Image.Image, dx: float, dy: float, fade: float) -> Image.Image:
    """平移 (dx,dy) + 整体乘 fade 透明度。"""
    canvas = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    canvas.paste(layer, (int(dx), int(dy)), layer)
    if fade < 1.0:
        r, g, b, al = canvas.split()
        al = al.point(lambda v: int(v * fade))
        canvas = Image.merge("RGBA", (r, g, b, al))
    return canvas


def _fade_shift(layer: Image.Image, dy: float, fade: float) -> Image.Image:
    """竖直平移 dy 并整体乘 fade 透明度(滑入 + 渐显)。"""
    return _place(layer, 0.0, dy, fade)


def smoothstep(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def _clouds(w: int, h: int, phase: float) -> Image.Image:
    """慢漂云层(低透明,横向匀速漂,循环)。"""
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    span = w + 500
    for cx, cy, rad in [(0.15, 0.22, 150), (0.55, 0.12, 200), (0.82, 0.34, 160), (0.4, 0.42, 120)]:
        x = (cx * w + phase * span) % span - 250
        d.ellipse(
            [x - rad, cy * h - rad * 0.45, x + rad, cy * h + rad * 0.45], fill=(255, 255, 250, 16)
        )
    return layer.filter(ImageFilter.GaussianBlur(45))


def ease_out_back(t: float, overshoot: float = 1.9) -> float:
    """回弹缓动:落定前小幅过冲再收(纸片落桌的弹感)。"""
    t = max(0.0, min(1.0, t))
    c1 = overshoot
    c3 = c1 + 1
    return 1 + c3 * (t - 1) ** 3 + c1 * (t - 1) ** 2


def animate_establish(
    ms: MapState,
    out_dir: Path,
    *,
    size: tuple[int, int] = (1168, 784),
    fps: int = 24,
    duration_s: float = 4.0,
    slide_px: float = 130.0,
) -> Path:
    """S1 全图铺陈:势力纸片自下依次滑入 + 接触阴影随落定加深 + 回弹 + 云漂。
    势力绘制顺序 = ms.forces 顺序(先画在后层,最后一个最先在前层最后滑入)。返回 mp4 路径。"""
    w, h = size
    out_dir = Path(out_dir)
    frames_dir = out_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    n = int(fps * duration_s)
    forces = ms.forces
    nf = len(forces)
    layers = [_force_layer(ms, fp, w, h) for fp in forces]  # 预渲染,只算一次
    starts = [0.6 * (i / max(1, nf - 1)) for i in range(nf)]
    win = 0.42

    for f in range(n):
        t = f / (n - 1) if n > 1 else 1.0
        frame = _paper_bg(w, h)
        for i, layer in enumerate(layers):
            ti = (t - starts[i]) / win
            fade = max(0.0, min(1.0, ti * 1.6))
            if fade <= 0:
                continue
            e = ease_out_back(ti)
            dy = (1.0 - e) * slide_px
            settle = max(0.0, min(1.0, ti))
            frame = Image.alpha_composite(
                frame,
                _shadow_from(
                    layer,
                    10 - 5 * settle,
                    14 - 6 * settle + dy,
                    blur=6 + 4 * (1 - settle),
                    alpha=int(70 * settle),
                ),
            )
            frame = Image.alpha_composite(frame, _fade_shift(layer, dy, fade))
        # 河流/裂线/城邑随势力落定渐显(S1-POLISH-1#3)
        geo_fade = smoothstep((t - 0.58) / 0.36)
        if geo_fade > 0:
            geo = _geo_layer(ms, w, h)
            r, g, b, al = geo.split()
            geo = Image.merge("RGBA", (r, g, b, al.point(lambda v, gf=geo_fade: int(v * gf))))
            frame = Image.alpha_composite(frame, geo)
        frame = Image.alpha_composite(frame, _clouds(w, h, phase=t * 0.12))
        frame.convert("RGB").save(frames_dir / f"f_{f:04d}.png")

    mp4 = out_dir / f"{ms.state_id}_establish.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-framerate",
            str(fps),
            "-i",
            str(frames_dir / "f_%04d.png"),
            "-pix_fmt",
            "yuv420p",
            "-crf",
            "18",
            str(mp4),
        ],
        check=True,
    )
    return mp4


def _geo_layer(ms: MapState, w: int, h: int) -> Image.Image:
    """河流/裂线/城邑点层(纸雕风,叠在势力块上;S1-POLISH-1#3 底图河流裂线补)。
    R7:不画地名(后期字幕合成),只出水系/裂纹/城点几何。"""
    proj = ms.projection
    sx, sy = w / proj.svg_w, h / proj.svg_h
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)

    def pt(lo, la):
        x, y = proj.ll(lo, la)
        return (x * sx, y * sy)

    for rv in ms.rivers:  # 河流:深蓝底 + 亮蓝芯(水的体量)
        pts = [pt(lo, la) for lo, la in rv.points]
        if len(pts) >= 2:
            d.line(pts, fill=(58, 96, 148, 150), width=int(rv.width * sx) + 5, joint="curve")
            d.line(pts, fill=(92, 142, 202, 205), width=int(rv.width * sx) + 1, joint="curve")
    for fs in ms.fissures:  # 裂线:preset=暗红(裂而未分)、else 暗线
        pts = [pt(lo, la) for lo, la in fs.points]
        if len(pts) >= 2:
            d.line(pts, fill=(150, 30, 20, 205) if fs.preset else (40, 25, 12, 220), width=3)
    for c in ms.cities:  # 城邑点(纸雕小圈 + 红芯;名 R7 后期)
        x, y = pt(c.lon, c.lat)
        d.ellipse(
            [x - 6, y - 6, x + 6, y + 6], fill=(238, 213, 163, 235), outline=(43, 32, 20, 230)
        )
        d.ellipse([x - 3, y - 3, x + 3, y + 3], fill=(120, 40, 30, 255))
    return layer


def _static_map(ms: MapState, w: int, h: int) -> Image.Image:
    """把 ms 所有势力落定合成一张静态底(供 S2 在其上显裂纹) + 河流/裂线/城邑层。"""
    frame = _paper_bg(w, h)
    for fp in ms.forces:
        layer = _force_layer(ms, fp, w, h)
        frame = Image.alpha_composite(frame, _shadow_from(layer, 5, 8, blur=6, alpha=70))
        frame = Image.alpha_composite(frame, layer)
    return Image.alpha_composite(frame, _geo_layer(ms, w, h))


def animate_fissure_reveal(
    base_ms: MapState,
    fissures: list,
    out_dir: Path,
    *,
    size: tuple[int, int] = (1168, 784),
    fps: int = 24,
    duration_s: float = 4.0,
) -> Path:
    """S2 裂线隐现:统一图落定不动,预置裂线沿其走向**渐渐蔓延**(crack propagate) + 微红预示。
    治"这只是 transition"——裂纹是一格格撕开长出来的,不是整条淡入。"""
    w, h = size
    out_dir = Path(out_dir)
    frames_dir = out_dir / "frames_fissure"
    frames_dir.mkdir(parents=True, exist_ok=True)
    n = int(fps * duration_s)
    proj = base_ms.projection
    sx, sy = w / proj.svg_w, h / proj.svg_h
    base = _static_map(base_ms, w, h)
    # 每条裂线密化 + deckle → 蔓延点序列
    cracks = []
    for i, fis in enumerate(fissures):
        pts = [(proj.ll(lo, la)[0] * sx, proj.ll(lo, la)[1] * sy) for lo, la in fis.points]
        cracks.append(_deckle(pts + pts[::-1][1:], amp=2.2, step=4.0, seed=900 + i)[:60])

    for f in range(n):
        t = f / (n - 1) if n > 1 else 1.0
        frame = base.copy()
        d = ImageDraw.Draw(frame)
        for pts in cracks:
            rp = smoothstep((t - 0.15) / 0.7)
            k = max(2, int(len(pts) * rp))
            seg = pts[:k]
            if len(seg) >= 2:
                d.line(seg, fill=(150, 20, 10, int(90 * rp)), width=6)  # 微红预示(底)
                d.line(seg, fill=(26, 15, 8, 230), width=2)  # 暗裂纹(面)
        frame = Image.alpha_composite(frame, _clouds(w, h, phase=t * 0.1))
        frame.convert("RGB").save(frames_dir / f"f_{f:04d}.png")

    mp4 = out_dir / f"{base_ms.state_id}_fissure.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-framerate",
            str(fps),
            "-i",
            str(frames_dir / "f_%04d.png"),
            "-pix_fmt",
            "yuv420p",
            "-crf",
            "18",
            str(mp4),
        ],
        check=True,
    )
    return mp4


def animate_tear(
    unified_ms: MapState,
    split_ms: MapState,
    out_dir: Path,
    *,
    children: tuple[str, ...] = ("han", "zhao", "wei"),
    size: tuple[int, int] = (1168, 784),
    fps: int = 24,
    duration_s: float = 5.0,
    sep_px: float = 26.0,
) -> Path:
    """S3 撕裂:统一块(unified 的 parent) → 沿裂线撕成 children 三块,各自径向抬起分离。
    周边国静态settled;中央 parent 淡出、children 淡入并从质心向外分离 + 接触阴影随抬起加深。"""
    w, h = size
    out_dir = Path(out_dir)
    frames_dir = out_dir / "frames_tear"
    frames_dir.mkdir(parents=True, exist_ok=True)
    n = int(fps * duration_s)
    proj = split_ms.projection
    sx, sy = w / proj.svg_w, h / proj.svg_h

    surround = [fp for fp in split_ms.forces if fp.force_id not in children]
    surround_layers = [_force_layer(split_ms, fp, w, h) for fp in surround]
    parent_fp = next(
        fp for fp in unified_ms.forces if fp.force_id not in [f.force_id for f in surround]
    )
    parent_layer = _force_layer(unified_ms, parent_fp, w, h)
    px0, py0 = proj.centroid_px(parent_fp.rings[0])
    px0, py0 = px0 * sx, py0 * sy  # parent 质心(像素)

    pieces = []
    for fp in split_ms.forces:
        if fp.force_id in children:
            cx, cy = proj.centroid_px(fp.rings[0])
            cx, cy = cx * sx, cy * sy
            vx, vy = cx - px0, cy - py0
            d = math.hypot(vx, vy) or 1.0
            pieces.append((_force_layer(split_ms, fp, w, h), vx / d, vy / d))

    for f in range(n):
        t = f / (n - 1) if n > 1 else 1.0
        frame = _paper_bg(w, h)
        # 周边国静态(已落定)
        for layer in surround_layers:
            frame = Image.alpha_composite(frame, _shadow_from(layer, 5, 8, blur=6, alpha=70))
            frame = Image.alpha_composite(frame, layer)
        p = smoothstep((t - 0.30) / 0.50)  # 撕裂进度 0→1
        # parent(统一晋)静置片刻后淡出
        jin_fade = 1.0 - smoothstep((t - 0.30) / 0.34)
        if jin_fade > 0.01:
            frame = Image.alpha_composite(
                frame, _shadow_from(parent_layer, 5, 8, blur=6, alpha=int(70 * jin_fade))
            )
            frame = Image.alpha_composite(frame, _place(parent_layer, 0, 0, jin_fade))
        # children 淡入 + 沿径向分离 + 抬起(阴影随 p 加深、偏移变大)
        if p > 0.01:
            for layer, ux, uy in pieces:
                dx, dy = ux * sep_px * p, uy * sep_px * p
                lift = p
                frame = Image.alpha_composite(
                    frame,
                    _shadow_from(
                        layer,
                        dx + 6 + 6 * lift,
                        dy + 9 + 8 * lift,
                        blur=6 + 6 * lift,
                        alpha=int(90 * p),
                    ),
                )
                frame = Image.alpha_composite(frame, _place(layer, dx, dy, min(1.0, p * 1.4)))
        frame = Image.alpha_composite(frame, _clouds(w, h, phase=t * 0.12))
        frame.convert("RGB").save(frames_dir / f"f_{f:04d}.png")

    mp4 = out_dir / f"{split_ms.state_id}_tear.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-framerate",
            str(fps),
            "-i",
            str(frames_dir / "f_%04d.png"),
            "-pix_fmt",
            "yuv420p",
            "-crf",
            "18",
            str(mp4),
        ],
        check=True,
    )
    return mp4


def _torn_rect(d: ImageDraw.ImageDraw, box, fill, seed, amp=3.0):
    """撕纸小块(矩形→deckle),画到给定 draw 上。box=(x0,y0,x1,y1)。"""
    x0, y0, x1, y1 = box
    pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    r, g, b = fill
    pale = tuple(min(255, int(c * 0.5 + 235 * 0.5)) for c in fill)
    d.polygon(_deckle(pts, amp=amp + 2, step=6, seed=seed + 7), fill=(*pale, 235))
    d.polygon(
        _deckle(pts, amp=amp, step=6, seed=seed), fill=(r, g, b, 235), outline=(43, 32, 20, 210)
    )


def animate_timeline(
    event_xfracs: list[float],
    out_dir: Path,
    *,
    accent=(122, 60, 40),
    size: tuple[int, int] = (1168, 784),
    fps: int = 24,
    duration_s: float = 5.0,
) -> Path:
    """S10 时间轴:纸带横轴 + 事件桩(游标扫过时回弹弹起) + 游标匀速推进。
    R7:不画年号/事件文字(后期字幕合成),只出纸雕结构+游标终位。event_xfracs=事件轴位置[0,1]。"""
    w, h = size
    out_dir = Path(out_dir)
    frames_dir = out_dir / "frames_timeline"
    frames_dir.mkdir(parents=True, exist_ok=True)
    n = int(fps * duration_s)
    ax_y = int(h * 0.52)
    x0, x1 = int(w * 0.12), int(w * 0.88)
    events_px = [int(x0 + xf * (x1 - x0)) for xf in event_xfracs]

    for f in range(n):
        t = f / (n - 1) if n > 1 else 1.0
        frame = _paper_bg(w, h)
        # 纸带横轴(撕边) + 接触阴影
        axis = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        ad = ImageDraw.Draw(axis)
        _torn_rect(ad, (x0, ax_y - 9, x1, ax_y + 9), (206, 190, 150), seed=42, amp=2.4)
        frame = Image.alpha_composite(frame, _shadow_from(axis, 4, 7, blur=6, alpha=70))
        frame = Image.alpha_composite(frame, axis)
        # 游标推进(前 15%–90% 时长匀速略缓)
        cur = smoothstep((t - 0.12) / 0.78)
        cx = int(x0 + cur * (x1 - x0))
        # 事件桩:游标到达其 x 时回弹弹起
        posts = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        pd = ImageDraw.Draw(posts)
        for i, ex in enumerate(events_px):
            reached = cur >= (ex - x0) / (x1 - x0) - 0.01
            e = ease_out_back((cur - ((ex - x0) / (x1 - x0)) + 0.12) / 0.12) if reached else 0.0
            e = max(0.0, min(1.0, e))
            if e <= 0:
                continue
            ph = int(52 * e)  # 桩高
            _torn_rect(pd, (ex - 15, ax_y - 12 - ph, ex + 15, ax_y - 12), accent, seed=100 + i * 13)
        frame = Image.alpha_composite(frame, _shadow_from(posts, 5, 8, blur=5, alpha=80))
        frame = Image.alpha_composite(frame, posts)
        # 游标(纸三角,悬在轴上)
        curm = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        cd = ImageDraw.Draw(curm)
        tri = [(cx, ax_y + 14), (cx - 12, ax_y + 34), (cx + 12, ax_y + 34)]
        cd.polygon(
            _deckle(tri, amp=2, step=6, seed=555),
            fill=(150, 30, 20, 240),
            outline=(43, 32, 20, 220),
        )
        frame = Image.alpha_composite(frame, _shadow_from(curm, 3, 5, blur=4, alpha=70))
        frame = Image.alpha_composite(frame, curm)
        frame = Image.alpha_composite(frame, _clouds(w, h, phase=t * 0.1))
        frame.convert("RGB").save(frames_dir / f"f_{f:04d}.png")

    mp4 = out_dir / "s10_timeline.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-framerate",
            str(fps),
            "-i",
            str(frames_dir / "f_%04d.png"),
            "-pix_fmt",
            "yuv420p",
            "-crf",
            "18",
            str(mp4),
        ],
        check=True,
    )
    return mp4


def _densify(pts_px, step=8.0):
    """把折线密化成步长≈step 的点序列(供纸带分段贴放/水流)。"""
    out = [pts_px[0]]
    for (x0, y0), (x1, y1) in pairwise(pts_px):
        seg = math.hypot(x1 - x0, y1 - y0)
        k = max(1, int(seg / step))
        out.extend((x0 + (x1 - x0) * s / k, y0 + (y1 - y0) * s / k) for s in range(1, k + 1))
    return out


def animate_route(
    path_fracs: list[tuple[float, float]],
    out_dir: Path,
    *,
    base: Image.Image | None = None,
    color=(74, 120, 190),
    width: float = 16.0,
    size: tuple[int, int] = (1168, 784),
    fps: int = 24,
    duration_s: float = 3.5,
    tag: str = "route",
) -> Path:
    """S5 路线:纸带沿折线**分段贴放**(恒平贴,不 morph),推进端小幅落定 + 接触阴影。
    引水/进军皆此。base 给底图则叠其上。B5 断言:标记/终点数。"""
    w, h = size
    out_dir = Path(out_dir)
    frames_dir = out_dir / f"frames_{tag}"
    frames_dir.mkdir(parents=True, exist_ok=True)
    n = int(fps * duration_s)
    pts = _densify([(int(xf * w), int(yf * h)) for xf, yf in path_fracs], step=7.0)
    m = len(pts)

    def band_polygon(seg_pts, wid):
        left, right = [], []
        for i, (x, y) in enumerate(seg_pts):
            x0, y0 = seg_pts[max(0, i - 1)]
            x1, y1 = seg_pts[min(len(seg_pts) - 1, i + 1)]
            dx, dy = x1 - x0, y1 - y0
            ln = math.hypot(dx, dy) or 1.0
            nx, ny = -dy / ln, dx / ln
            left.append((x + nx * wid / 2, y + ny * wid / 2))
            right.append((x - nx * wid / 2, y - ny * wid / 2))
        return left + right[::-1]

    for f in range(n):
        t = f / (n - 1) if n > 1 else 1.0
        frame = base.copy() if base is not None else _paper_bg(w, h)
        rp = smoothstep(min(1.0, t / 0.9))
        k = max(2, int(m * rp))
        seg = pts[:k]
        if len(seg) >= 2:
            ribbon = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            rd = ImageDraw.Draw(ribbon)
            poly = band_polygon(seg, width)
            r, g, b = color
            pale = tuple(min(255, int(c * 0.5 + 235 * 0.5)) for c in color)
            rd.polygon(_deckle(poly, amp=2.2, step=7, seed=333), fill=(*pale, 210))
            rd.polygon(
                _deckle(poly, amp=1.4, step=7, seed=201),
                fill=(r, g, b, 205),
                outline=(43, 32, 20, 150),
            )
            frame = Image.alpha_composite(frame, _shadow_from(ribbon, 3, 6, blur=5, alpha=60))
            frame = Image.alpha_composite(frame, ribbon)
            # 推进端箭头(纸三角)
            tx, ty = seg[-1]
            px0, py0 = seg[max(0, len(seg) - 4)]
            ang = math.atan2(ty - py0, tx - px0)
            tip = [
                (tx + 14 * math.cos(ang), ty + 14 * math.sin(ang)),
                (tx + math.cos(ang + 2.5) * 12, ty + math.sin(ang + 2.5) * 12),
                (tx + math.cos(ang - 2.5) * 12, ty + math.sin(ang - 2.5) * 12),
            ]
            ad = ImageDraw.Draw(frame)
            ad.polygon(
                _deckle(tip, amp=1.5, step=5, seed=99),
                fill=(*color, 235),
                outline=(43, 32, 20, 180),
            )
        frame.convert("RGB").save(frames_dir / f"f_{f:04d}.png")

    mp4 = out_dir / f"s5_{tag}.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-framerate",
            str(fps),
            "-i",
            str(frames_dir / "f_%04d.png"),
            "-pix_fmt",
            "yuv420p",
            "-crf",
            "18",
            str(mp4),
        ],
        check=True,
    )
    return mp4


_FIGURE_SW, _FIGURE_SH = 280, 440


def figure_sprite(accent, trim, *, elder=False, crown=False, seed=1) -> Image.Image:
    """程序化纸雕人偶(袍服剪影,撕边)。T1 立牌 canonical 纸偶。返回紧致 sprite(底在 SH-14)。"""
    sw, sh = _FIGURE_SW, _FIGURE_SH
    sp = Image.new("RGBA", (sw, sh), (0, 0, 0, 0))
    d = ImageDraw.Draw(sp)
    cx = sw // 2
    base_y = sh - 14
    sh_y = base_y - 300  # 肩线
    # 袍身(梯形,下宽上窄)
    robe = [(cx - 96, base_y), (cx + 96, base_y), (cx + 58, sh_y), (cx - 58, sh_y)]
    d.polygon(
        _deckle(robe, amp=3, step=8, seed=seed), fill=(*accent, 242), outline=(43, 32, 20, 220)
    )
    # 两袖
    d.polygon(
        _deckle(
            [
                (cx - 58, sh_y + 6),
                (cx - 94, sh_y + 44),
                (cx - 80, base_y - 46),
                (cx - 58, base_y - 66),
            ],
            amp=2,
            step=8,
            seed=seed + 3,
        ),
        fill=(*accent, 236),
        outline=(43, 32, 20, 180),
    )
    d.polygon(
        _deckle(
            [
                (cx + 58, sh_y + 6),
                (cx + 94, sh_y + 44),
                (cx + 80, base_y - 46),
                (cx + 58, base_y - 66),
            ],
            amp=2,
            step=8,
            seed=seed + 5,
        ),
        fill=(*accent, 236),
        outline=(43, 32, 20, 180),
    )
    # 镶边(下摆 + 交领 V)
    d.line([(cx - 92, base_y - 10), (cx + 92, base_y - 10)], fill=(*trim, 235), width=7)
    d.polygon([(cx - 56, sh_y + 2), (cx + 56, sh_y + 2), (cx, sh_y + 74)], fill=(*trim, 225))
    # 头
    hy = sh_y - 40
    d.ellipse(
        [cx - 36, hy - 44, cx + 36, hy + 44], fill=(234, 214, 184, 246), outline=(43, 32, 20, 210)
    )
    # 冠 / 发髻
    if crown:
        d.polygon(
            [(cx - 30, hy - 40), (cx + 30, hy - 40), (cx + 22, hy - 88), (cx - 22, hy - 88)],
            fill=(*trim, 242),
            outline=(43, 32, 20, 200),
        )
        d.rectangle([cx - 6, hy - 98, cx + 6, hy - 86], fill=(232, 220, 176, 255))  # 玉簪
    else:
        d.chord([cx - 40, hy - 54, cx + 40, hy - 4], 180, 360, fill=(52, 44, 38, 242))
        d.ellipse([cx - 11, hy - 62, cx + 11, hy - 40], fill=(52, 44, 38, 242))  # 束发髻
    # 须(长者)
    if elder:
        d.polygon(
            [(cx - 20, hy + 30), (cx + 20, hy + 30), (cx, hy + 82)], fill=(212, 206, 196, 236)
        )
    # 眼
    d.ellipse([cx - 16, hy - 6, cx - 8, hy + 2], fill=(40, 30, 25, 255))
    d.ellipse([cx + 8, hy - 6, cx + 16, hy + 2], fill=(40, 30, 25, 255))
    # 纸纹颗粒
    arr = np.asarray(sp, dtype=np.float64)
    grain = _fibre(sw, sh, seed=seed % 89 + 5) * 6.0
    arr[..., :3] = np.clip(arr[..., :3] + grain[..., None], 0, 255)
    return Image.fromarray(arr.astype(np.uint8), "RGBA")


def animate_standee(
    accent,
    trim,
    out_dir: Path,
    *,
    elder=False,
    crown=False,
    seed=1,
    tag="standee",
    size: tuple[int, int] = (1168, 784),
    fps: int = 24,
    duration_s: float = 2.2,
) -> Path:
    """S7 立牌:纸偶自底折痕**翻立**(竖向从压扁 0.05→1,回弹) + 接触阴影随立起收紧。
    B7 断言:立牌身份分(此处 by construction 纸偶恒定)。"""
    w, h = size
    out_dir = Path(out_dir)
    frames_dir = out_dir / f"frames_{tag}"
    frames_dir.mkdir(parents=True, exist_ok=True)
    n = int(fps * duration_s)
    sprite = figure_sprite(accent, trim, elder=elder, crown=crown, seed=seed)
    sw, sh = sprite.size
    cxp, floor_y = w // 2, int(h * 0.93)

    for f in range(n):
        t = f / (n - 1) if n > 1 else 1.0
        frame = _paper_bg(w, h)
        s = max(0.05, min(1.15, ease_out_back(min(1.0, t / 0.62), overshoot=2.2)))
        sh_s = max(1, int(sh * s))
        scaled = sprite.resize((sw, sh_s), Image.BICUBIC)
        px, py = cxp - sw // 2, floor_y - sh_s
        lay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        lay.paste(scaled, (px, py), scaled)
        settle = min(1.0, t / 0.62)
        frame = Image.alpha_composite(
            frame, _shadow_from(lay, 6, 10, blur=6 + 8 * (1 - settle), alpha=int(80 * settle))
        )
        frame = Image.alpha_composite(frame, lay)
        frame.convert("RGB").save(frames_dir / f"f_{f:04d}.png")

    mp4 = out_dir / f"s7_{tag}.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-framerate",
            str(fps),
            "-i",
            str(frames_dir / "f_%04d.png"),
            "-pix_fmt",
            "yuv420p",
            "-crf",
            "18",
            str(mp4),
        ],
        check=True,
    )
    return mp4


def animate_landing(
    target_xf: float,
    target_yf: float,
    out_dir: Path,
    *,
    base: Image.Image | None = None,
    accent=(150, 30, 20),
    size: tuple[int, int] = (1168, 784),
    fps: int = 24,
    duration_s: float = 2.5,
) -> Path:
    """S6 落点:标记片自上落下 + 落定回弹 + 纸屑四溅。base 给底图(如晋阳地图)则叠其上,否则皮纸。
    B6 断言:标记数=1。"""
    w, h = size
    out_dir = Path(out_dir)
    frames_dir = out_dir / "frames_landing"
    frames_dir.mkdir(parents=True, exist_ok=True)
    n = int(fps * duration_s)
    tx, ty = int(w * target_xf), int(h * target_yf)
    # 纸屑落点(确定性散布)
    rng = random.Random(4321)
    debris = [
        (rng.uniform(-40, 40), rng.uniform(-30, 30), rng.uniform(4, 9), rng.random())
        for _ in range(9)
    ]

    for f in range(n):
        t = f / (n - 1) if n > 1 else 1.0
        frame = base.copy() if base is not None else _paper_bg(w, h)
        e = ease_out_back(min(1.0, t / 0.55), overshoot=2.4)  # 落定回弹
        drop = (1.0 - e) * -240  # 从上方落下(负偏移)
        settle = min(1.0, t / 0.55)
        # 标记片(菱形撕纸)
        mk = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        md = ImageDraw.Draw(mk)
        dia = [(tx, ty - 18), (tx + 14, ty), (tx, ty + 18), (tx - 14, ty)]
        md.polygon(
            _deckle(dia, amp=2, step=5, seed=71), fill=(*accent, 240), outline=(43, 32, 20, 220)
        )
        md.ellipse([tx - 4, ty - 4, tx + 4, ty + 4], fill=(235, 225, 200, 255))
        frame = Image.alpha_composite(
            frame,
            _shadow_from(
                mk,
                4 + 6 * (1 - settle),
                8 + drop + 6 * (1 - settle),
                blur=5 + 8 * (1 - settle),
                alpha=int(90 * settle),
            ),
        )
        frame = Image.alpha_composite(frame, _place(mk, 0, drop, min(1.0, t / 0.3)))
        # 纸屑(落定瞬间迸溅后落下)
        if settle > 0.55:
            burst = min(1.0, (t - 0.5) / 0.5)
            dd = ImageDraw.Draw(frame)
            for dx, dy, r, phase in debris:
                bx = tx + dx * burst
                by = ty + dy * burst + burst * burst * 30
                col = accent if phase > 0.5 else (210, 195, 160)
                dd.polygon(
                    _deckle(
                        [(bx - r, by - r), (bx + r, by - r), (bx, by + r)],
                        amp=1.5,
                        step=4,
                        seed=int(phase * 999),
                    ),
                    fill=(*col, int(220 * (1 - burst * 0.4))),
                )
        frame.convert("RGB").save(frames_dir / f"f_{f:04d}.png")

    mp4 = out_dir / "s6_landing.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-framerate",
            str(fps),
            "-i",
            str(frames_dir / "f_%04d.png"),
            "-pix_fmt",
            "yuv420p",
            "-crf",
            "18",
            str(mp4),
        ],
        check=True,
    )
    return mp4


__all__ = [
    "animate_establish",
    "animate_fissure_reveal",
    "animate_landing",
    "animate_route",
    "animate_standee",
    "animate_tear",
    "animate_timeline",
    "ease_out_back",
    "figure_sprite",
    "smoothstep",
]
