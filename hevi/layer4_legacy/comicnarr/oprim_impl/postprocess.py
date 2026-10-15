"""Deterministic post-processing passes for generated keyframes.

Currently supports the ``manga_bw`` screentone pass (true grayscale + halftone)
so a colour-capable diffusion model can never leak colour into a black-and-white
comic panel.

3O Pillar: oprim.comicnarr_postprocess
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

# 4x4 Bayer ordered-dither threshold matrix (0..15), scaled to 0..255.
_BAYER4 = np.array(
    [
        [0, 8, 2, 10],
        [12, 4, 14, 6],
        [3, 11, 1, 9],
        [15, 7, 13, 5],
    ],
    dtype=np.float32,
)


def _to_manga_bw_array(rgb: np.ndarray) -> np.ndarray:
    """Convert an RGB uint8 array to a grayscale screentone uint8 array."""
    gray = Image.fromarray(rgb).convert("L")
    gray = ImageOps.autocontrast(gray, cutoff=1)
    # Mild S-curve to deepen inks and clean the paper.
    gray = gray.point(lambda v: int(round(255.0 * (v / 255.0) ** 1.35)))

    arr = np.asarray(gray, dtype=np.float32)
    h, w = arr.shape

    # Ordered-dither halftone (screentone dots) tile.
    tile = np.tile(_BAYER4, (h // 4 + 1, w // 4 + 1))[:h, :w]
    threshold = (tile + 0.5) / 16.0 * 255.0
    halftone = np.where(arr < threshold, 0.0, 255.0)

    # Blend tone (60%) with halftone dots (40%): keeps detail, adds screentone.
    out = 0.6 * arr + 0.4 * halftone
    return np.clip(out, 0, 255).astype(np.uint8)


def apply_style_postprocess(image_path: str | Path, mode: str = "none") -> Path:
    """Apply a deterministic post-process pass to *image_path* in place.

    ``mode``:
      - ``"none"``      : no-op (returns path unchanged)
      - ``"manga_bw"``  : grayscale + autocontrast + halftone screentone
      - ``"grayscale"`` : grayscale + autocontrast only
    """
    path = Path(image_path)
    clean = (mode or "none").strip().lower()
    if clean in ("", "none"):
        return path
    if not path.is_file():
        raise FileNotFoundError(f"postprocess input missing: {path}")

    img = Image.open(path).convert("RGB")
    rgb = np.asarray(img)

    if clean == "manga_bw":
        out = _to_manga_bw_array(rgb)
        result = Image.fromarray(out, mode="L").convert("RGB")
    elif clean == "grayscale":
        gray = ImageOps.autocontrast(Image.fromarray(rgb).convert("L"), cutoff=1)
        result = gray.convert("RGB")
    else:
        raise ValueError(f"unknown postprocess mode: {mode!r}")

    result.save(path, format="PNG")
    return path


def is_grayscale(image_bgr: np.ndarray, tolerance: int = 10) -> bool:
    """Return True when a BGR uint8 image has (near-)equal colour channels."""
    if image_bgr.ndim != 3 or image_bgr.shape[2] < 3:
        return True
    b = image_bgr[:, :, 0].astype(np.int16)
    g = image_bgr[:, :, 1].astype(np.int16)
    r = image_bgr[:, :, 2].astype(np.int16)
    max_dev = int(np.max(np.abs(b - g))) + int(np.max(np.abs(g - r)))
    return max_dev <= tolerance * 2


__all__ = [
    "apply_style_postprocess",
    "is_grayscale",
]
