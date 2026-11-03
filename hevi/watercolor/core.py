"""Procedural watercolour rendering (deterministic, local, $0).

Original implementation of the classic digital-watercolour idea:

* Take a base shape (circle / ellipse / rectangle / polygon point list).
* Repeatedly apply *midpoint displacement*: every edge's midpoint is
  pushed by a random offset, the amplitude decaying each iteration.
  After a few iterations the once-crisp outline is irregular in the
  way a wet pigment edge is.
* Draw that shape many times (default 40 layers), each version
  displaced slightly differently and each at very low opacity
  (default alpha 0.045).  The centre is covered by almost every
  layer and saturates; a given edge point is covered by only a few
  layers and stays pale.  That uneven coverage *is* the bleed /
  halo — no blur filter and no AI image model is involved.

Determinism: every random decision comes from ``random.Random``
instances seeded from the caller's ``seed`` (never the global RNG),
and PNG output is written with no timestamp/metadata, so the same
seed + same parameters produce a byte-identical PNG.

Core API (usable directly by handdraw / HyperFrames / any line)::

    from hevi.watercolor import render_watercolor_image, demo_scene_shapes
    img = render_watercolor_image(
        demo_scene_shapes(640, 480), width=640, height=480, seed=42)
    img.save("scene.png")

Shapes are plain dicts::

    {"type": "circle",  "center": [x, y], "radius": r, "color": "#E4572E"}
    {"type": "ellipse", "center": [x, y], "rx": rx, "ry": ry, "color": ...}
    {"type": "rect",    "points": [[x0, y0], [x1, y1]], "color": ...}
    {"type": "polygon", "points": [[x, y], ...], "color": "#5B7E99"}
    {"type": "path",    "points": [[x, y], ...], "color": ...}  # closed fill

``color`` may also be an ``[r, g, b]`` list.  Any shape may override
``layers`` / ``alpha`` / ``displacement`` / ``iterations`` per shape.
"""

from __future__ import annotations

import math
import random
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

__all__ = [
    "DEFAULT_ALPHA",
    "DEFAULT_DISPLACEMENT",
    "DEFAULT_ITERATIONS",
    "DEFAULT_LAYERS",
    "base_points_for_shape",
    "circle_points",
    "demo_scene_shapes",
    "displace_polygon",
    "ellipse_points",
    "parse_color",
    "render_flat_image",
    "render_watercolor_image",
    "save_png",
]

DEFAULT_LAYERS = 40
DEFAULT_ALPHA = 0.045
DEFAULT_DISPLACEMENT = 6.0
DEFAULT_ITERATIONS = 4

_MAX_DIM = 4096
_MAX_POINTS_AFTER_DISPLACEMENT = 8192


# ---------------------------------------------------------------------------
# validation helpers
# ---------------------------------------------------------------------------

def _check_canvas(width: Any, height: Any) -> tuple[int, int]:
    if not isinstance(width, int) or isinstance(width, bool):
        raise ValueError(f"width must be an int, got {width!r}")
    if not isinstance(height, int) or isinstance(height, bool):
        raise ValueError(f"height must be an int, got {height!r}")
    if not (16 <= width <= _MAX_DIM and 16 <= height <= _MAX_DIM):
        raise ValueError(
            f"canvas {width}x{height} out of range (each side 16..{_MAX_DIM})"
        )
    return width, height


def _check_paint_params(
    *, layers: Any, alpha: Any, displacement: Any, iterations: Any
) -> tuple[int, float, float, int]:
    if not isinstance(layers, int) or isinstance(layers, bool) or not (1 <= layers <= 200):
        raise ValueError(f"layers must be an int in 1..200, got {layers!r}")
    if isinstance(alpha, bool) or not isinstance(alpha, (int, float)) or not (0 < float(alpha) <= 1.0):
        raise ValueError(f"alpha must be a number in (0, 1], got {alpha!r}")
    if isinstance(displacement, bool) or not isinstance(displacement, (int, float)) or float(displacement) < 0:
        raise ValueError(f"displacement must be a number >= 0, got {displacement!r}")
    if not isinstance(iterations, int) or isinstance(iterations, bool) or not (0 <= iterations <= 6):
        raise ValueError(f"iterations must be an int in 0..6, got {iterations!r}")
    return layers, float(alpha), float(displacement), iterations


def parse_color(color: Any) -> tuple[int, int, int]:
    """Parse ``#RRGGBB`` / ``#RGB`` / ``[r, g, b]`` into an RGB tuple."""
    if isinstance(color, str):
        s = color.strip()
        if s.startswith("#"):
            s = s[1:]
        if len(s) == 3:
            s = "".join(ch * 2 for ch in s)
        if len(s) != 6:
            raise ValueError(f"invalid colour {color!r}: expected #RRGGBB")
        try:
            return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
        except ValueError as exc:
            raise ValueError(f"invalid colour {color!r}: not hex") from exc
    if isinstance(color, (list, tuple)) and len(color) == 3:
        out = []
        for v in color:
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not (0 <= v <= 255):
                raise ValueError(f"invalid colour component {v!r} in {color!r}")
            out.append(int(v))
        return out[0], out[1], out[2]
    raise ValueError(f"invalid colour {color!r}: expected #RRGGBB or [r, g, b]")


def _point(value: Any, what: str) -> tuple[float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError(f"{what} must be [x, y], got {value!r}")
    x, y = value
    if isinstance(x, bool) or isinstance(y, bool) or not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
        raise ValueError(f"{what} coordinates must be numbers, got {value!r}")
    return float(x), float(y)


# ---------------------------------------------------------------------------
# base shapes
# ---------------------------------------------------------------------------

def circle_points(
    center: Sequence[float], radius: float, *, segments: int = 16
) -> list[tuple[float, float]]:
    if radius <= 0:
        raise ValueError(f"circle radius must be > 0, got {radius!r}")
    cx, cy = float(center[0]), float(center[1])
    return [
        (
            cx + radius * math.cos(2.0 * math.pi * i / segments),
            cy + radius * math.sin(2.0 * math.pi * i / segments),
        )
        for i in range(segments)
    ]


def ellipse_points(
    center: Sequence[float], rx: float, ry: float, *, segments: int = 20
) -> list[tuple[float, float]]:
    if rx <= 0 or ry <= 0:
        raise ValueError(f"ellipse radii must be > 0, got rx={rx!r} ry={ry!r}")
    cx, cy = float(center[0]), float(center[1])
    return [
        (
            cx + rx * math.cos(2.0 * math.pi * i / segments),
            cy + ry * math.sin(2.0 * math.pi * i / segments),
        )
        for i in range(segments)
    ]


def base_points_for_shape(shape: dict[str, Any]) -> list[tuple[float, float]]:
    """Resolve a shape dict to its undisplaced polygon point list."""
    if not isinstance(shape, dict):
        raise ValueError(f"shape must be a dict, got {type(shape).__name__}")
    kind = shape.get("type") or shape.get("kind")
    if kind == "circle":
        center = _point(shape.get("center"), "circle center")
        radius = shape.get("radius")
        if isinstance(radius, bool) or not isinstance(radius, (int, float)):
            raise ValueError(f"circle radius must be a number, got {radius!r}")
        return circle_points(center, float(radius))
    if kind == "ellipse":
        center = _point(shape.get("center"), "ellipse center")
        rx, ry = shape.get("rx"), shape.get("ry")
        if not isinstance(rx, (int, float)) or not isinstance(ry, (int, float)):
            raise ValueError(f"ellipse rx/ry must be numbers, got rx={rx!r} ry={ry!r}")
        return ellipse_points(center, float(rx), float(ry))
    if kind == "rect":
        raw = shape.get("points")
        if not isinstance(raw, (list, tuple)) or len(raw) != 2:
            raise ValueError("rect needs points=[[x0, y0], [x1, y1]]")
        (x0, y0), (x1, y1) = _point(raw[0], "rect corner"), _point(raw[1], "rect corner")
        return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    if kind in ("polygon", "path"):
        raw = shape.get("points")
        if not isinstance(raw, (list, tuple)) or len(raw) < 3:
            raise ValueError(f"{kind} needs at least 3 points, got {raw!r}")
        return [_point(p, f"{kind} point") for p in raw]
    raise ValueError(
        f"unknown shape type {kind!r}: expected circle|ellipse|rect|polygon|path"
    )


# ---------------------------------------------------------------------------
# midpoint displacement
# ---------------------------------------------------------------------------

def displace_polygon(
    points: Sequence[tuple[float, float]],
    rng: random.Random,
    *,
    displacement: float,
    iterations: int,
) -> list[tuple[float, float]]:
    """Return ``points`` after ``iterations`` rounds of midpoint displacement.

    Each round inserts, between every pair of neighbouring vertices,
    their midpoint shifted by ``rng.uniform(-amp, amp)`` on both axes;
    ``amp`` starts at ``displacement`` and decays by 0.58 per round so
    large-scale wobble dominates and fine rounds only roughen the edge.
    All randomness flows through the caller-supplied ``rng``.
    """
    pts = [(float(x), float(y)) for x, y in points]
    amp = float(displacement)
    for _ in range(iterations):
        nxt: list[tuple[float, float]] = []
        n = len(pts)
        for i in range(n):
            x1, y1 = pts[i]
            x2, y2 = pts[(i + 1) % n]
            nxt.append((x1, y1))
            nxt.append(
                (
                    (x1 + x2) / 2.0 + rng.uniform(-amp, amp),
                    (y1 + y2) / 2.0 + rng.uniform(-amp, amp),
                )
            )
        pts = nxt
        amp *= 0.58
    return pts


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------

def _effective_params(
    shape: dict[str, Any], layers: int, alpha: float, displacement: float, iterations: int
) -> tuple[int, float, float, int]:
    return _check_paint_params(
        layers=shape.get("layers", layers),
        alpha=shape.get("alpha", alpha),
        displacement=shape.get("displacement", displacement),
        iterations=shape.get("iterations", iterations),
    )


def render_watercolor_image(
    shapes: Sequence[dict[str, Any]],
    *,
    width: int = 640,
    height: int = 480,
    background: Any = "#FFFEF8",
    layers: int = DEFAULT_LAYERS,
    alpha: float = DEFAULT_ALPHA,
    displacement: float = DEFAULT_DISPLACEMENT,
    iterations: int = DEFAULT_ITERATIONS,
    seed: int = 42,
) -> Image.Image:
    """Render ``shapes`` as layered watercolour; returns an RGB PIL Image.

    Same ``seed`` + same parameters => byte-identical PNG when saved
    with :func:`save_png` (or plain ``Image.save`` — no metadata is
    attached either way).
    """
    width, height = _check_canvas(width, height)
    layers, alpha, displacement, iterations = _check_paint_params(
        layers=layers, alpha=alpha, displacement=displacement, iterations=iterations
    )
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise ValueError(f"seed must be an int, got {seed!r}")
    shape_list = list(shapes) if shapes is not None else []
    if not shape_list:
        raise ValueError("shapes must be a non-empty list")

    bg = parse_color(background)
    canvas = Image.new("RGBA", (width, height), (bg[0], bg[1], bg[2], 255))

    for idx, shape in enumerate(shape_list):
        base = base_points_for_shape(shape)
        color = parse_color(shape.get("color"))
        s_layers, s_alpha, s_disp, s_iter = _effective_params(
            shape, layers, alpha, displacement, iterations
        )
        if len(base) * (2 ** s_iter) > _MAX_POINTS_AFTER_DISPLACEMENT:
            raise ValueError(
                f"shape {idx}: {len(base)} points x 2^{s_iter} exceeds "
                f"{_MAX_POINTS_AFTER_DISPLACEMENT} displaced points"
            )
        alpha_byte = max(1, min(255, round(s_alpha * 255)))
        # Per-shape RNG: adding a later shape never changes earlier ones.
        rng = random.Random(seed + idx * 10007)
        for _layer in range(s_layers):
            pts = displace_polygon(base, rng, displacement=s_disp, iterations=s_iter)
            overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            ImageDraw.Draw(overlay).polygon(
                pts, fill=(color[0], color[1], color[2], alpha_byte)
            )
            canvas.alpha_composite(overlay)
    return canvas.convert("RGB")


def render_flat_image(
    shapes: Sequence[dict[str, Any]],
    *,
    width: int = 640,
    height: int = 480,
    background: Any = "#FFFEF8",
) -> Image.Image:
    """Render the same shapes as ordinary flat fill (one opaque layer each).

    The comparison baseline for the watercolour render: crisp edges,
    uniform saturation everywhere, no bleed.
    """
    width, height = _check_canvas(width, height)
    shape_list = list(shapes) if shapes is not None else []
    if not shape_list:
        raise ValueError("shapes must be a non-empty list")
    bg = parse_color(background)
    img = Image.new("RGB", (width, height), bg)
    draw = ImageDraw.Draw(img)
    for shape in shape_list:
        draw.polygon(base_points_for_shape(shape), fill=parse_color(shape.get("color")))
    return img


def demo_scene_shapes(width: int, height: int) -> list[dict[str, Any]]:
    """Minimal sun + far mountain + lake composition, scaled to the canvas."""
    w, h = float(width), float(height)
    m = min(w, h)
    return [
        {
            "type": "circle",
            "center": [0.72 * w, 0.27 * h],
            "radius": 0.13 * m,
            "color": "#E4572E",
        },
        {
            "type": "polygon",
            "points": [
                [0.0, 0.64 * h],
                [0.26 * w, 0.38 * h],
                [0.50 * w, 0.60 * h],
                [0.73 * w, 0.42 * h],
                [w, 0.64 * h],
            ],
            "color": "#5B7E99",
        },
        {
            "type": "polygon",
            "points": [[0.0, 0.68 * h], [w, 0.68 * h], [w, h], [0.0, h]],
            "color": "#2E6F9E",
        },
    ]


def save_png(image: Image.Image, path: str | Path) -> Path:
    """Save ``image`` as PNG deterministically (no metadata / timestamps)."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    image.save(out, format="PNG")
    return out
