"""oskill: pure-Python SVG geometry for stroke draw-on animation.

Parses SVG path data / basic shapes into flattened polylines, measures their
length and trims them -- the exact equivalent of CSS
``stroke-dasharray: L; stroke-dashoffset: L -> 0`` (visible = L - offset).
No cairo, no browser. Supported: <path> (M L H V C S Q T A Z, abs+rel),
<line> <polyline> <polygon> <rect> <circle> <ellipse>, root viewBox, and
translate/scale/matrix transforms on elements and <g>.
"""

from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

Point = tuple[float, float]

_TOKEN = re.compile(r"[MmLlHhVvCcSsQqTtAaZz]|[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?")


def _cubic(p0, p1, p2, p3, n):
    out = []
    for i in range(1, n + 1):
        t = i / n
        u = 1 - t
        out.append((u**3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t**3 * p3[0],
                    u**3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t**3 * p3[1]))
    return out


def _quad(p0, p1, p2, n):
    out = []
    for i in range(1, n + 1):
        t = i / n
        u = 1 - t
        out.append((u * u * p0[0] + 2 * u * t * p1[0] + t * t * p2[0],
                    u * u * p0[1] + 2 * u * t * p1[1] + t * t * p2[1]))
    return out


def _seg_n(*pts, tol=1.0):
    approx = sum(math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))
    return max(4, min(256, int(approx / max(tol, 0.05)) + 1))


def _arc(p0, rx, ry, phi_deg, large, sweep, p1, tol):
    """SVG endpoint arc -> points (SVG 1.1 F.6.5)."""
    if rx == 0 or ry == 0 or p0 == p1:
        return [p1]
    rx, ry = abs(rx), abs(ry)
    phi = math.radians(phi_deg)
    c, s = math.cos(phi), math.sin(phi)
    dx, dy = (p0[0] - p1[0]) / 2, (p0[1] - p1[1]) / 2
    x1, y1 = c * dx + s * dy, -s * dx + c * dy
    lam = x1 * x1 / (rx * rx) + y1 * y1 / (ry * ry)
    if lam > 1:
        rx, ry = rx * math.sqrt(lam), ry * math.sqrt(lam)
    num = rx * rx * ry * ry - rx * rx * y1 * y1 - ry * ry * x1 * x1
    den = rx * rx * y1 * y1 + ry * ry * x1 * x1
    co = math.sqrt(max(0.0, num / den)) if den else 0.0
    if large == sweep:
        co = -co
    cx1, cy1 = co * rx * y1 / ry, -co * ry * x1 / rx
    cx = c * cx1 - s * cy1 + (p0[0] + p1[0]) / 2
    cy = s * cx1 + c * cy1 + (p0[1] + p1[1]) / 2

    def ang(ux, uy, vx, vy):
        a = math.atan2(ux * vy - uy * vx, ux * vx + uy * vy)
        return a

    t1 = ang(1, 0, (x1 - cx1) / rx, (y1 - cy1) / ry)
    dt = ang((x1 - cx1) / rx, (y1 - cy1) / ry, (-x1 - cx1) / rx, (-y1 - cy1) / ry)
    if not sweep and dt > 0:
        dt -= 2 * math.pi
    elif sweep and dt < 0:
        dt += 2 * math.pi
    n = max(4, min(256, int(abs(dt) * max(rx, ry) / max(tol, 0.05)) + 1))
    out = []
    for i in range(1, n + 1):
        t = t1 + dt * i / n
        ex, ey = rx * math.cos(t), ry * math.sin(t)
        out.append((c * ex - s * ey + cx, s * ex + c * ey + cy))
    out[-1] = p1
    return out


def parse_path_d(d: str, tol: float = 1.0) -> list[tuple[list[Point], bool]]:
    """Flatten SVG path data into ``[(points, closed), ...]`` subpaths."""
    toks = _TOKEN.findall(d or "")
    subs: list[tuple[list[Point], bool]] = []
    cur: list[Point] = []
    pos = (0.0, 0.0)
    start = pos
    last_c = None  # last cubic control (for S)
    last_q = None  # last quad control (for T)
    cmd = None
    i = 0

    def num():
        nonlocal i
        if i >= len(toks) or toks[i].isalpha():
            raise ValueError(f"bad path data near token {i}: {d[:60]!r}")
        v = float(toks[i])
        i += 1
        return v

    def flush(closed=False):
        nonlocal cur
        if len(cur) >= 2:
            subs.append((cur, closed))
        cur = []

    while i < len(toks):
        if toks[i].isalpha():
            cmd = toks[i]
            i += 1
        elif cmd is None:
            raise ValueError("path data must start with a command")
        rel = cmd.islower()
        C = cmd.upper()
        ox, oy = pos if rel else (0.0, 0.0)
        if C == "Z":
            if cur:
                if cur[-1] != start:
                    cur.append(start)
                flush(True)
            pos = start
            cur = []
            last_c = last_q = None
            continue
        if C == "M":
            flush()
            pos = (ox + num(), oy + num())
            start = pos
            cur = [pos]
            cmd = "l" if rel else "L"
            last_c = last_q = None
            continue
        if not cur:
            cur = [pos]
        if C == "L":
            pos = (ox + num(), oy + num()); cur.append(pos); last_c = last_q = None
        elif C == "H":
            pos = ((pos[0] if rel else 0) + num(), pos[1]); cur.append(pos); last_c = last_q = None
        elif C == "V":
            pos = (pos[0], (pos[1] if rel else 0) + num()); cur.append(pos); last_c = last_q = None
        elif C in ("C", "S"):
            if C == "C":
                c1 = (ox + num(), oy + num())
            else:
                c1 = (2 * pos[0] - last_c[0], 2 * pos[1] - last_c[1]) if last_c else pos
            c2 = (ox + num(), oy + num())
            p = (ox + num(), oy + num())
            cur.extend(_cubic(pos, c1, c2, p, _seg_n(pos, c1, c2, p, tol=tol)))
            last_c, last_q, pos = c2, None, p
        elif C in ("Q", "T"):
            if C == "Q":
                c1 = (ox + num(), oy + num())
            else:
                c1 = (2 * pos[0] - last_q[0], 2 * pos[1] - last_q[1]) if last_q else pos
            p = (ox + num(), oy + num())
            cur.extend(_quad(pos, c1, p, _seg_n(pos, c1, p, tol=tol)))
            last_q, last_c, pos = c1, None, p
        elif C == "A":
            rx, ry, rot, la, sw = num(), num(), num(), num(), num()
            p = (ox + num(), oy + num())
            cur.extend(_arc(pos, rx, ry, rot, int(la), int(sw), p, tol))
            pos, last_c, last_q = p, None, None
        else:
            raise ValueError(f"unsupported path command {cmd!r}")
    flush()
    return subs


def polyline_length(pts) -> float:
    return sum(math.dist(pts[k], pts[k + 1]) for k in range(len(pts) - 1))


def trim_polyline(pts, length: float) -> list[Point]:
    """Prefix of ``pts`` of arc length ``length`` (interpolates last point)."""
    if length <= 0 or len(pts) < 2:
        return [tuple(pts[0])] if pts else []
    out = [tuple(pts[0])]
    acc = 0.0
    for k in range(len(pts) - 1):
        a, b = pts[k], pts[k + 1]
        seg = math.dist(a, b)
        if acc + seg >= length:
            r = (length - acc) / seg if seg else 0.0
            out.append((a[0] + (b[0] - a[0]) * r, a[1] + (b[1] - a[1]) * r))
            return out
        acc += seg
        out.append(tuple(b))
    return out


def dash_state(total: float, progress: float) -> dict:
    """CSS draw-on state: dasharray=L, dashoffset L->0 as progress 0->1."""
    p = min(1.0, max(0.0, progress))
    off = total * (1 - p)
    return {"dasharray": total, "dashoffset": off, "visible": total - off}


# ---------------------------------------------------------------- SVG doc

_Mat = tuple[float, float, float, float, float, float]
_ID: _Mat = (1, 0, 0, 1, 0, 0)


def _mul(m: _Mat, n: _Mat) -> _Mat:
    a, b, c, d, e, f = m
    A, B, C, D, E, F = n
    return (a * A + c * B, b * A + d * B, a * C + c * D, b * C + d * D, a * E + c * F + e, b * E + d * F + f)


def _parse_transform(s: str | None) -> _Mat:
    m = _ID
    for name, args in re.findall(r"(\w+)\s*\(([^)]*)\)", s or ""):
        v = [float(x) for x in re.findall(r"[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?", args)]
        if name == "translate":
            t = (1, 0, 0, 1, v[0], v[1] if len(v) > 1 else 0)
        elif name == "scale":
            t = (v[0], 0, 0, v[1] if len(v) > 1 else v[0], 0, 0)
        elif name == "matrix" and len(v) == 6:
            t = tuple(v)
        elif name == "rotate":
            r = math.radians(v[0]); c, s_ = math.cos(r), math.sin(r)
            t = (c, s_, -s_, c, 0, 0)
            if len(v) == 3:
                t = _mul(_mul((1, 0, 0, 1, v[1], v[2]), t), (1, 0, 0, 1, -v[1], -v[2]))
        else:
            continue
        m = _mul(m, t)
    return m


def _apply(m: _Mat, pts):
    a, b, c, d, e, f = m
    return [(a * x + c * y + e, b * x + d * y + f) for x, y in pts]


def _style(el, inherited: dict) -> dict:
    st = dict(inherited)
    for k in ("stroke", "fill", "stroke-width", "opacity"):
        if el.get(k) is not None:
            st[k] = el.get(k)
    for kv in (el.get("style") or "").split(";"):
        if ":" in kv:
            k, v = kv.split(":", 1)
            st[k.strip()] = v.strip()
    return st


@dataclass
class Shape:
    subpaths: list[tuple[list[Point], bool]]
    stroke: str | None = "#000000"
    fill: str | None = None
    stroke_width: float = 2.0
    id: str | None = None
    length: float = field(init=False)

    def __post_init__(self):
        self.length = sum(polyline_length(p) for p, _ in self.subpaths)


def _f(el, k, dflt=0.0):
    v = el.get(k)
    return float(re.sub(r"[a-z%]+$", "", v)) if v else dflt


def parse_svg(text: str, size: tuple[int, int] | None = None, tol: float = 1.0) -> tuple[list[Shape], tuple[int, int]]:
    """Parse an SVG document into drawable shapes mapped to output pixels."""
    root = ET.fromstring(text)
    vb = [float(x) for x in re.split(r"[ ,]+", (root.get("viewBox") or "").strip()) if x]
    w0 = _f(root, "width", vb[2] if len(vb) == 4 else 512)
    h0 = _f(root, "height", vb[3] if len(vb) == 4 else 512)
    if len(vb) != 4:
        vb = [0, 0, w0, h0]
    W, H = size or (int(round(w0)), int(round(h0)))
    sc = min(W / vb[2], H / vb[3])
    base = (sc, 0, 0, sc, -vb[0] * sc + (W - vb[2] * sc) / 2, -vb[1] * sc + (H - vb[3] * sc) / 2)
    shapes: list[Shape] = []

    def walk(el, m, st):
        tag = el.tag.split("}")[-1]
        m = _mul(m, _parse_transform(el.get("transform")))
        st = _style(el, st)
        subs = None
        if tag == "path":
            subs = parse_path_d(el.get("d", ""), tol=tol / max(sc, 1e-6))
        elif tag == "line":
            subs = [([(_f(el, "x1"), _f(el, "y1")), (_f(el, "x2"), _f(el, "y2"))], False)]
        elif tag in ("polyline", "polygon"):
            v = [float(x) for x in re.findall(r"[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?", el.get("points", ""))]
            pts = list(zip(v[0::2], v[1::2]))
            if tag == "polygon" and pts:
                pts.append(pts[0])
            subs = [(pts, tag == "polygon")]
        elif tag == "rect":
            x, y, w, h = _f(el, "x"), _f(el, "y"), _f(el, "width"), _f(el, "height")
            subs = [([(x, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y)], True)]
        elif tag in ("circle", "ellipse"):
            cx, cy = _f(el, "cx"), _f(el, "cy")
            rx = _f(el, "r") if tag == "circle" else _f(el, "rx")
            ry = _f(el, "r") if tag == "circle" else _f(el, "ry")
            n = max(24, int(2 * math.pi * max(rx, ry) * sc / max(tol, 0.5)))
            # start at 12 o'clock, clockwise -- like browsers draw a circle stroke from 3 o'clock; either is fine
            subs = [([(cx + rx * math.cos(2 * math.pi * k / n), cy + ry * math.sin(2 * math.pi * k / n)) for k in range(n + 1)], True)]
        if subs:
            stroke = st.get("stroke", "none")
            fill = st.get("fill", "#000000")
            shapes.append(Shape(
                [(_apply(m, p), c) for p, c in subs if len(p) >= 2],
                stroke=None if stroke == "none" else stroke,
                fill=None if fill in ("none", "transparent") else fill,
                stroke_width=float(re.sub(r"[a-z]+$", "", str(st.get("stroke-width", "2")))) * sc,
                id=el.get("id"),
            ))
        for ch in el:
            walk(ch, m, st)

    walk(root, base, {})
    return shapes, (W, H)
