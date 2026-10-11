"""Real-ESRGAN 2x / 4x upscaling (CPU, tiled, deterministic)."""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

from hevi.layer4_legacy.enhance.oprim_impl.models import load_realesrgan

logger = logging.getLogger(__name__)

#: Cap on the longest side of a single tile fed to the network (CPU memory).
DEFAULT_TILE = 256
TILE_PAD = 10


def _to_tensor(img: np.ndarray):
    import torch

    t = torch.from_numpy(np.transpose(img[:, :, :3], (2, 0, 1))).float().unsqueeze(0)
    return t


def _from_tensor(t) -> np.ndarray:
    out = t.data.squeeze().float().cpu().clamp_(0, 1).numpy()
    return np.transpose(out, (1, 2, 0))


def _infer_tiled(net, img: np.ndarray, *, tile: int) -> np.ndarray:
    """Run ``net`` over ``img`` (float32 HWC 0..1) with optional tiling."""
    import torch

    h, w = img.shape[:2]
    if tile <= 0 or (h <= tile and w <= tile):
        with torch.no_grad():
            return _from_tensor(net(_to_tensor(img)))

    scale = int(getattr(net, "scale", 4))
    out = np.zeros((h * scale, w * scale, 3), dtype=np.float32)
    for y in range(0, h, tile):
        for x in range(0, w, tile):
            y0 = max(y - TILE_PAD, 0)
            x0 = max(x - TILE_PAD, 0)
            y1 = min(y + tile + TILE_PAD, h)
            x1 = min(x + tile + TILE_PAD, w)
            patch = img[y0:y1, x0:x1, :]
            with torch.no_grad():
                up = _from_tensor(net(_to_tensor(patch)))
            oy0 = (y - y0) * scale
            ox0 = (x - x0) * scale
            oy1 = oy0 + (min(y + tile, h) - y) * scale
            ox1 = ox0 + (min(x + tile, w) - x) * scale
            out[y * scale : min(y + tile, h) * scale, x * scale : min(x + tile, w) * scale, :] = up[
                oy0:oy1, ox0:ox1, :
            ]
    return out


def upscale_array(img_bgr: np.ndarray, *, scale: int, tile: int = DEFAULT_TILE) -> np.ndarray:
    """Upscale a BGR uint8 array; returns BGR uint8."""
    if scale not in (2, 4):
        raise ValueError(f"scale must be 2 or 4, got {scale}")
    net = load_realesrgan(scale)
    rgb = img_bgr[:, :, ::-1].astype(np.float32) / 255.0
    # Real-ESRGAN pads to a multiple of 4 to avoid checkerboard seams.
    h, w = rgb.shape[:2]
    pad = 4
    ph = (pad - h % pad) % pad
    pw = (pad - w % pad) % pad
    if ph or pw:
        rgb = np.pad(rgb, ((0, ph), (0, pw), (0, 0)), mode="reflect")
    up = _infer_tiled(net, rgb, tile=tile)
    up = up[: h * scale, : w * scale, :]
    out = (up * 255.0).round().astype(np.uint8)
    return out[:, :, ::-1]


def upscale_image(
    input_path: str | Path,
    output_path: str | Path,
    *,
    scale: int = 2,
    tile: int = DEFAULT_TILE,
) -> dict[str, object]:
    """Upscale an image file; returns measured input/output dimensions."""
    import cv2

    src = Path(input_path)
    img = cv2.imread(str(src), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(f"cannot read image: {src}")
    out = upscale_array(img, scale=scale, tile=tile)
    dest = Path(output_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(dest), out):
        raise OSError(f"cannot write image: {dest}")
    return {
        "in_w": int(img.shape[1]),
        "in_h": int(img.shape[0]),
        "out_w": int(out.shape[1]),
        "out_h": int(out.shape[0]),
        "scale": scale,
        "model": f"RealESRGAN_x{scale}plus",
    }


__all__ = ["DEFAULT_TILE", "upscale_array", "upscale_image"]
