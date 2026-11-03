"""Rough-style hand-drawn stroke technique (clean-room, Python side).

This module is an original Python implementation written from the *general
principle* behind sketchy/rough line rendering:

* take the vertices / sampled points of a line or path,
* displace them by a small, controlled random offset (``roughness``),
* displace each segment's midpoint perpendicular to the segment by a
  second controlled offset (``bowing``), so straight lines sag/bulge a
  little the way a hand-drawn line does, and
* draw the result twice with two independent offsets (``double_stroke``),
  which produces the familiar "the pen went over it twice" sketch look.

No code from rough.js (or any other library) is copied or transliterated
here; only the high-level idea above is implemented, in idiomatic Python,
on top of the standard library only.

Web rendering side (not wired up by this module, documented for later):
on a web page you do not need this Python code at all -- you can use the
upstream library directly.  rough.js is MIT-licensed; pin version 4.6.6,
e.g. ``npm install roughjs@4.6.6`` or the jsDelivr CDN build
``https://cdn.jsdelivr.net/npm/roughjs@4.6.6/bundled/rough.js``, then call
``rough.svg(svgEl).rectangle(...)`` / ``rough.canvas(el).line(...)`` with
``{roughness, bowing, seed}`` options.  See ``docs/rules/rough_stroke.md``.

Determinism: every call uses its own ``random.Random`` instance seeded
from the caller's ``seed`` (plus the pass index).  The module never touches
the global RNG, so the same (points, params, seed) always yields exactly
the same output and calling this module cannot perturb other code.

Zero external calls, CPU-only, standard library only.
"""

from __future__ import annotations

import math
import random
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

Point = tuple[float, float]

#: Hard limits keep a stray caller from asking for a stroke displaced so far
#: that the result no longer resembles the input geometry at all.
MAX_ROUGHNESS = 50.0
MAX_BOWING = 50.0


def _validate_scalar(name: str, value: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number, got {type(value).__name__}")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{name} must be finite, got {value!r}")
    if out < 0.0 or out > maximum:
        raise ValueError(f"{name} must be within [0, {maximum}], got {out}")
    return out


def _validate_seed(seed: int) -> int:
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError(f"seed must be an int, got {type(seed).__name__}")
    return int(seed)


def _validate_points(points: Sequence[Sequence[float]]) -> tuple[Point, ...]:
    if points is None:
        raise ValueError("points must not be None")
    pts: list[Point] = []
    try:
        iterator = iter(points)
    except TypeError as exc:
        raise ValueError("points must be an iterable of (x, y) pairs") from exc
    for raw in iterator:
        try:
            x_raw, y_raw = raw  # type: ignore[misc]
        except Exception as exc:
            raise ValueError(f"each point must be an (x, y) pair, got {raw!r}") from exc
        for coord in (x_raw, y_raw):
            if isinstance(coord, bool) or not isinstance(coord, (int, float)):
                raise ValueError(f"point coordinates must be numbers, got {raw!r}")
            if not math.isfinite(float(coord)):
                raise ValueError(f"point coordinates must be finite, got {raw!r}")
        pts.append((float(x_raw), float(y_raw)))
    if len(pts) < 2:
        raise ValueError(f"a polyline needs at least 2 points, got {len(pts)}")
    return tuple(pts)


def points_to_svg_path(
    points: Sequence[Sequence[float]], *, closed: bool = False, precision: int = 3
) -> str:
    """Format a point list as an SVG ``path`` ``d`` string (M/L[/Z])."""
    pts = _validate_points(points)
    if isinstance(precision, bool) or not isinstance(precision, int) or not 0 <= precision <= 9:
        raise ValueError(f"precision must be an int within [0, 9], got {precision!r}")
    fmt = f"{{:.{precision}f}}"
    parts = [f"M {fmt.format(pts[0][0])} {fmt.format(pts[0][1])}"]
    for x, y in pts[1:]:
        parts.append(f"L {fmt.format(x)} {fmt.format(y)}")
    if closed:
        parts.append("Z")
    return " ".join(parts)


@dataclass(frozen=True)
class RoughStrokeResult:
    """One roughened polyline: one point list (pass) per drawn stroke."""

    passes: tuple[tuple[Point, ...], ...]
    svg_paths: tuple[str, ...]
    closed: bool = False

    @property
    def points(self) -> tuple[Point, ...]:
        """The first (primary) pass, as a point list."""
        return self.passes[0]

    @property
    def svg_path(self) -> str:
        """The first (primary) pass, as an SVG path string."""
        return self.svg_paths[0]

    def to_dict(self) -> dict:
        return {
            "passes": [[list(p) for p in one_pass] for one_pass in self.passes],
            "svg_paths": list(self.svg_paths),
            "closed": self.closed,
        }


def _one_pass(
    pts: tuple[Point, ...],
    *,
    roughness: float,
    bowing: float,
    seed: int,
    pass_index: int,
    closed: bool,
) -> tuple[Point, ...]:
    # A dedicated RNG per pass: string seeding of random.Random is stable
    # across runs/processes and independent of the global RNG state.
    rng = random.Random(f"hevi-rough-stroke:{seed}:{pass_index}")
    jittered: list[Point] = [
        (x + rng.uniform(-roughness, roughness), y + rng.uniform(-roughness, roughness))
        for x, y in pts
    ]
    segments: list[tuple[int, int]] = [(i, i + 1) for i in range(len(pts) - 1)]
    if closed:
        segments.append((len(pts) - 1, 0))
    out: list[Point] = [jittered[0]]
    for a_idx, b_idx in segments:
        ax, ay = pts[a_idx]
        bx, by = pts[b_idx]
        dx, dy = bx - ax, by - ay
        length = math.hypot(dx, dy)
        if length > 1e-9 and bowing > 0.0:
            # Segment midpoint, pushed sideways (perpendicular) by a random
            # amount up to ``bowing`` -- this is what makes a straight edge
            # read as hand-drawn rather than ruler-drawn.
            nx, ny = -dy / length, dx / length
            offset = rng.uniform(-bowing, bowing)
            jax, jay = jittered[a_idx]
            jbx, jby = jittered[b_idx]
            out.append(((jax + jbx) / 2 + nx * offset, (jay + jby) / 2 + ny * offset))
        if not closed or b_idx != 0:
            out.append(jittered[b_idx])
    return tuple(out)


def roughen_polyline(
    points: Sequence[Sequence[float]],
    *,
    roughness: float = 1.0,
    bowing: float = 1.0,
    seed: int = 0,
    double_stroke: bool = True,
    closed: bool = False,
) -> RoughStrokeResult:
    """Roughen one polyline / sampled curve.

    Parameters (all in the same coordinate units as ``points``):

    * ``roughness`` -- max random displacement of each vertex.
    * ``bowing`` -- max perpendicular displacement of each segment midpoint.
    * ``seed`` -- int; the same seed always reproduces the same result.
    * ``double_stroke`` -- when true (default), return two independently
      displaced passes, for the double-drawn sketch look.
    * ``closed`` -- treat the polyline as a closed shape (the last segment
      wraps back to the first point).

    With ``roughness == 0`` and ``bowing == 0`` every pass is exactly the
    input polyline -- callers can rely on that as the "off" position.
    """
    pts = _validate_points(points)
    rough = _validate_scalar("roughness", roughness, MAX_ROUGHNESS)
    bow = _validate_scalar("bowing", bowing, MAX_BOWING)
    seed_i = _validate_seed(seed)
    if not isinstance(double_stroke, bool) or not isinstance(closed, bool):
        raise ValueError("double_stroke and closed must be bool")
    n_passes = 2 if double_stroke else 1
    if rough == 0.0 and bow == 0.0:
        passes = tuple(pts for _ in range(n_passes))
    else:
        passes = tuple(
            _one_pass(
                pts,
                roughness=rough,
                bowing=bow,
                seed=seed_i,
                pass_index=i,
                closed=closed,
            )
            for i in range(n_passes)
        )
    svg_paths = tuple(points_to_svg_path(p, closed=closed) for p in passes)
    return RoughStrokeResult(passes=passes, svg_paths=svg_paths, closed=closed)


def roughen_polylines(
    polylines: Iterable[Sequence[Sequence[float]]],
    *,
    roughness: float = 1.0,
    bowing: float = 1.0,
    seed: int = 0,
    double_stroke: bool = True,
    closed: bool = False,
) -> list[RoughStrokeResult]:
    """Roughen several polylines; each gets its own derived seed (seed+index)."""
    seed_i = _validate_seed(seed)
    lines = list(polylines)
    if not lines:
        raise ValueError("polylines must contain at least one polyline")
    return [
        roughen_polyline(
            line,
            roughness=roughness,
            bowing=bowing,
            seed=seed_i + idx,
            double_stroke=double_stroke,
            closed=closed,
        )
        for idx, line in enumerate(lines)
    ]


__all__ = [
    "MAX_BOWING",
    "MAX_ROUGHNESS",
    "Point",
    "RoughStrokeResult",
    "points_to_svg_path",
    "roughen_polyline",
    "roughen_polylines",
]
