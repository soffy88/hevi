"""Field primitives for the brush engine: composable painting regions.

Each primitive is a small pure function of normalised canvas position
(u, v in 0..1) answering "what colour / direction / timing lives here".
Primitives know nothing about pixels, RNG streams or files; randomness
they need comes from the deterministic coordinate hash, so a primitive's
answer never depends on which other layers were sampled before it.

Implemented regions: swirl sky, moon (ring field), stars (ring field),
hills, water with a reflected light column, cypress, tree, house,
meadow, clouds.  All parameter names and defaults are this package's
own design, tuned for stylised storybook scenes.
"""

from __future__ import annotations

import math
from typing import Any, Sequence

from .engine import Cell, SeededRng, hash2, hex_to_rgb, lerp_rgb, palette_at


class SpecError(ValueError):
    """A scene spec / primitive parameter problem (never a fake paint)."""


def _req(params: dict[str, Any], key: str, owner: str) -> Any:
    if key not in params or params[key] is None:
        raise SpecError(f"{owner}: missing required parameter {key!r}")
    return params[key]


def _palette(params: dict[str, Any], key: str, owner: str) -> tuple[tuple[int, int, int], ...]:
    raw = _req(params, key, owner)
    if not isinstance(raw, (list, tuple)) or not raw:
        raise SpecError(f"{owner}: {key!r} must be a non-empty list of #rrggbb colours")
    try:
        return tuple(hex_to_rgb(c) for c in raw)
    except ValueError as exc:
        raise SpecError(f"{owner}: {exc}") from exc


def _num(params: dict[str, Any], key: str, default: float, owner: str) -> float:
    value = params.get(key, default)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise SpecError(f"{owner}: {key!r} must be a number")
    return float(value)


def _tint(rgb: tuple[int, int, int], factor: float) -> tuple[int, int, int]:
    return tuple(max(0, min(255, round(c * factor))) for c in rgb)


class _AspectAware:
    """Mixin: ``bind`` receives the canvas aspect (width/height) so
    distance tests can run in pixel-proportional space."""

    aspect: float = 1.0

    def bind(self, aspect: float) -> None:
        self.aspect = float(aspect)


class SwirlSky(_AspectAware):
    """Open sky: a slow rightward flow bent by vortex centres.

    The stroke direction is the local flow direction; colour walks the
    palette from top (v=0) to the horizon.
    """

    def __init__(self, params: dict[str, Any]) -> None:
        owner = "swirl_sky"
        self.palette = _palette(params, "palette", owner)
        self.horizon = _num(params, "horizon", 1.0, owner)
        if not 0.0 < self.horizon <= 1.5:
            raise SpecError(f"{owner}: horizon must be in (0, 1.5]")
        self.base_flow = _num(params, "base_flow", 0.55, owner)
        self.wave = _num(params, "wave", 0.45, owner)
        self.sway = _num(params, "sway", 2.0, owner)
        self.vortices: list[tuple[float, float, float, float]] = []
        for i, raw in enumerate(params.get("vortices", []) or []):
            if not isinstance(raw, dict):
                raise SpecError(f"{owner}: vortices[{i}] must be an object")
            self.vortices.append(
                (
                    _num(raw, "x", 0.5, owner),
                    _num(raw, "y", 0.3, owner),
                    max(0.02, _num(raw, "r", 0.18, owner)),
                    _num(raw, "s", 1.5, owner),
                )
            )

    def cell(self, u: float, v: float) -> Cell | None:
        if v > self.horizon:
            return None
        vx = self.base_flow
        vy = math.sin(u * 8.0 + v * 3.0) * self.wave * 0.35
        for cx, cy, r, s in self.vortices:
            dx, dy = (u - cx) * self.aspect, v - cy
            d = math.hypot(dx, dy) + 1e-4
            k = s * math.exp(-d / r)
            vx += (-dy / d) * k
            vy += (dx / d) * k
        t = min(1.0, v / self.horizon) if self.horizon else 1.0
        base = palette_at(self.palette, t)
        colors = (base, _tint(base, 0.88), _tint(base, 1.1))
        return Cell(
            colors=colors,
            angle=math.atan2(vy, vx),
            len_factor=2.1,
            wid_factor=0.6,
            order=t * 0.85,
            sway=self.sway,
        )


class Moon(_AspectAware):
    """A moon disc with a tangential (ring) stroke field plus halo."""

    def __init__(self, params: dict[str, Any]) -> None:
        owner = "moon"
        self.x = _num(params, "x", 0.78, owner)
        self.y = _num(params, "y", 0.16, owner)
        self.r = max(0.01, _num(params, "r", 0.07, owner))
        self.palette = _palette(params, "palette", owner) if "palette" in params else (
            (247, 215, 116),
            (251, 233, 160),
            (255, 243, 192),
        )
        self.halo_palette = (
            _palette(params, "halo_palette", owner)
            if "halo_palette" in params
            else ((207, 224, 240), (156, 192, 230), (242, 230, 160))
        )
        self.sway = _num(params, "sway", 1.0, owner)

    def cell(self, u: float, v: float) -> Cell | None:
        dx = (u - self.x) * self.aspect
        dy = v - self.y
        d = math.hypot(dx, dy)
        ring_angle = math.atan2(dy, dx) + math.pi / 2.0
        if d < self.r:
            t = d / self.r
            base = palette_at(self.palette, t)
            return Cell(
                colors=(base, _tint(base, 0.92)),
                angle=ring_angle,
                len_factor=1.4,
                wid_factor=0.62,
                order=0.25 + 0.4 * t,
                sway=self.sway,
            )
        if d < self.r * 1.9:
            t = (d - self.r) / (self.r * 0.9)
            base = palette_at(self.halo_palette, t)
            return Cell(
                colors=(base,),
                angle=ring_angle,
                len_factor=1.7,
                wid_factor=0.55,
                order=0.2 + 0.4 * t,
                sway=self.sway * 1.3,
            )
        return None


class Stars(_AspectAware):
    """Small ring-field stars scattered by a seeded generator."""

    def __init__(self, params: dict[str, Any]) -> None:
        owner = "stars"
        self.sway = _num(params, "sway", 1.1, owner)
        raw_points = params.get("points")
        self.points: list[tuple[float, float, float]] = []
        if raw_points:
            for i, p in enumerate(raw_points):
                if not isinstance(p, dict):
                    raise SpecError(f"{owner}: points[{i}] must be an object")
                self.points.append(
                    (
                        _num(p, "x", 0.5, owner),
                        _num(p, "y", 0.2, owner),
                        max(0.006, _num(p, "r", 0.03, owner)),
                    )
                )
        else:
            count = int(_num(params, "count", 9, owner))
            region = params.get("region", {}) or {}
            x0 = _num(region, "x0", 0.04, owner)
            x1 = _num(region, "x1", 0.96, owner)
            y0 = _num(region, "y0", 0.04, owner)
            y1 = _num(region, "y1", 0.45, owner)
            r_min = _num(params, "r_min", 0.018, owner)
            r_max = max(r_min, _num(params, "r_max", 0.042, owner))
            rng = SeededRng(int(_num(params, "seed", 1234, owner)))
            for _ in range(max(0, count)):
                self.points.append(
                    (
                        rng.uniform(x0, x1),
                        rng.uniform(y0, y1),
                        rng.uniform(r_min, r_max),
                    )
                )
        self.core = ((255, 247, 194), (247, 215, 116), (255, 255, 255))
        self.halo = ((207, 224, 240), (156, 192, 230), (243, 198, 63))

    def cell(self, u: float, v: float) -> Cell | None:
        for cx, cy, r in self.points:
            dx = (u - cx) * self.aspect
            dy = v - cy
            d = math.hypot(dx, dy)
            if d < r * 1.7:
                ring = math.atan2(dy, dx) + math.pi / 2.0
                if d < r * 0.55:
                    return Cell(colors=self.core, angle=ring, len_factor=1.0,
                                wid_factor=0.6, order=0.3, sway=self.sway)
                if d < r:
                    return Cell(colors=self.halo, angle=ring, len_factor=1.3,
                                wid_factor=0.55, order=0.32, sway=self.sway)
                return Cell(colors=self.halo[1:], angle=ring, len_factor=1.6,
                            wid_factor=0.5, order=0.34, sway=self.sway * 1.2)
        return None


class Hills:
    """Rolling hill silhouette: everything below a sine-sum ridgeline."""

    def __init__(self, params: dict[str, Any]) -> None:
        owner = "hills"
        self.base = _num(params, "base", 0.58, owner)
        self.amp = _num(params, "amp", 0.035, owner)
        self.freq = _num(params, "freq", 1.6, owner)
        self.phase = _num(params, "phase", 0.7, owner)
        self.palette = _palette(params, "palette", owner)
        self.sway = _num(params, "sway", 0.0, owner)

    def ridge(self, u: float) -> float:
        return (
            self.base
            + self.amp * math.sin(u * self.freq * math.tau + self.phase)
            + self.amp * 0.4 * math.sin(u * self.freq * 2.7 * math.tau + self.phase * 2.0)
        )

    def cell(self, u: float, v: float) -> Cell | None:
        ridge = self.ridge(u)
        if v < ridge:
            return None
        depth = min(1.0, (v - ridge) / 0.35)
        slope = (self.ridge(u + 0.01) - self.ridge(u - 0.01)) / 0.02
        base = palette_at(self.palette, depth)
        return Cell(
            colors=(base, _tint(base, 0.9), _tint(base, 1.08)),
            angle=math.atan(slope * 0.6),
            len_factor=1.9,
            wid_factor=0.6,
            order=0.15 + 0.7 * depth,
            sway=self.sway,
        )


class Water:
    """Water band with horizontal strokes and an optional reflected
    light column (moonlight glitter) under ``reflect_x``."""

    def __init__(self, params: dict[str, Any]) -> None:
        owner = "water"
        self.from_y = _num(params, "from", 0.66, owner)
        self.palette = _palette(params, "palette", owner)
        self.reflect_x = params.get("reflect_x")
        if self.reflect_x is not None:
            self.reflect_x = _num(params, "reflect_x", 0.7, owner)
        self.reflect_width = max(0.005, _num(params, "reflect_width", 0.045, owner))
        self.glitter = (
            _palette(params, "glitter_palette", owner)
            if "glitter_palette" in params
            else ((247, 216, 106), (255, 243, 192), (207, 224, 240))
        )
        self.sway = _num(params, "sway", 1.6, owner)

    def cell(self, u: float, v: float) -> Cell | None:
        if v < self.from_y:
            return None
        depth = min(1.0, (v - self.from_y) / max(0.05, 1.0 - self.from_y))
        if self.reflect_x is not None:
            dx = abs(u - self.reflect_x)
            wobble = 0.012 * math.sin(v * 40.0)
            if dx < self.reflect_width * (1.0 + 0.7 * depth) + wobble * 0.3:
                if hash2(u * 91.0, v * 57.0) < 0.62:
                    return Cell(
                        colors=self.glitter,
                        angle=0.05 * math.sin(v * 30.0),
                        len_factor=1.5,
                        wid_factor=0.5,
                        order=0.3 + 0.6 * depth,
                        sway=self.sway * 1.4,
                    )
        base = palette_at(self.palette, depth)
        return Cell(
            colors=(base, _tint(base, 0.9), _tint(base, 1.12)),
            angle=0.06 * math.sin(u * 20.0 + v * 26.0),
            len_factor=2.0,
            wid_factor=0.55,
            order=0.25 + 0.65 * depth,
            sway=self.sway,
        )


class Cypress:
    """Flame-shaped dark tree (cypress): narrow at the top, swelling
    then tapering to the ground line, strokes pointing up."""

    def __init__(self, params: dict[str, Any]) -> None:
        owner = "cypress"
        self.x = _num(params, "x", 0.16, owner)
        self.base_y = _num(params, "base", 0.68, owner)
        self.height = max(0.05, _num(params, "height", 0.5, owner))
        self.width = max(0.01, _num(params, "width", 0.075, owner))
        self.bend = _num(params, "bend", 0.02, owner)
        self.palette = _palette(params, "palette", owner)
        self.sway = _num(params, "sway", 0.8, owner)

    def cell(self, u: float, v: float) -> Cell | None:
        t = (self.base_y - v) / self.height  # 0 at ground, 1 at tip
        if t < 0.0 or t > 1.0:
            return None
        cx = self.x + self.bend * math.sin(t * 2.2)
        half = self.width * (math.sin(math.pi * min(1.0, 0.15 + t * 0.95)) ** 0.7) * (1.0 - 0.35 * t)
        if abs(u - cx) > half:
            return None
        base = palette_at(self.palette, 1.0 - t)
        return Cell(
            colors=(base, _tint(base, 0.85), _tint(base, 1.12)),
            angle=-math.pi / 2.0 + 0.45 * math.sin(v * 22.0 + u * 12.0),
            len_factor=2.2,
            wid_factor=0.6,
            order=0.35 + 0.55 * t,
            sway=self.sway * t,
        )


class Tree(_AspectAware):
    """Round-canopy tree with a short trunk."""

    def __init__(self, params: dict[str, Any]) -> None:
        owner = "tree"
        self.x = _num(params, "x", 0.3, owner)
        self.base_y = _num(params, "base", 0.85, owner)
        self.canopy_r = max(0.02, _num(params, "canopy_r", 0.11, owner))
        self.canopy_y = self.base_y - _num(params, "canopy_h", 0.22, owner)
        self.palette = _palette(params, "palette", owner)
        self.trunk = (
            _palette(params, "trunk_palette", owner)
            if "trunk_palette" in params
            else ((92, 64, 44), (110, 80, 52))
        )
        self.sway = _num(params, "sway", 0.7, owner)

    def cell(self, u: float, v: float) -> Cell | None:
        dx = (u - self.x) * self.aspect
        dy = v - self.canopy_y
        d = math.hypot(dx, dy)
        if d < self.canopy_r:
            t = d / self.canopy_r
            base = palette_at(self.palette, t)
            angle = math.atan2(dy, dx) + math.pi / 2.0
            return Cell(
                colors=(base, _tint(base, 0.88), _tint(base, 1.14)),
                angle=angle + 0.5 * (hash2(u * 51.0, v * 51.0) - 0.5),
                len_factor=1.5,
                wid_factor=0.6,
                order=0.4 + 0.4 * (1.0 - t),
                sway=self.sway,
            )
        trunk_half = self.canopy_r * 0.2
        if abs(u - self.x) < trunk_half and self.canopy_y < v <= self.base_y:
            return Cell(
                colors=self.trunk,
                angle=math.pi / 2.0,
                len_factor=1.8,
                wid_factor=0.7,
                order=0.3,
                sway=0.0,
            )
        return None


class House:
    """Simple house: rectangular walls, pitched roof, lit windows."""

    def __init__(self, params: dict[str, Any]) -> None:
        owner = "house"
        self.x = _num(params, "x", 0.65, owner)
        self.base_y = _num(params, "base", 0.72, owner)
        self.w = max(0.03, _num(params, "w", 0.17, owner))
        self.h = max(0.03, _num(params, "h", 0.11, owner))
        self.roof_h = max(0.01, _num(params, "roof_h", 0.055, owner))
        self.walls = _palette(params, "wall_palette", owner)
        self.roof = _palette(params, "roof_palette", owner)
        self.lit = (
            _palette(params, "window_palette", owner)
            if "window_palette" in params
            else ((255, 196, 86), (255, 222, 140))
        )
        self.sway = _num(params, "sway", 0.0, owner)

    def _in_window(self, u: float, v: float) -> bool:
        # Two windows on the wall face, positioned in relative coords.
        rx = (u - (self.x - self.w / 2.0)) / self.w
        ry = (v - (self.base_y - self.h)) / self.h
        for wx in (0.2, 0.62):
            if wx <= rx <= wx + 0.19 and 0.28 <= ry <= 0.66:
                return True
        return False

    def cell(self, u: float, v: float) -> Cell | None:
        x0, x1 = self.x - self.w / 2.0, self.x + self.w / 2.0
        wall_top = self.base_y - self.h
        roof_top = wall_top - self.roof_h
        if wall_top <= v <= self.base_y and x0 <= u <= x1:
            if self._in_window(u, v):
                return Cell(colors=self.lit, angle=0.0, len_factor=0.95,
                            wid_factor=0.72, order=0.85, sway=0.0)
            base = palette_at(self.walls, (v - wall_top) / self.h)
            return Cell(
                colors=(base, _tint(base, 0.92)),
                angle=0.0,
                len_factor=1.7,
                wid_factor=0.6,
                order=0.55 + 0.3 * ((v - wall_top) / self.h),
                sway=self.sway,
            )
        if roof_top <= v < wall_top:
            t = (v - roof_top) / self.roof_h  # 0 at ridge, 1 at eaves
            half = (self.w / 2.0) * t * 1.12
            if abs(u - self.x) <= half:
                side = 1.0 if u >= self.x else -1.0
                slope = math.atan2(self.roof_h, self.w / 2.0) * side
                base = palette_at(self.roof, t)
                return Cell(
                    colors=(base, _tint(base, 0.9)),
                    angle=slope,
                    len_factor=1.8,
                    wid_factor=0.72,
                    order=0.5 + 0.3 * t,
                    sway=self.sway,
                )
        return None


class Meadow:
    """Foreground meadow band: short upright strokes, sparse flowers."""

    def __init__(self, params: dict[str, Any]) -> None:
        owner = "meadow"
        self.from_y = _num(params, "from", 0.86, owner)
        self.palette = _palette(params, "palette", owner)
        self.flowers = (
            _palette(params, "flower_palette", owner)
            if "flower_palette" in params
            else ((255, 214, 231), (255, 236, 170), (255, 255, 255), (244, 160, 190))
        )
        self.flower_density = _num(params, "flower_density", 0.06, owner)
        self.sway = _num(params, "sway", 0.9, owner)

    def cell(self, u: float, v: float) -> Cell | None:
        if v < self.from_y:
            return None
        depth = min(1.0, (v - self.from_y) / max(0.04, 1.0 - self.from_y))
        if hash2(u * 131.0, v * 97.0) < self.flower_density:
            return Cell(
                colors=self.flowers,
                angle=-math.pi / 2.0,
                len_factor=0.55,
                wid_factor=0.55,
                order=0.9,
                sway=self.sway,
            )
        base = palette_at(self.palette, depth)
        return Cell(
            colors=(base, _tint(base, 0.9), _tint(base, 1.12)),
            angle=-math.pi / 2.0 + 0.55 * (hash2(u * 71.0, v * 71.0) - 0.5),
            len_factor=1.0 + 0.5 * depth,
            wid_factor=0.5,
            order=0.55 + 0.4 * depth,
            sway=self.sway,
        )


class Clouds:
    """Soft horizontal cloud blobs (ellipses), slowly drifting."""

    def __init__(self, params: dict[str, Any]) -> None:
        owner = "clouds"
        self.palette = _palette(params, "palette", owner)
        self.sway = _num(params, "sway", 2.4, owner)
        self.blobs: list[tuple[float, float, float, float]] = []
        raw = params.get("blobs") or [
            {"x": 0.3, "y": 0.14, "rx": 0.16, "ry": 0.035},
            {"x": 0.68, "y": 0.24, "rx": 0.2, "ry": 0.045},
        ]
        for i, b in enumerate(raw):
            if not isinstance(b, dict):
                raise SpecError(f"{owner}: blobs[{i}] must be an object")
            self.blobs.append(
                (
                    _num(b, "x", 0.4, owner),
                    _num(b, "y", 0.15, owner),
                    max(0.02, _num(b, "rx", 0.16, owner)),
                    max(0.008, _num(b, "ry", 0.04, owner)),
                )
            )

    def cell(self, u: float, v: float) -> Cell | None:
        for cx, cy, rx, ry in self.blobs:
            d = math.hypot((u - cx) / rx, (v - cy) / ry)
            if d < 1.0:
                base = palette_at(self.palette, d)
                return Cell(
                    colors=(base, _tint(base, 0.94)),
                    angle=0.08 * math.sin(u * 14.0),
                    len_factor=2.2,
                    wid_factor=0.6,
                    order=0.2 + 0.3 * d,
                    sway=self.sway,
                )
        return None


PRIMITIVES: dict[str, type] = {
    "swirl_sky": SwirlSky,
    "moon": Moon,
    "stars": Stars,
    "hills": Hills,
    "water": Water,
    "cypress": Cypress,
    "tree": Tree,
    "house": House,
    "meadow": Meadow,
    "clouds": Clouds,
}
