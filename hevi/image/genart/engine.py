"""Seeded generative-art engine (flow fields + Julia fractals).

Original, offline, CPU-only implementation of the algorithmic-art
ideas popularised by Anthropic's ``algorithmic-art`` skill (p5.js,
Apache-2.0; archived under ``~/workspace/references/algorithmic-art``):
an aesthetic is expressed as a seeded algorithm, and the same
``(spec, seed)`` always produces the same artefact.  No JS, no CDN,
no network: everything here is numpy + PIL, deterministic per spec.

Two algorithms:

* ``flowfield`` -- particles advected through a static, multi-octave
  value-noise flow field, leaving coloured trails.  The field is
  deliberately static and particle ages wrap on a lifetime that
  divides the frame count, so video loops are *exactly* seamless
  (frame ``F`` is byte-identical to frame ``0``).
* ``julia`` -- escape-time Julia-set fractal.  For video the constant
  ``c`` orbits a small circle with the loop period, so the first and
  last frames coincide (up to float noise in ``sin(2*pi)``).

Public surface: :func:`parse_spec`, :class:`GenartSpec`,
:class:`SpecError`, :func:`resolve_palette`, :data:`PALETTES`,
:func:`simulate_flowfield`, :func:`julia_mu`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np

__all__ = [
    "GenartSpec",
    "Palette",
    "SpecError",
    "PALETTES",
    "julia_mu",
    "parse_spec",
    "resolve_palette",
    "simulate_flowfield",
]


class SpecError(ValueError):
    """Raised when a generative-art spec is malformed or out of bounds."""


# ---------------------------------------------------------------------------
# Palettes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Palette:
    """A background colour plus gradient stops ``(pos, (r, g, b))``."""

    name: str
    background: tuple[int, int, int]
    stops: tuple[tuple[float, tuple[int, int, int]], ...]

    def lut(self, n: int = 1024) -> np.ndarray:
        """Return an ``(n, 3)`` float32 lookup table over t in [0, 1]."""
        pos = np.array([s[0] for s in self.stops], dtype=np.float64)
        cols = np.array([s[1] for s in self.stops], dtype=np.float64)
        t = np.linspace(0.0, 1.0, n)
        out = np.stack(
            [np.interp(t, pos, cols[:, ch]) for ch in range(3)], axis=1
        )
        return out.astype(np.float32)

    def color_at(self, t: float) -> tuple[float, float, float]:
        """Interpolated colour at ``t`` as floats in [0, 255]."""
        stops = self.stops
        if t <= stops[0][0]:
            return tuple(float(c) for c in stops[0][1])
        for (p0, c0), (p1, c1) in zip(stops, stops[1:]):
            if t <= p1:
                f = 0.0 if p1 == p0 else (t - p0) / (p1 - p0)
                return tuple(
                    float(c0[ch] + (c1[ch] - c0[ch]) * f) for ch in range(3)
                )
        return tuple(float(c) for c in stops[-1][1])


def _hex(value: str) -> tuple[int, int, int]:
    s = str(value).strip().lstrip("#")
    if len(s) != 6:
        raise SpecError(f"colour {value!r} is not a 6-digit hex value")
    try:
        return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
    except ValueError as exc:
        raise SpecError(f"colour {value!r} is not valid hex") from exc


PALETTES: dict[str, Palette] = {
    "ember": Palette(
        name="ember",
        background=(10, 6, 8),
        stops=(
            (0.0, (38, 8, 16)),
            (0.35, (146, 26, 24)),
            (0.62, (232, 92, 30)),
            (0.82, (250, 172, 62)),
            (1.0, (255, 232, 168)),
        ),
    ),
    "abyss": Palette(
        name="abyss",
        background=(4, 8, 18),
        stops=(
            (0.0, (10, 24, 64)),
            (0.35, (12, 84, 124)),
            (0.62, (16, 168, 168)),
            (0.82, (96, 220, 210)),
            (1.0, (214, 255, 246)),
        ),
    ),
    "sakura": Palette(
        name="sakura",
        background=(14, 8, 16),
        stops=(
            (0.0, (52, 20, 62)),
            (0.35, (128, 44, 104)),
            (0.62, (216, 92, 148)),
            (0.82, (248, 168, 196)),
            (1.0, (255, 240, 244)),
        ),
    ),
    "verdant": Palette(
        name="verdant",
        background=(6, 12, 8),
        stops=(
            (0.0, (12, 44, 28)),
            (0.35, (20, 104, 52)),
            (0.62, (74, 184, 84)),
            (0.82, (168, 224, 110)),
            (1.0, (244, 255, 196)),
        ),
    ),
}


def resolve_palette(value: Any) -> Palette:
    """Resolve a palette name or a custom stop list into a Palette."""
    if value is None:
        return PALETTES["abyss"]
    if isinstance(value, str):
        pal = PALETTES.get(value.strip().lower())
        if pal is None:
            raise SpecError(
                f"unknown palette {value!r} (have: {', '.join(sorted(PALETTES))})"
            )
        return pal
    if isinstance(value, (list, tuple)):
        if len(value) < 2:
            raise SpecError("custom palette needs at least 2 colours")
        cols = [_hex(v) for v in value]
        stops = tuple(
            (i / (len(cols) - 1), cols[i]) for i in range(len(cols))
        )
        return Palette(name="custom", background=(6, 6, 10), stops=stops)
    raise SpecError(f"palette must be a name or a list of hex colours, got {value!r}")


# ---------------------------------------------------------------------------
# Spec
# ---------------------------------------------------------------------------

_ALGORITHMS = ("flowfield", "julia")
_SPEC_KEYS = {
    "algorithm",
    "seed",
    "palette",
    "colors",
    "width",
    "height",
    "particle_count",
    "particle_life",
    "step_size",
    "noise_cells",
    "angle_turns",
    "trail",
    "julia_c",
    "orbit_radius",
    "max_iter",
    "exposure",
}


@dataclass(frozen=True)
class GenartSpec:
    algorithm: str = "flowfield"
    seed: int = 7
    palette: Palette = PALETTES["abyss"]
    width: int = 1280
    height: int = 720
    # flowfield
    particle_count: int = 1600
    particle_life: int = 220  # advection steps per particle life
    step_size: float = 2.0  # pixels per step
    noise_cells: float = 3.0  # base noise cells across the width
    angle_turns: float = 1.6  # field swirl strength (in full turns)
    trail: int = 28  # trail length (steps) drawn per video frame
    # julia
    julia_c: complex = complex(-0.7, 0.27015)
    orbit_radius: float = 0.012
    max_iter: int = 90
    # shared
    exposure: float = 1.15


def _int(raw: dict, key: str, default: int, lo: int, hi: int) -> int:
    v = raw.get(key, default)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise SpecError(f"{key} must be an integer, got {v!r}")
    v = int(v)
    if not lo <= v <= hi:
        raise SpecError(f"{key}={v} out of range [{lo}, {hi}]")
    return v


def _float(raw: dict, key: str, default: float, lo: float, hi: float) -> float:
    v = raw.get(key, default)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise SpecError(f"{key} must be a number, got {v!r}")
    v = float(v)
    if not lo <= v <= hi:
        raise SpecError(f"{key}={v} out of range [{lo}, {hi}]")
    return v


def parse_spec(raw: dict[str, Any] | None) -> GenartSpec:
    """Validate a raw spec dict into a :class:`GenartSpec`.

    Unknown keys are rejected so a typo can never silently pass --
    the capability contract forbids fake success.
    """
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise SpecError(f"spec must be an object, got {type(raw).__name__}")
    unknown = sorted(set(raw) - _SPEC_KEYS)
    if unknown:
        raise SpecError(f"unknown spec keys: {', '.join(unknown)}")

    algorithm = str(raw.get("algorithm", "flowfield")).strip().lower()
    if algorithm not in _ALGORITHMS:
        raise SpecError(
            f"algorithm must be one of {_ALGORITHMS}, got {algorithm!r}"
        )

    palette_value = raw.get("colors", raw.get("palette"))
    palette = resolve_palette(palette_value)

    julia_c = complex(-0.7, 0.27015)
    if "julia_c" in raw:
        jc = raw["julia_c"]
        if isinstance(jc, (list, tuple)) and len(jc) == 2:
            julia_c = complex(float(jc[0]), float(jc[1]))
        elif isinstance(jc, dict) and "re" in jc and "im" in jc:
            julia_c = complex(float(jc["re"]), float(jc["im"]))
        else:
            raise SpecError("julia_c must be [re, im] or {re, im}")

    return GenartSpec(
        algorithm=algorithm,
        seed=_int(raw, "seed", 7, -2**31, 2**31 - 1),
        palette=palette,
        width=_int(raw, "width", 1280, 64, 3840),
        height=_int(raw, "height", 720, 64, 3840),
        particle_count=_int(raw, "particle_count", 1600, 10, 20000),
        particle_life=_int(raw, "particle_life", 220, 8, 4000),
        step_size=_float(raw, "step_size", 2.0, 0.2, 20.0),
        noise_cells=_float(raw, "noise_cells", 3.0, 0.5, 16.0),
        angle_turns=_float(raw, "angle_turns", 1.6, 0.1, 6.0),
        trail=_int(raw, "trail", 28, 1, 512),
        julia_c=julia_c,
        orbit_radius=_float(raw, "orbit_radius", 0.012, 0.0, 0.2),
        max_iter=_int(raw, "max_iter", 90, 8, 2000),
        exposure=_float(raw, "exposure", 1.15, 0.1, 8.0),
    )


# ---------------------------------------------------------------------------
# Seeded value noise (periodic lattices -> tileable, platform-stable stream)
# ---------------------------------------------------------------------------


def _sample_lattice(values: np.ndarray, xs: np.ndarray, ys: np.ndarray) -> np.ndarray:
    """Smoothstep-bilinear sample of a periodic lattice at cell coords."""
    gh, gw = values.shape
    x0 = np.floor(xs).astype(np.int64)
    y0 = np.floor(ys).astype(np.int64)
    fx = xs - x0
    fy = ys - y0
    sx = fx * fx * (3.0 - 2.0 * fx)
    sy = fy * fy * (3.0 - 2.0 * fy)
    x0m = x0 % gw
    x1m = (x0 + 1) % gw
    y0m = y0 % gh
    y1m = (y0 + 1) % gh
    v00 = values[y0m, x0m]
    v10 = values[y0m, x1m]
    v01 = values[y1m, x0m]
    v11 = values[y1m, x1m]
    top = v00 + (v10 - v00) * sx
    bot = v01 + (v11 - v01) * sx
    return top + (bot - top) * sy


def _fbm_field(
    rng: np.random.Generator,
    width: int,
    height: int,
    base_cells: float,
    octaves: int = 4,
) -> np.ndarray:
    """Fractal value-noise field over the pixel grid, values in ~[0, 1]."""
    yy, xx = np.mgrid[0:height, 0:width].astype(np.float64)
    total = np.zeros((height, width), dtype=np.float64)
    amp_sum = 0.0
    amp = 1.0
    for k in range(octaves):
        cells_x = max(1, int(round(base_cells * (2**k))))
        cells_y = max(1, int(round(base_cells * (2**k) * height / width)))
        lattice = rng.random((cells_y, cells_x))
        xs = xx / width * cells_x
        ys = yy / height * cells_y
        total += amp * _sample_lattice(lattice, xs, ys)
        amp_sum += amp
        amp *= 0.55
    return total / amp_sum


# ---------------------------------------------------------------------------
# Flow field simulation
# ---------------------------------------------------------------------------


@dataclass
class FlowField:
    """Precomputed deterministic particle trajectories.

    ``trajectories[i, a]`` is particle ``i``'s pixel position at age
    ``a`` (0 = spawn).  ``phases[i]`` is the particle's loop phase
    offset; at video frame ``f`` its age is ``(f + phases[i]) % life``.
    """

    trajectories: np.ndarray  # (N, life + 1, 2) float32, pixel coords
    hues: np.ndarray  # (N,) float32 in [0, 1]
    phases: np.ndarray  # (N,) int64 in [0, life)


def simulate_flowfield(spec: GenartSpec) -> FlowField:
    """Advect all particles through the seeded static flow field."""
    rng = np.random.default_rng(spec.seed & 0xFFFFFFFF)
    w, h = spec.width, spec.height

    noise = _fbm_field(rng, w, h, spec.noise_cells)
    angle = (noise * 2.0 - 1.0) * math.pi * spec.angle_turns
    cos_f = np.cos(angle).astype(np.float32)
    sin_f = np.sin(angle).astype(np.float32)

    n = spec.particle_count
    life = spec.particle_life
    spawns = rng.random((n, 2)) * np.array([w, h])
    hues = np.clip(
        _sample_lattice(
            rng.random((8, 8)),
            spawns[:, 0] / w * 8,
            spawns[:, 1] / h * 8,
        )
        * 0.85
        + rng.random(n) * 0.15,
        0.0,
        1.0,
    ).astype(np.float32)
    phases = rng.integers(0, life, size=n)

    traj = np.empty((n, life + 1, 2), dtype=np.float32)
    pos = spawns.astype(np.float32)
    traj[:, 0] = pos
    step = float(spec.step_size)
    for a in range(1, life + 1):
        xi = np.clip(pos[:, 0].astype(np.int64), 0, w - 1)
        yi = np.clip(pos[:, 1].astype(np.int64), 0, h - 1)
        pos = pos + step * np.stack([cos_f[yi, xi], sin_f[yi, xi]], axis=1)
        pos[:, 0] = np.mod(pos[:, 0], w)
        pos[:, 1] = np.mod(pos[:, 1], h)
        traj[:, a] = pos
    return FlowField(trajectories=traj, hues=hues, phases=phases)


# ---------------------------------------------------------------------------
# Julia fractal
# ---------------------------------------------------------------------------


def julia_mu(spec: GenartSpec, theta: float = 0.0) -> np.ndarray:
    """Smooth escape-time field ``mu`` for the Julia set, shape (H, W).

    ``theta`` orbits the constant ``c`` around ``spec.julia_c`` with
    radius ``spec.orbit_radius``; ``theta = 2*pi`` returns to the start
    (the loop point for video).
    """
    w, h = spec.width, spec.height
    c = spec.julia_c + spec.orbit_radius * complex(
        math.cos(theta), math.sin(theta)
    )
    scale = 1.6
    xs = np.linspace(-scale, scale, w, dtype=np.float64)
    ys = np.linspace(-scale * h / w, scale * h / w, h, dtype=np.float64)
    z = (xs[None, :] + 1j * ys[:, None]).copy()
    mu = np.full((h, w), float(spec.max_iter), dtype=np.float64)
    alive = np.ones((h, w), dtype=bool)
    for i in range(spec.max_iter):
        z[alive] = z[alive] * z[alive] + c
        escaped = alive & (np.abs(z) > 2.0)
        if escaped.any():
            mu[escaped] = i + 1 - np.log2(np.log(np.abs(z[escaped])))
            alive &= ~escaped
            if not alive.any():
                break
    return mu
