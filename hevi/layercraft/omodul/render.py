"""omodul: frame renderers + mp4 entry points for layercraft.

* ``svg_draw_on``      -- generic SVG stroke draw-on (dashoffset L->0), fill fades in after.
* ``layered_reveal``   -- SVG whose top-level <g> are layers; each layer enters half a beat
                          after the previous with fade + slide-up + stroke draw-on.
* ``default_landscape_svg`` -- sky/sun/far hills/near hills/trees/text demo document.
* ``paper_cut``        -- image -> colour-zone paper sheets (shadow, white rim, grain), staggered drop-in.
* ``boiling_lines``    -- rough.js-style polylines re-seeded every ``hold`` frames (boiling line),
                          optionally drawn on.
All CPU, Pillow; deterministic for a given seed.
"""

from __future__ import annotations

import copy
import math
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
from PIL import Image, ImageColor, ImageDraw, ImageFont

from hevi.layercraft.obase.ffmpeg_sink import FFmpegSink
from hevi.layercraft.oskill import paper_cut as pc
from hevi.layercraft.oskill.svg_path import Shape, parse_svg, polyline_length, trim_polyline
from hevi.layercraft.oskill.timing import (
    boil_seed, ease_in_out_cubic, ease_out_back, ease_out_cubic, layer_enter_state, local,
    stagger_starts, sway,
)

SS = 2  # supersampling factor for anti-aliased strokes
FONT_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]


def _font(px: int):
    for f in FONT_CANDIDATES:
        if Path(f).exists():
            return ImageFont.truetype(f, px)
    return ImageFont.load_default()


def _rgb(c, default=(0, 0, 0)):
    try:
        return ImageColor.getrgb(c)[:3] if c else default
    except ValueError:
        return default


# ------------------------------------------------------------ primitives

def draw_shapes(shapes: list[Shape], size, progress: list[float], fill_alpha: list[float] | None = None,
                bg=None) -> Image.Image:
    """Draw shapes with per-shape stroke progress (0..1 of total length) and fill alpha."""
    W, H = size
    im = Image.new("RGBA", (W * SS, H * SS), bg or (0, 0, 0, 0))
    for i, sh in enumerate(shapes):
        fa = fill_alpha[i] if fill_alpha else 0.0
        if sh.fill and fa > 0:
            lay = Image.new("RGBA", im.size, (0, 0, 0, 0))
            d = ImageDraw.Draw(lay)
            for pts, _c in sh.subpaths:
                if len(pts) >= 3:
                    d.polygon([(x * SS, y * SS) for x, y in pts], fill=_rgb(sh.fill) + (int(255 * fa),))
            im.alpha_composite(lay)
        if sh.stroke and progress[i] > 0:
            d = ImageDraw.Draw(im)
            remain = sh.length * min(1.0, progress[i])
            w = max(1, int(round(sh.stroke_width * SS)))
            col = _rgb(sh.stroke) + (255,)
            for pts, _c in sh.subpaths:
                if remain <= 0:
                    break
                L = polyline_length(pts)
                part = trim_polyline(pts, min(L, remain))
                remain -= L
                if len(part) >= 2:
                    sp = [(x * SS, y * SS) for x, y in part]
                    d.line(sp, fill=col, width=w, joint="curve")
                    r = w / 2
                    for x, y in (sp[0], sp[-1]):  # round caps
                        d.ellipse([x - r, y - r, x + r, y + r], fill=col)
    return im.resize((W, H), Image.LANCZOS)


def _encode(frames_iter, out, size, fps):
    with FFmpegSink(out, size, fps) as sink:
        for fr in frames_iter:
            sink.write(fr)
    return Path(out)


def _bg(size, color=(250, 246, 238)):
    return Image.new("RGBA", size, color + (255,))


# ------------------------------------------------------------ 1. SVG draw-on

def svg_draw_on_frames(svg_text: str, *, size=(480, 270), fps=24, duration=3.0, stagger=0.12,
                       draw_dur=None, fill_fade=0.4, bg=(250, 246, 238)):
    shapes, size = parse_svg(svg_text, size)
    n = max(1, len(shapes))
    draw_dur = draw_dur or max(0.3, duration - fill_fade - stagger * (n - 1) - 0.3)
    for f in range(int(round(duration * fps))):
        t = f / fps
        prog, fa = [], []
        for i, sh in enumerate(shapes):
            st = i * stagger
            prog.append(ease_in_out_cubic(local(t, st, draw_dur)))
            fa.append(ease_out_cubic(local(t, st + draw_dur * 0.85, fill_fade)))
        fr = _bg(size, bg)
        fr.alpha_composite(draw_shapes(shapes, size, prog, fa))
        yield fr


def svg_draw_on(svg_text: str, out, *, size=(480, 270), fps=24, duration=3.0, **kw) -> Path:
    _, size = parse_svg(svg_text, size)
    return _encode(svg_draw_on_frames(svg_text, size=size, fps=fps, duration=duration, **kw), out, size, fps)


# ------------------------------------------------------------ 2. layered reveal

def split_svg_layers(svg_text: str) -> list[tuple[str, str, list[dict]]]:
    """Top-level <g> of an SVG -> [(layer_id, sub_svg_text, texts)]."""
    ET.register_namespace("", "http://www.w3.org/2000/svg")
    root = ET.fromstring(svg_text)
    out = []
    groups = [el for el in root if el.tag.split("}")[-1] == "g"]
    for idx, g in enumerate(groups):
        r2 = copy.copy(root)
        for ch in list(r2):
            r2.remove(ch)
        texts = []
        g2 = copy.deepcopy(g)
        for el in list(g2.iter()):
            for ch in list(el):
                if ch.tag.split("}")[-1] == "text":
                    texts.append({"x": float(ch.get("x", 0)), "y": float(ch.get("y", 0)),
                                  "size": float(ch.get("font-size", 32)), "fill": ch.get("fill", "#222"),
                                  "anchor": ch.get("text-anchor", "start"), "text": "".join(ch.itertext())})
                    el.remove(ch)
        r2.append(g2)
        out.append((g.get("id") or f"layer{idx}", ET.tostring(r2, encoding="unicode"), texts))
    return out


def _text_layer(texts, size, scale, offset):
    im = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    for tx in texts:
        f = _font(max(8, int(tx["size"] * scale)))
        x, y = tx["x"] * scale + offset[0], tx["y"] * scale + offset[1]
        anchor = {"middle": "ms", "end": "rs"}.get(tx["anchor"], "ls")
        d.text((x, y), tx["text"], font=f, fill=_rgb(tx["fill"]), anchor=anchor)
    return im


def _viewbox_map(svg_text, size):
    root = ET.fromstring(svg_text)
    vb = [float(v) for v in (root.get("viewBox") or f"0 0 {size[0]} {size[1]}").replace(",", " ").split()]
    sc = min(size[0] / vb[2], size[1] / vb[3])
    return sc, (-vb[0] * sc + (size[0] - vb[2] * sc) / 2, -vb[1] * sc + (size[1] - vb[3] * sc) / 2)


def layered_reveal_frames(svg_text: str, *, size=(480, 270), fps=24, duration=4.0, bpm=120.0,
                          step_beats=0.5, enter_dur=0.7, rise=None, bg=(250, 246, 238)):
    layers = split_svg_layers(svg_text)
    sc, off = _viewbox_map(svg_text, size)
    rise = size[1] * 0.08 if rise is None else rise
    starts = stagger_starts(len(layers), bpm=bpm, step_beats=step_beats)
    prepared = []
    for (lid, sub, texts), st in zip(layers, starts):
        shapes, _ = parse_svg(sub, size)
        fill = draw_shapes(shapes, size, [0.0] * len(shapes), [1.0] * len(shapes))
        if texts:
            fill.alpha_composite(_text_layer(texts, size, sc, off))
        prepared.append((lid, shapes, fill, st))
    for f in range(int(round(duration * fps))):
        t = f / fps
        fr = _bg(size, bg)
        for lid, shapes, fill, st in prepared:
            s = layer_enter_state(t, st, dur=enter_dur, rise=rise, stroke_dur=enter_dur * 1.6)
            if s["alpha"] <= 0 and s["stroke"] <= 0:
                continue
            dy = int(round(s["dy"]))
            lay = Image.new("RGBA", size, (0, 0, 0, 0))
            a = fill.getchannel("A").point(lambda v, k=s["alpha"]: int(v * k))
            fl = fill.copy(); fl.putalpha(a)
            lay.alpha_composite(fl, (0, dy) if dy >= 0 else (0, 0), (0, 0) if dy >= 0 else (0, -dy))
            strokes = [sh for sh in shapes if sh.stroke]
            if strokes and s["stroke"] > 0:
                st_im = draw_shapes(strokes, size, [s["stroke"]] * len(strokes))
                lay.alpha_composite(st_im, (0, max(0, dy)))
            fr.alpha_composite(lay)
        yield fr


def layered_reveal(svg_text: str, out, *, size=(480, 270), fps=24, duration=4.0, **kw) -> Path:
    return _encode(layered_reveal_frames(svg_text, size=size, fps=fps, duration=duration, **kw), out, size, fps)


def default_landscape_svg(title: str = "山 野 晨 光") -> str:
    """Six-layer demo: sky / sun / far hills / near hills / trees / text (viewBox 960x540)."""
    trees = []
    for i, (x, h) in enumerate([(120, 120), (190, 90), (700, 140), (780, 100), (850, 125)]):
        y = 470
        trees.append(f'<polygon points="{x},{y-h} {x-34},{y} {x+34},{y}" fill="#2f6b46" stroke="#1b3a26" stroke-width="4"/>'
                     f'<rect x="{x-6}" y="{y}" width="12" height="26" fill="#6b4a2b" stroke="#1b3a26" stroke-width="3"/>')
    sky = "".join(f'<rect x="0" y="{i*45}" width="960" height="46" fill="{c}"/>' for i, c in enumerate(
        ["#f6c6a8", "#f8d0ae", "#f9dab4", "#fae3bb", "#fbebc3", "#fcf1cb", "#fdf5d3", "#fef8da", "#fefade", "#fffbe2", "#fffce6", "#fffdea"]))
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 540" width="960" height="540">
<g id="sky">{sky}</g>
<g id="sun"><circle cx="700" cy="170" r="70" fill="#f39a4a" stroke="#c4612a" stroke-width="5"/></g>
<g id="far_hills"><path d="M0 360 Q 120 240 260 320 T 520 300 T 780 280 T 960 320 L 960 540 L 0 540 Z" fill="#9db8c9" stroke="#5b7a8f" stroke-width="4"/></g>
<g id="near_hills"><path d="M0 430 C 160 330 300 380 420 410 S 700 340 960 420 L 960 540 L 0 540 Z" fill="#6f9e6a" stroke="#3d6640" stroke-width="5"/></g>
<g id="trees">{"".join(trees)}</g>
<g id="text"><text x="480" y="120" font-size="64" fill="#3a2a1a" text-anchor="middle">{title}</text>
<path d="M330 145 C 400 160 560 135 630 150" fill="none" stroke="#c4612a" stroke-width="6"/></g>
</svg>'''


# ------------------------------------------------------------ 3. paper cut

def paper_cut_frames(img: Image.Image, *, k=5, size=(480, 270), fps=24, duration=4.0, bpm=120.0,
                     step_beats=0.5, seed=0, border=None, shadow=None, drop=None, bg=(240, 234, 222)):
    W, H = size
    src = img.convert("RGB")
    # cover-crop to target aspect
    sr, tr = src.width / src.height, W / H
    if sr > tr:
        nw = int(src.height * tr); src = src.crop(((src.width - nw) // 2, 0, (src.width - nw) // 2 + nw, src.height))
    else:
        nh = int(src.width / tr); src = src.crop((0, (src.height - nh) // 2, src.width, (src.height - nh) // 2 + nh))
    src = src.resize(size, Image.LANCZOS)
    layers = pc.split_layers(src, k, seed=seed)
    border = border if border is not None else max(2, W // 160)
    shadow = shadow if shadow is not None else W / 90
    drop = drop if drop is not None else H * 0.12
    sheets = []
    for i, L in enumerate(layers):
        g = pc.paper_grain(size, seed=seed * 101 + i, strength=0.07)
        sheet = pc.paper_sheet(L.mask, L.color, border=0 if i == 0 else border, grain=g)
        sheets.append((sheet, pc.drop_shadow(sheet, blur=shadow * 0.8, opacity=0.5)))
    starts = stagger_starts(len(sheets), bpm=bpm, step_beats=step_beats)
    for f in range(int(round(duration * fps))):
        t = f / fps
        fr = _bg(size, bg)
        for i, ((sheet, shd), st) in enumerate(zip(sheets, starts)):
            p = local(t, st, 0.6)
            if p <= 0:
                continue
            e = ease_out_back(p)
            alpha = ease_out_cubic(min(1.0, p * 1.6))
            dx = sway(t - st, 1.5 * i / max(1, len(sheets) - 1), 3.0, i) if p >= 1 else 0.0
            dy = -drop * (1 - e)
            lift = 1.0 + 1.5 * (1 - ease_out_cubic(p))  # shadow larger while "in the air"
            so = (int(round(dx + shadow * 0.5 * lift * (i > 0))), int(round(dy + shadow * 0.7 * lift * (i > 0))))
            if i > 0:
                s2 = shd.copy(); s2.putalpha(shd.getchannel("A").point(lambda v, a=alpha: int(v * a)))
                fr.alpha_composite(_shift(s2, so))
            s1 = sheet.copy(); s1.putalpha(sheet.getchannel("A").point(lambda v, a=alpha: int(v * a)))
            fr.alpha_composite(_shift(s1, (int(round(dx)), int(round(dy)))))
        yield fr


def _shift(im, d):
    out = Image.new("RGBA", im.size, (0, 0, 0, 0))
    out.paste(im, d, im)
    return out


def paper_cut(image_path, out, *, size=(480, 270), fps=24, duration=4.0, **kw) -> Path:
    img = Image.open(image_path)
    return _encode(paper_cut_frames(img, size=size, fps=fps, duration=duration, **kw), out, size, fps)


# ------------------------------------------------------------ 4. boiling line

def boiling_passes(polylines, frame: int, *, hold=3, base_seed=0, roughness=1.5, bowing=1.0,
                   double_stroke=True, closed=False):
    """rough_stroke passes for ``frame`` with a seed that changes every ``hold`` frames."""
    from hevi.layer4_legacy.handdraw.rough_stroke import roughen_polylines
    res = roughen_polylines(polylines, roughness=roughness, bowing=bowing,
                            seed=boil_seed(frame, base_seed, hold) * 1000, double_stroke=double_stroke, closed=closed)
    return [list(map(list, p)) for r in res for p in r.passes]


def boiling_lines_frames(polylines, *, size=(480, 270), fps=24, duration=3.0, hold=3, base_seed=0,
                         draw_on=0.0, color=(30, 30, 30), width=2.5, bg=(250, 246, 238), **rough):
    for f in range(int(round(duration * fps))):
        t = f / fps
        prog = ease_in_out_cubic(local(t, 0, draw_on)) if draw_on > 0 else 1.0
        passes = boiling_passes(polylines, f, hold=hold, base_seed=base_seed, **rough)
        shapes = [Shape([(p, False)], stroke="#%02x%02x%02x" % color, stroke_width=width) for p in passes]
        # draw-on by shared fraction so double-stroke passes grow together
        fr = _bg(size, bg)
        fr.alpha_composite(draw_shapes(shapes, size, [prog] * len(shapes)))
        yield fr


def boiling_lines(polylines, out, *, size=(480, 270), fps=24, duration=3.0, **kw) -> Path:
    return _encode(boiling_lines_frames(polylines, size=size, fps=fps, duration=duration, **kw), out, size, fps)
