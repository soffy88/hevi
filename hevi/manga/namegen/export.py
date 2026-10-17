"""M1 分镜生成器 — SVG + PNG export, including diagnostic overlay.

Determinism note: We render the page, panels, bubbles, effect lines, and the
diagnostic layer (reading-order numbers, line-of-sight arrows, dialogue axis)
from the Storyboard model with an SVG serializer.  SVG is text and serializes
identically for identical inputs, which is what the "same seed reproduces
byte-identical output" test checks.  PNG is rasterized from that SVG with
Pillow (no network, no GPU).
"""

from __future__ import annotations

import base64
import html
import io
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from . import Panel, Storyboard

# dialogue bubble palette per emotion (just stroke/shape hints)
_BUBBLE_FILL = "#ffffff"
_BUBBLE_STROKE = "#111111"


def _svg_escape(s: str) -> str:
    return html.escape(s, quote=True)


def _bubble_shape(shape: str, cx: float, cy: float, w: float, h: float) -> str:
    """Return an SVG path/shape string for a dialogue bubble interior.

    Centered at (cx, cy) with outer box of width w, height h.  Tail points down.
    """
    x0, y0 = cx - w / 2, cy - h / 2
    x1, y1 = cx + w / 2, cy + h / 2
    r = min(w, h) * 0.22
    if shape in ("rounded", "soft", "whisper"):
        # rounded rectangle
        return (f'<rect x="{x0:.1f}" y="{y0:.1f}" width="{w:.1f}" height="{h:.1f}" '
                f'rx="{r:.1f}" ry="{r:.1f}" fill="{_BUBBLE_FILL}" '
                f'stroke="{_BUBBLE_STROKE}" stroke-width="3"/>')
    if shape == "spiked":
        # jagged star-ish bubble
        pts = []
        n = 14
        cxr, cyr = cx, cy
        for i in range(n * 2):
            ang = math.pi * i / n
            rad = (w / 2) if i % 2 == 0 else (w / 2) * 0.72
            pts.append(f"{cxr + rad * math.cos(ang):.1f},{cyr + rad * math.sin(ang):.1f}")
        return (f'<polygon points="{" ".join(pts)}" fill="{_BUBBLE_FILL}" '
                f'stroke="{_BUBBLE_STROKE}" stroke-width="3"/>')
    if shape in ("cloud", "cloud_thought"):
        # scalloped cloud using circles
        circles = []
        n = 6
        for i in range(n):
            ang = 2 * math.pi * i / n
            bx = cx + (w / 2 - r) * math.cos(ang)
            by = cy + (h / 2 - r) * math.sin(ang)
            circles.append(f'<circle cx="{bx:.1f}" cy="{by:.1f}" r="{r:.1f}" '
                           f'fill="{_BUBBLE_FILL}" stroke="{_BUBBLE_STROKE}" stroke-width="3"/>')
        circles.append(f'<ellipse cx="{cx:.1f}" cy="{cy:.1f}" rx="{w/2-r:.1f}" '
                       f'ry="{h/2-r:.1f}" fill="{_BUBBLE_FILL}"/>')
        return "".join(circles)
    if shape == "teardrop":
        return (f'<path d="M{cx:.1f} {y0:.1f} '
                f'C{x0:.1f} {cy:.1f} {x0:.1f} {y1:.1f} {cx:.1f} {y1:.1f} '
                f'C{x1:.1f} {y1:.1f} {x1:.1f} {cy:.1f} {cx:.1f} {y0:.1f} Z" '
                f'fill="{_BUBBLE_FILL}" stroke="{_BUBBLE_STROKE}" stroke-width="3"/>')
    # default rounded
    return (f'<rect x="{x0:.1f}" y="{y0:.1f}" width="{w:.1f}" height="{h:.1f}" '
            f'rx="{r:.1f}" ry="{r:.1f}" fill="{_BUBBLE_FILL}" '
            f'stroke="{_BUBBLE_STROKE}" stroke-width="3"/>')


def _effect_lines(kind: str, w: int, h: int, seed_tag: str) -> str:
    """Deterministic decorative SVG for effect lines within a panel box."""
    out = []
    if kind == "speed_lines":
        # radial lines from right edge
        for i in range(0, h, max(6, h // 18)):
            out.append(f'<line x1="{w}" y1="{i}" x2="{int(w*0.7)}" y2="{i}" '
                       f'stroke="#222" stroke-width="1.5" opacity="0.5"/>')
    elif kind == "concentration_lines":
        cx, cy = w // 2, h // 2
        for i in range(6):
            rr = (w // 2) * (0.4 + 0.1 * i)
            out.append(f'<circle cx="{cx}" cy="{cy}" r="{int(rr)}" fill="none" '
                       f'stroke="#333" stroke-width="1.2" opacity="0.4"/>')
    elif kind == "tone_dots":
        for i in range(20):
            x = (i * 53) % w
            y = (i * 97) % h
            out.append(f'<circle cx="{x}" cy="{y}" r="2" fill="#444" opacity="0.4"/>')
    return "".join(out)


def render_svg(board: Storyboard) -> str:
    """Serialize the storyboard to a single-page SVG (with diagnostics)."""
    W, H = board.page_w, board.page_h
    parts = [
        f'<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
        f'viewBox="0 0 {W} {H}">',
        f'<rect width="{W}" height="{H}" fill="#f4f1ea"/>',
    ]
    # panels
    for p in board.panels:
        parts.append(f'<rect x="{p.x}" y="{p.y}" width="{p.w}" height="{p.h}" '
                     f'fill="#ffffff" stroke="#000" stroke-width="3"/>')
        # background plate hint
        if p.beat.bg_kind != "none":
            tag = p.beat.bg_kind
            parts.append(f'<text x="{p.x+6}" y="{p.y+16}" font-size="12" fill="#999" '
                         f'font-family="monospace">{_svg_escape(tag)}</text>')
        # camera + pose annotation
        cam = p.camera
        parts.append(f'<text x="{p.x+6}" y="{p.y+p.h-8}" font-size="11" fill="#333" '
                     f'font-family="monospace">{_svg_escape(cam.get("shot",""))} '
                     f'{cam.get("mm",0)}mm {cam.get("pitch","")}/{cam.get("tilt","")}</text>')
        # character pose stick figure (simple)
        ch = p.characters[0] if p.characters else None
        if ch:
            fx = p.x + p.w * ch["floor_x"]
            fy = p.y + p.h * 0.82
            parts.append(_stick_figure(fx, fy, ch["pose"]))
        # dialogue bubble
        if p.dialogue:
            bw = min(p.w * 0.6, 260)
            bh = 46
            bx = p.x + p.w * 0.5
            by = p.y + p.h * 0.3
            parts.append(_bubble_shape(p.dialogue["shape"], bx, by, bw, bh))
            # text (verbatim)
            txt = p.dialogue["text"]
            wrapped = _wrap(txt, max(4, int(bw / 12)))
            ty = by - (len(wrapped) - 1) * 9
            for j, line in enumerate(wrapped):
                parts.append(f'<text x="{bx:.1f}" y="{ty + j*18:.1f}" font-size="13" '
                             f'text-anchor="middle" fill="#111" '
                             f'font-family="sans-serif">{_svg_escape(line)}</text>')
            if p.dialogue.get("speaker"):
                parts.append(f'<text x="{bx:.1f}" y="{by - bh/2 - 6:.1f}" font-size="11" '
                             f'text-anchor="middle" fill="#666" '
                             f'font-family="sans-serif">{_svg_escape(str(p.dialogue["speaker"]))}</text>')
        # effect lines
        for eff in p.effects:
            parts.append(_effect_lines(eff, p.w, p.h, f"p{p.index}"))

    # ---- diagnostic overlay ----
    parts.append('<g font-family="monospace" font-size="14" fill="#e6550d">')
    for p in sorted(board.panels, key=lambda q: q.read_order):
        # reading order number
        parts.append(f'<circle cx="{p.x+14}" cy="{p.y+14}" r="11" fill="#fff" '
                     f'stroke="#e6550d" stroke-width="2"/>')
        parts.append(f'<text x="{p.x+14}" y="{p.y+19}" text-anchor="middle" '
                     f'fill="#e6550d">{p.read_order}</text>')
    parts.append('</g>')

    # line-of-sight arrows + 180 axis per panel (derived from camera.side)
    parts.append('<g stroke="#1f77b4" stroke-width="2" fill="none" opacity="0.8">')
    for p in board.panels:
        cx = p.x + p.w / 2
        cy = p.y + p.h / 2
        side = p.beat.camera_side
        if side != 0:
            dx = math.copysign(1.0, side) * (p.w * 0.3)
            parts.append(f'<line x1="{cx:.1f}" y1="{cy:.1f}" x2="{cx+dx:.1f}" '
                         f'y2="{cy:.1f}" marker-end="url(#arrow)"/>')
    parts.append('</g>')
    parts.append('<defs><marker id="arrow" markerWidth="8" markerHeight="8" '
                 'refX="6" refY="3" orient="auto"><path d="M0,0 L6,3 L0,6 Z" '
                 'fill="#1f77b4"/></marker></defs>')

    # axis violation banner
    if board.axis_violations:
        msg = f"180° VIOLATION @ {board.axis_violations[0]['between']}"
        parts.append(f'<text x="{W//2}" y="20" text-anchor="middle" font-size="16" '
                     f'fill="#d62728" font-family="monospace">{_svg_escape(msg)}</text>')

    parts.append('</svg>')
    return "\n".join(parts)


def _stick_figure(cx: float, fy: float, pose: str) -> str:
    head = f'<circle cx="{cx:.1f}" cy="{fy-44:.1f}" r="9" fill="none" stroke="#222" stroke-width="2"/>'
    body = f'<line x1="{cx:.1f}" y1="{fy-35:.1f}" x2="{cx:.1f}" y2="{fy-10:.1f}" stroke="#222" stroke-width="2"/>'
    legs = f'<line x1="{cx:.1f}" y1="{fy-10:.1f}" x2="{cx-8:.1f}" y2="{fy:.1f}" stroke="#222" stroke-width="2"/>' \
           f'<line x1="{cx:.1f}" y1="{fy-10:.1f}" x2="{cx+8:.1f}" y2="{fy:.1f}" stroke="#222" stroke-width="2"/>'
    arms = ''
    if pose == "wave":
        arms = f'<line x1="{cx:.1f}" y1="{fy-30:.1f}" x2="{cx+12:.1f}" y2="{fy-42:.1f}" stroke="#222" stroke-width="2"/>'
    elif pose == "point":
        arms = f'<line x1="{cx:.1f}" y1="{fy-30:.1f}" x2="{cx+16:.1f}" y2="{fy-26:.1f}" stroke="#222" stroke-width="2"/>'
    elif pose in ("walk", "run"):
        arms = f'<line x1="{cx:.1f}" y1="{fy-30:.1f}" x2="{cx+10:.1f}" y2="{fy-24:.1f}" stroke="#222" stroke-width="2"/>' \
               f'<line x1="{cx:.1f}" y1="{fy-30:.1f}" x2="{cx-10:.1f}" y2="{fy-24:.1f}" stroke="#222" stroke-width="2"/>'
    else:
        arms = f'<line x1="{cx:.1f}" y1="{fy-30:.1f}" x2="{cx+10:.1f}" y2="{fy-26:.1f}" stroke="#222" stroke-width="2"/>' \
               f'<line x1="{cx:.1f}" y1="{fy-30:.1f}" x2="{cx-10:.1f}" y2="{fy-26:.1f}" stroke="#222" stroke-width="2"/>'
    return head + body + legs + arms


def _wrap(text: str, n: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    cur = ""
    for w in words:
        if len(cur) + len(w) + 1 > n and cur:
            lines.append(cur)
            cur = w
        else:
            cur = (cur + " " + w).strip()
    if cur:
        lines.append(cur)
    return lines or [""]


def svg_to_png(svg_text: str, out_path: str | Path, scale: int = 1) -> Path:
    """Rasterize SVG to PNG with Pillow (background fill + text approximated).

    Our SVG is simple (rects, lines, circles, text).  For a faithful raster we
    parse the primitives ourselves rather than depend on cairosvg (keeps the
    unit CPU-only and dependency-light).  Returns the output path.
    """
    out = Path(out_path)
    lines = svg_text.splitlines()
    # crude parse: find svg root for size
    import re
    m = re.search(r'<svg[^>]*width="(\d+)"[^>]*height="(\d+)"', svg_text)
    W = int(m.group(1)) if m else 800
    H = int(m.group(2)) if m else 1100
    img = Image.new("RGB", (W, H), (244, 241, 234))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 13)
    except Exception:
        font = ImageFont.load_default()
    for ln in lines:
        if ln.startswith("<rect"):
            vals = _attrs(ln)
            x, y, w, h = (int(float(vals.get(k, 0))) for k in ("x", "y", "width", "height"))
            fill = _parse_color(vals.get("fill", "none"))
            stroke = _parse_color(vals.get("stroke", "none"))
            if fill:
                draw.rectangle([x, y, x + w, y + h], fill=fill, outline=stroke, width=1)
        elif ln.startswith("<line"):
            vals = _attrs(ln)
            coords = (int(float(vals["x1"])), int(float(vals["y1"])),
                      int(float(vals["x2"])), int(float(vals["y2"])))
            col = _parse_color(vals.get("stroke", "#000")) or (0, 0, 0)
            draw.line(coords, fill=col, width=int(float(vals.get("stroke-width", "1"))))
        elif ln.startswith("<circle") and "marker" not in ln:
            vals = _attrs(ln)
            cx, cy, r = int(float(vals["cx"])), int(float(vals["cy"])), int(float(vals["r"]))
            fill = _parse_color(vals.get("fill", "none"))
            if fill:
                draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=fill)
        elif ln.startswith("<text"):
            m2 = re.search(r'x="([\d.]+)" y="([\d.]+)"[^>]*>(.*?)</text>', ln)
            if m2:
                x, y, txt = float(m2.group(1)), float(m2.group(2)), _unescape(m2.group(3))
                draw.text((x, y - 11), txt, fill=(20, 20, 20), font=font)
        elif ln.startswith("<polygon"):
            vals = _attrs(ln)
            pts = [tuple(map(float, p.split(","))) for p in vals["points"].split()]
            fill = _parse_color(vals.get("fill", "none"))
            if fill and len(pts) > 2:
                draw.polygon([(int(a), int(b)) for a, b in pts], fill=fill)
    if scale != 1:
        img = img.resize((W * scale, H * scale), Image.LANCZOS)
    img.save(out, format="PNG")
    return out


def _attrs(ln: str) -> dict[str, str]:
    import re
    return dict(re.findall(r'(\w+)="([^"]*)"', ln))


def _parse_color(c: str):
    if c in (None, "none", ""):
        return None
    if c.startswith("#"):
        h = c[1:]
        if len(h) == 3:
            h = "".join(ch * 2 for ch in h)
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    return (0, 0, 0)


def _unescape(s: str) -> str:
    import html as _h
    return _h.unescape(s).replace("&amp;", "&")
