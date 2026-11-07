"""oskill: model-free Paper-Cut layer split + paper sheet compositing.

``split_layers`` colour-clusters an image (deterministic k-means in Lab-ish
space on a downsample), cleans each mask morphologically and orders the
sheets back-to-front (largest/lightest first). ``paper_sheet`` turns one
mask into an RGBA paper sheet: flat colour, white cut border, grain texture.
``drop_shadow`` makes its soft shadow.  Numpy + Pillow only.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageFilter


@dataclass
class PaperLayer:
    mask: Image.Image          # L, 255 = paper
    color: tuple[int, int, int]
    area: float                # fraction of canvas


def kmeans(x: np.ndarray, k: int, *, seed: int = 0, iters: int = 20) -> tuple[np.ndarray, np.ndarray]:
    """Deterministic k-means++ (rows of ``x``) -> (centers, labels)."""
    rng = np.random.default_rng(seed)
    n = len(x)
    k = max(1, min(k, n))
    centers = [x[rng.integers(n)]]
    for _ in range(1, k):
        d = np.min(((x[:, None, :] - np.array(centers)[None]) ** 2).sum(-1), axis=1)
        s = d.sum()
        centers.append(x[rng.choice(n, p=d / s)] if s > 0 else x[rng.integers(n)])
    c = np.array(centers, dtype=np.float64)
    lab = np.zeros(n, dtype=np.int64)
    for _ in range(iters):
        lab = np.argmin(((x[:, None, :] - c[None]) ** 2).sum(-1), axis=1)
        new = np.array([x[lab == j].mean(0) if np.any(lab == j) else c[j] for j in range(k)])
        if np.allclose(new, c, atol=1e-3):
            c = new
            break
        c = new
    return c, lab


def split_layers(img: Image.Image, k: int = 5, *, seed: int = 0, smooth: int = 5, work: int = 160) -> list[PaperLayer]:
    """Split ``img`` into ``k`` paper layers ordered back-to-front."""
    if k < 2:
        raise ValueError("k must be >= 2")
    rgb = img.convert("RGB")
    W, H = rgb.size
    small = rgb.copy()
    small.thumbnail((work, work))
    sw, sh = small.size
    a = np.asarray(small, dtype=np.float64) / 255.0
    pix = a.reshape(-1, 3)
    # positional term keeps regions contiguous ("zones") rather than pure palette
    yy, xx = np.mgrid[0:sh, 0:sw]
    pos = np.stack([xx.ravel() / sw, yy.ravel() / sh], 1) * 0.25
    centers, lab = kmeans(np.concatenate([pix, pos], 1), k, seed=seed)
    lab = lab.reshape(sh, sw)
    order = sorted(range(len(centers)), key=lambda j: (-(lab == j).mean(), -centers[j][:3].sum()))
    layers: list[PaperLayer] = []
    for j in order:
        m = Image.fromarray(((lab == j) * 255).astype(np.uint8), "L").resize((W, H), Image.BILINEAR)
        if smooth:
            m = m.filter(ImageFilter.GaussianBlur(smooth * W / 640)).point(lambda v: 255 if v > 127 else 0)
        col = tuple(int(round(v * 255)) for v in centers[j][:3])
        layers.append(PaperLayer(m, col, float((lab == j).mean())))
    # back sheet covers the whole canvas so no holes show through
    layers[0].mask = Image.new("L", (W, H), 255)
    # make upper sheets a bit larger than their zone where they sit on lower sheets? keep exact zones,
    # and let each sheet also cover all sheets above it (stacked paper, no gaps)
    acc = Image.new("L", (W, H), 0)
    for lay in reversed(layers[1:]):
        acc = Image.fromarray(np.maximum(np.asarray(acc), np.asarray(lay.mask)))
        lay.mask = acc.copy()
    return layers


def paper_grain(size: tuple[int, int], *, seed: int = 0, strength: float = 0.06) -> np.ndarray:
    """Multiplicative fibre/grain field (H,W) around 1.0, deterministic."""
    W, H = size
    rng = np.random.default_rng(seed)
    fine = rng.normal(0, 1, (H, W))
    coarse = np.asarray(Image.fromarray(((rng.normal(0, 1, (max(2, H // 8), max(2, W // 8))) * 40 + 128).clip(0, 255)).astype(np.uint8)).resize((W, H), Image.BICUBIC), dtype=np.float64)
    coarse = (coarse - 128) / 40
    fib = np.asarray(Image.fromarray(((fine * 40 + 128).clip(0, 255)).astype(np.uint8)).filter(ImageFilter.BoxBlur(1)), dtype=np.float64)
    fib = (fib - 128) / 40
    return 1.0 + strength * (0.6 * fib + 0.4 * coarse)


def paper_sheet(mask: Image.Image, color, *, border: int = 4, grain: np.ndarray | None = None) -> Image.Image:
    """RGBA sheet: coloured paper with a white cut edge of ``border`` px."""
    W, H = mask.size
    outer = mask.filter(ImageFilter.MaxFilter(border * 2 + 1)) if border > 0 else mask
    m_in = np.asarray(mask, dtype=np.float64) / 255
    rgb = np.empty((H, W, 3))
    rgb[:] = np.array(color, dtype=np.float64)
    rgb = rgb * m_in[..., None] + 250.0 * (1 - m_in[..., None])  # white rim outside inner mask
    if grain is not None:
        rgb = rgb * grain[..., None]
    alpha = np.asarray(outer.filter(ImageFilter.GaussianBlur(0.7)), dtype=np.uint8)
    out = np.dstack([rgb.clip(0, 255).astype(np.uint8), alpha])
    return Image.fromarray(out, "RGBA")


def drop_shadow(sheet: Image.Image, *, blur: float = 6.0, opacity: float = 0.45) -> Image.Image:
    a = sheet.getchannel("A").filter(ImageFilter.GaussianBlur(blur)).point(lambda v: int(v * opacity))
    sh = Image.new("RGBA", sheet.size, (20, 14, 8, 0))
    sh.putalpha(a)
    return sh
