"""Render a downscaled ASCII/brightness map of a region to reason about layout without viewing images."""
from __future__ import annotations

import sys

import numpy as np
from PIL import Image


def ascii_map(path: str, x0=0, y0=0, x1=None, y1=None, cols=100) -> None:
    im = Image.open(path).convert("L")
    w, h = im.size
    x1 = w if x1 is None else x1
    y1 = h if y1 is None else y1
    crop = im.crop((x0, y0, x1, y1))
    cw = crop.width
    ch = max(1, int((cw / cols) * (crop.height / max(1, crop.width)) * 2))
    small = crop.resize((cols, ch), Image.Resampling.BOX)
    a = np.array(small, dtype=np.float32)
    chars = " .:-=+*#%@"
    lo, hi = a.min(), a.max()
    rng = max(1e-6, hi - lo)
    print(f"{path} box=({x0},{y0})-({x1},{y1}) size={cw}x{crop.height} range=({lo:.0f},{hi:.0f})")
    for row in a:
        print("".join(chars[min(9, int((v - lo) / rng * 9.999))] for v in row))


if __name__ == "__main__":
    path = sys.argv[1]
    kw = {}
    for a in sys.argv[2:]:
        k, v = a.split("=")
        kw[k] = int(v) if "." not in v else float(v)
    ascii_map(path, **kw)
