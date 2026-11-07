"""oskill: CatmullRom camera paths (pure, deterministic, no I/O).

Control points -> centripetal/uniform/chordal Catmull-Rom curve (same maths as
three.js ``CatmullRomCurve3``) re-parameterised by arc length, so a camera moving
with ``u = ease(t / duration)`` travels at an even speed.  ``lookAt`` defaults to
a point slightly ahead on the curve (``lookahead`` = fraction of curve length);
an optional fixed ``look_at`` target can be blended in.  FOV and roll are linear
keyframes in seconds (optionally smoothstepped).
"""
from __future__ import annotations

import bisect
import math
from typing import Any, Sequence

Vec = tuple[float, float, float]


def _sub(a, b): return (a[0] - b[0], a[1] - b[1], a[2] - b[2])
def _add(a, b): return (a[0] + b[0], a[1] + b[1], a[2] + b[2])
def _mul(a, s): return (a[0] * s, a[1] * s, a[2] * s)
def _len(a): return math.sqrt(a[0] * a[0] + a[1] * a[1] + a[2] * a[2])
def _lerp(a, b, s): return _add(a, _mul(_sub(b, a), s))


class CatmullRom3:
    """Catmull-Rom spline through ``points`` (>=2). ``kind``: centripetal|catmullrom|chordal."""

    def __init__(self, points: Sequence[Sequence[float]], *, closed: bool = False,
                 kind: str = "centripetal", tension: float = 0.5, divisions: int = 400) -> None:
        pts = [tuple(float(c) for c in p) for p in points]
        if len(pts) < 2:
            raise ValueError("camera path needs at least 2 control points")
        if any(len(p) != 3 for p in pts):
            raise ValueError("camera path points must be [x,y,z]")
        if kind not in ("centripetal", "catmullrom", "chordal"):
            raise ValueError(f"unknown curve kind {kind!r}")
        self.points: list[Vec] = pts  # type: ignore[assignment]
        self.closed = bool(closed)
        self.kind = kind
        self.tension = float(tension)
        self._build_lengths(max(16, int(divisions)))

    # -- raw parameter (equal per segment), mirrors three.js getPoint -------- #
    def _point_raw(self, t: float) -> Vec:
        pts, n = self.points, len(self.points)
        p = (n - (0 if self.closed else 1)) * t
        ip = int(math.floor(p))
        w = p - ip
        if self.closed:
            ip += 0 if ip > 0 else (abs(ip) // n + 1) * n
        elif w == 0 and ip == n - 1:
            ip, w = n - 2, 1.0
        if self.closed or ip > 0:
            p0 = pts[(ip - 1) % n]
        else:  # extrapolate first point
            p0 = _sub(_mul(pts[0], 2), pts[1])
        p1 = pts[ip % n]
        p2 = pts[(ip + 1) % n]
        if self.closed or ip + 2 < n:
            p3 = pts[(ip + 2) % n]
        else:
            p3 = _sub(_mul(pts[n - 1], 2), pts[n - 2])
        if self.kind == "catmullrom":
            return _cubic_uniform(p0, p1, p2, p3, w, self.tension)
        pw = 0.25 if self.kind == "centripetal" else 0.5
        dt0 = (_len(_sub(p0, p1)) ** 2) ** pw
        dt1 = (_len(_sub(p1, p2)) ** 2) ** pw
        dt2 = (_len(_sub(p2, p3)) ** 2) ** pw
        if dt1 < 1e-4: dt1 = 1.0
        if dt0 < 1e-4: dt0 = dt1
        if dt2 < 1e-4: dt2 = dt1
        return _cubic_nonuniform(p0, p1, p2, p3, dt0, dt1, dt2, w)

    def _build_lengths(self, div: int) -> None:
        self._div = div
        acc, last = [0.0], self._point_raw(0.0)
        for i in range(1, div + 1):
            cur = self._point_raw(i / div)
            acc.append(acc[-1] + _len(_sub(cur, last)))
            last = cur
        self._acc = acc
        self.length = acc[-1]

    def _u_to_t(self, u: float) -> float:
        u = min(1.0, max(0.0, u))
        target = u * self.length
        acc = self._acc
        i = bisect.bisect_left(acc, target)
        if i <= 0:
            return 0.0
        if i > self._div:
            return 1.0
        seg = acc[i] - acc[i - 1]
        frac = 0.0 if seg <= 0 else (target - acc[i - 1]) / seg
        return (i - 1 + frac) / self._div

    def point_at(self, u: float) -> Vec:
        """Point at arc-length fraction ``u`` in [0,1] (wraps when closed)."""
        if self.closed:
            u = u % 1.0
        return self._point_raw(self._u_to_t(u))

    def tangent_at(self, u: float, eps: float = 1e-3) -> Vec:
        a = self.point_at(max(0.0, u - eps) if not self.closed else u - eps)
        b = self.point_at(min(1.0, u + eps) if not self.closed else u + eps)
        d = _sub(b, a)
        l = _len(d) or 1.0
        return _mul(d, 1.0 / l)

    def ahead(self, u: float, lookahead: float) -> Vec:
        """Point ``lookahead`` (curve-length fraction) ahead; extrapolates past the end."""
        if self.closed or u + lookahead <= 1.0:
            return self.point_at(u + lookahead)
        end = self.point_at(1.0)
        over = (u + lookahead - 1.0) * max(self.length, 1e-6)
        return _add(end, _mul(self.tangent_at(1.0), over))


def _cubic_uniform(p0, p1, p2, p3, w, tension):
    out = []
    for i in range(3):
        x0, x1, x2, x3 = p0[i], p1[i], p2[i], p3[i]
        t0 = tension * (x2 - x0)
        t1 = tension * (x3 - x1)
        c0, c1 = x1, t0
        c2 = -3 * x1 + 3 * x2 - 2 * t0 - t1
        c3 = 2 * x1 - 2 * x2 + t0 + t1
        out.append(c0 + c1 * w + c2 * w * w + c3 * w * w * w)
    return tuple(out)


def _cubic_nonuniform(p0, p1, p2, p3, dt0, dt1, dt2, w):
    out = []
    for i in range(3):
        x0, x1, x2, x3 = p0[i], p1[i], p2[i], p3[i]
        t1 = (x1 - x0) / dt0 - (x2 - x0) / (dt0 + dt1) + (x2 - x1) / dt1
        t2 = (x2 - x1) / dt1 - (x3 - x1) / (dt1 + dt2) + (x3 - x2) / dt2
        t1 *= dt1
        t2 *= dt1
        c0, c1 = x1, t1
        c2 = -3 * x1 + 3 * x2 - 2 * t1 - t2
        c3 = 2 * x1 - 2 * x2 + t1 + t2
        out.append(c0 + c1 * w + c2 * w * w + c3 * w * w * w)
    return tuple(out)


EASES = {
    "linear": lambda x: x,
    "in_out": lambda x: x * x * (3 - 2 * x),
    "in": lambda x: x * x,
    "out": lambda x: 1 - (1 - x) * (1 - x),
}


def interp_keys(keys: Sequence[dict[str, Any]], t: float, field: str, default: float) -> float:
    """Piecewise-linear (or ``ease: in_out`` per key) interpolation of ``{t, field}`` keys."""
    if not keys:
        return float(default)
    ks = sorted(keys, key=lambda k: float(k["t"]))
    if t <= float(ks[0]["t"]):
        return float(ks[0][field])
    if t >= float(ks[-1]["t"]):
        return float(ks[-1][field])
    for a, b in zip(ks, ks[1:]):
        ta, tb = float(a["t"]), float(b["t"])
        if ta <= t <= tb:
            s = 0.0 if tb == ta else (t - ta) / (tb - ta)
            s = EASES.get(str(b.get("ease", "linear")), EASES["linear"])(s)
            return float(a[field]) + (float(b[field]) - float(a[field])) * s
    return float(ks[-1][field])  # pragma: no cover


def sample_camera(cam: dict[str, Any], curve: CatmullRom3, t: float, duration: float) -> dict[str, Any]:
    path = cam["path"]
    x = 0.0 if duration <= 0 else min(1.0, max(0.0, t / duration))
    u0, u1 = float(path.get("u_start", 0.0)), float(path.get("u_end", 1.0))
    u = u0 + (u1 - u0) * EASES[path.get("ease", "linear")](x)
    pos = curve.point_at(u)
    look = curve.ahead(u, float(path.get("lookahead", 0.03)))
    target = path.get("look_at")
    if target is not None:
        blend = float(path.get("look_at_blend", 1.0))
        look = _lerp(look, tuple(float(c) for c in target), blend)
    if _len(_sub(look, pos)) < 1e-6:  # never lookAt self
        look = _add(pos, curve.tangent_at(u))
    fov = interp_keys(cam.get("fov_keys", []), t, "fov", cam.get("fov", 50.0))
    roll = interp_keys(cam.get("roll_keys", []), t, "deg", 0.0)
    r = lambda v: [round(c, 5) for c in v]
    return {"t": round(t, 6), "u": round(u, 6), "pos": r(pos), "look": r(look),
            "fov": round(fov, 4), "roll_deg": round(roll, 4)}


def frame_times(duration: float, fps: int) -> list[float]:
    n = max(1, math.ceil(duration * fps))
    ts = [i / fps for i in range(n)]
    if n > 1:
        ts[-1] = float(duration)
    return ts


def bake_camera(cam: dict[str, Any], duration: float, fps: int) -> list[dict[str, Any]]:
    """Return one camera state per output frame (deterministic)."""
    path = cam["path"]
    curve = CatmullRom3(path["points"], closed=bool(path.get("closed", False)),
                        kind=path.get("curve", "centripetal"), tension=float(path.get("tension", 0.5)))
    return [sample_camera(cam, curve, t, duration) for t in frame_times(duration, fps)]
