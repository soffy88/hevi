"""Procedural brush-stroke painting engine (clean-room implementation).

Concept: a painting is not an image file.  It is a *field* -- for every
point of the canvas the field answers "which colours live here, which way
does the brush move, how long/wide is the dab, when does it appear and
how much does it sway once painted".  The engine samples the field on a
jittered grid with a seeded RNG, turns the answers into a few thousand
short strokes, and reveals them in order so the picture visibly paints
itself.  Everything is deterministic: same scene spec + same seed ->
same strokes, byte for byte.

This module is an original implementation written for hevi.  It shares
no code with any external project; the underlying idea (seeded grid
sampling of a colour/direction field) is a generic generative-art
technique.

Only dependencies: Pillow + the standard library.  CPU-only, offline,
zero marginal cost.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Protocol, Sequence

from PIL import Image, ImageDraw

_MASK64 = (1 << 64) - 1


class SeededRng:
    """SplitMix64 stream: tiny, fast, fully deterministic across runs
    and platforms (integer arithmetic only, no platform float hashing).
    """

    __slots__ = ("_state",)

    def __init__(self, seed: int) -> None:
        self._state = (int(seed) * 0x9E3779B97F4A7C15 + 0x2545F4914F6CDD1D) & _MASK64

    def _next_u64(self) -> int:
        self._state = (self._state + 0x9E3779B97F4A7C15) & _MASK64
        z = self._state
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & _MASK64
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & _MASK64
        return z ^ (z >> 31)

    def random(self) -> float:
        """Uniform float in [0, 1)."""
        return (self._next_u64() >> 11) / float(1 << 53)

    def uniform(self, lo: float, hi: float) -> float:
        return lo + (hi - lo) * self.random()

    def choice(self, seq: Sequence):
        return seq[min(len(seq) - 1, int(self.random() * len(seq)))]


def hash2(a: float, b: float) -> float:
    """Deterministic 2-D coordinate hash -> [0, 1).

    Used by field primitives that need per-point variation without
    consuming the shared RNG stream (their answers must stay a pure
    function of position so layer compositing order cannot change them).
    """
    x = math.sin(a * 127.1 + b * 311.7) * 43758.5453123
    return x - math.floor(x)


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    s = str(value).strip().lstrip("#")
    if len(s) == 3:
        s = "".join(ch * 2 for ch in s)
    if len(s) != 6:
        raise ValueError(f"invalid colour {value!r} (want #rrggbb)")
    return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))


def lerp_rgb(
    a: tuple[int, int, int], b: tuple[int, int, int], t: float
) -> tuple[int, int, int]:
    t = min(1.0, max(0.0, t))
    return (
        round(a[0] + (b[0] - a[0]) * t),
        round(a[1] + (b[1] - a[1]) * t),
        round(a[2] + (b[2] - a[2]) * t),
    )


def palette_at(
    palette: Sequence[tuple[int, int, int]], t: float
) -> tuple[int, int, int]:
    """Sample a multi-stop palette at t in [0, 1]."""
    if not palette:
        raise ValueError("palette must not be empty")
    if len(palette) == 1:
        return palette[0]
    pos = min(1.0, max(0.0, t)) * (len(palette) - 1)
    i = int(pos)
    if i >= len(palette) - 1:
        return palette[-1]
    return lerp_rgb(palette[i], palette[i + 1], pos - i)


@dataclass(frozen=True)
class Cell:
    """One field answer: how a stroke at this point should look."""

    colors: tuple[tuple[int, int, int], ...]
    angle: float  # radians, direction the brush travels
    len_factor: float = 1.6  # stroke length, in grid-step units
    wid_factor: float = 0.62  # stroke width, in grid-step units
    order: float = 0.5  # local reveal order within the layer band, 0..1
    sway: float = 0.0  # sway amplitude in pixels once painted


class Field(Protocol):
    """A paintable region.  ``cell`` returns None outside the region."""

    def cell(self, u: float, v: float) -> Cell | None: ...


@dataclass(frozen=True)
class Stroke:
    x: float
    y: float
    angle: float
    length: float
    width: float
    rgb: tuple[int, int, int]
    order: float  # global reveal order, 0..1
    sway: float  # pixels
    sway_phase: float  # radians

    def key(self) -> tuple:
        return (
            round(self.x, 3),
            round(self.y, 3),
            round(self.angle, 5),
            round(self.length, 3),
            round(self.width, 3),
            self.rgb,
            round(self.order, 5),
            round(self.sway, 3),
            round(self.sway_phase, 5),
        )


@dataclass
class Layer:
    """A field plus the reveal band [order_lo, order_hi] it paints in."""

    field: Field
    order_lo: float = 0.0
    order_hi: float = 1.0


@dataclass
class Scene:
    background: tuple[int, int, int]
    layers: list[Layer] = field(default_factory=list)
    step: float = 14.0  # grid spacing in pixels at render size
    seed: int = 42
    name: str = "scene"


def build_strokes(scene: Scene, width: int, height: int) -> list[Stroke]:
    """Sample the scene's fields into a deterministically ordered
    stroke list.  Scan order is fixed (top-to-bottom, left-to-right)
    and every random draw comes from one seeded stream, so the result
    depends only on (scene, width, height)."""
    rng = SeededRng(scene.seed)
    step = scene.step
    # Let fields know the canvas aspect so circular regions (moon,
    # stars, canopies, vortices) stay circular in pixels, not ovals.
    aspect = width / height
    for layer in scene.layers:
        bind = getattr(layer.field, "bind", None)
        if callable(bind):
            bind(aspect)
    strokes: list[Stroke] = []
    y = step * 0.5
    while y < height + step:
        x = step * 0.5
        while x < width + step:
            px = x + (rng.random() - 0.5) * step
            py = y + (rng.random() - 0.5) * step
            u = px / width
            v = py / height
            winner: tuple[Layer, Cell] | None = None
            for layer in scene.layers:
                cell = layer.field.cell(u, v)
                if cell is not None:
                    winner = (layer, cell)  # later layers paint over
            if winner is not None:
                layer, cell = winner
                rgb = cell.colors[min(len(cell.colors) - 1, int(rng.random() * len(cell.colors)))]
                # Slight per-stroke value jitter, baked in at build time
                # so frames never flicker.
                jitter = 0.92 + 0.16 * rng.random()
                rgb = tuple(max(0, min(255, round(c * jitter))) for c in rgb)
                order = layer.order_lo + (layer.order_hi - layer.order_lo) * min(
                    1.0, max(0.0, cell.order)
                )
                strokes.append(
                    Stroke(
                        x=px,
                        y=py,
                        angle=cell.angle + (rng.random() - 0.5) * 0.22,
                        length=cell.len_factor * step * (0.75 + 0.5 * rng.random()),
                        width=cell.wid_factor * step * (0.8 + 0.4 * rng.random()),
                        rgb=rgb,
                        order=order,
                        sway=cell.sway,
                        sway_phase=rng.random() * math.tau,
                    )
                )
            x += step
        y += step
    strokes.sort(key=lambda s: s.order)
    return strokes


def stroke_polygon(s: Stroke, dx: float = 0.0, dy: float = 0.0) -> list[tuple[float, float]]:
    """Tapered brush dab: a hexagon, wide at the heel, narrow at the tip."""
    ca, sa = math.cos(s.angle), math.sin(s.angle)
    px, py = -sa, ca  # perpendicular
    hl, hw = s.length / 2.0, s.width / 2.0
    cx, cy = s.x + dx, s.y + dy

    def pt(along: float, side: float) -> tuple[float, float]:
        return (cx + ca * along + px * side, cy + sa * along + py * side)

    return [
        pt(-hl, 0.0),
        pt(-hl * 0.35, -hw),
        pt(hl * 0.55, -hw * 0.82),
        pt(hl, -hw * 0.18),
        pt(hl, hw * 0.18),
        pt(hl * 0.55, hw * 0.82),
        pt(-hl * 0.35, hw),
    ]


def draw_stroke(draw: ImageDraw.ImageDraw, s: Stroke, dx: float = 0.0, dy: float = 0.0) -> None:
    draw.polygon(stroke_polygon(s, dx, dy), fill=s.rgb)


def new_canvas(scene: Scene, width: int, height: int) -> Image.Image:
    return Image.new("RGB", (width, height), scene.background)
