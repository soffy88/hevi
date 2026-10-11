"""Deterministic 3D LUT generation (pure functions, no ffmpeg, no I/O except write).

Looks are expressed as per-channel transfer functions so the generated ``.cube``
is reproducible and reviewable.  A LUT is written in the standard Adobe ``.cube``
ordering (red index varies fastest).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

RGB = tuple[float, float, float]
_LUMA = (0.2126, 0.7152, 0.0722)


def _clamp(x: float) -> float:
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x


def _contrast(x: float, amount: float, pivot: float = 0.5) -> float:
    return _clamp((x - pivot) * amount + pivot)


def _gamma(x: float, g: float) -> float:
    return _clamp(x ** (1.0 / g)) if g > 0 else x


def _mix(a: float, b: float, t: float) -> float:
    return a * (1.0 - t) + b * t


def _identity(rgb: RGB) -> RGB:
    return rgb


def _ink(rgb: RGB) -> RGB:
    """Ink-on-paper: desaturate toward luma, raise contrast, lift blacks."""
    r, g, b = rgb
    luma = _LUMA[0] * r + _LUMA[1] * g + _LUMA[2] * b
    desat = 0.35
    r, g, b = _mix(r, luma, desat), _mix(g, luma, desat), _mix(b, luma, desat)
    r, g, b = _contrast(r, 1.18), _contrast(g, 1.18), _contrast(b, 1.18)
    lift = 0.03
    return (_clamp(r + lift * (1 - r)), _clamp(g + lift * (1 - g)), _clamp(b + lift * (1 - b)))


def _teal_orange(rgb: RGB) -> RGB:
    """Push shadows teal, highlights warm."""
    r, g, b = rgb
    luma = _LUMA[0] * r + _LUMA[1] * g + _LUMA[2] * b
    shadow = 1.0 - luma
    r = _clamp(r + 0.10 * luma - 0.03 * shadow)
    g = _clamp(g + 0.02 * luma + 0.02 * shadow)
    b = _clamp(b - 0.05 * luma + 0.10 * shadow)
    return (r, g, b)


def _cool_night(rgb: RGB) -> RGB:
    r, g, b = rgb
    r = _gamma(_clamp(r * 0.92), 0.95)
    g = _gamma(_clamp(g * 0.97), 0.98)
    b = _gamma(_clamp(b * 1.06), 1.02)
    luma = _LUMA[0] * r + _LUMA[1] * g + _LUMA[2] * b
    return (_mix(r, luma, 0.12), _mix(g, luma, 0.12), _mix(b, luma, 0.12))


def _warm_key(rgb: RGB) -> RGB:
    r, g, b = rgb
    return (_gamma(_clamp(r * 1.06), 1.02), _gamma(_clamp(g * 1.01), 1.0), _gamma(_clamp(b * 0.94), 0.98))


LOOKS: dict[str, Callable[[RGB], RGB]] = {
    "neutral": _identity,
    "ink": _ink,
    "teal": _teal_orange,
    "night": _cool_night,
    "warm": _warm_key,
}


def apply_look_to_rgb(look: str, rgb: RGB) -> RGB:
    """Apply a named look to one RGB triple (0..1). Unknown look → identity."""
    return LOOKS.get(look, _identity)(rgb)


def cube_lines(look: str, size: int = 17) -> list[str]:
    """Render the ``.cube`` text for ``look`` at ``size`` nodes per axis."""
    if size < 2:
        raise ValueError("LUT size must be >= 2")
    fn = LOOKS.get(look)
    if fn is None:
        raise ValueError(f"unknown look: {look}")
    lines = [f'TITLE "{look}"', f"LUT_3D_SIZE {size}", "DOMAIN_MIN 0 0 0", "DOMAIN_MAX 1 1 1"]
    step = 1.0 / (size - 1)
    for bi in range(size):
        for gi in range(size):
            for ri in range(size):
                r, g, b = fn((ri * step, gi * step, bi * step))
                lines.append(f"{r:.6f} {g:.6f} {b:.6f}")
    return lines


def write_cube_lut(look: str, path: str | Path, *, size: int = 17) -> Path:
    """Write a ``.cube`` file for ``look``; returns the path."""
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n".join(cube_lines(look, size)) + "\n", encoding="utf-8")
    return dest


__all__ = ["LOOKS", "apply_look_to_rgb", "cube_lines", "write_cube_lut"]
