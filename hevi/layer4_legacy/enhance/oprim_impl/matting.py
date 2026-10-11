"""Background removal / alpha matte via rembg (U^2-Net, Apache-2.0, CPU)."""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "u2net"


def _session(model: str):
    from rembg import new_session

    return new_session(model)


def matte_image(
    input_path: str | Path,
    output_path: str | Path,
    *,
    model: str = DEFAULT_MODEL,
    mask_path: str | Path | None = None,
    post_process: bool = True,
) -> dict[str, object]:
    """Remove the background of an image → RGBA PNG (+ optional L-mode mask)."""
    from PIL import Image
    from rembg import remove

    src = Path(input_path)
    img = Image.open(src).convert("RGB")
    session = _session(model)
    cutout = remove(img, session=session, post_process_mask=post_process)
    out_img = cutout.convert("RGBA") if isinstance(cutout, Image.Image) else Image.open(cutout).convert("RGBA")
    dest = Path(output_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    out_img.save(dest)

    metrics: dict[str, object] = {
        "width": out_img.width,
        "height": out_img.height,
        "model": model,
        "has_alpha": True,
    }
    if mask_path is not None:
        alpha = out_img.getchannel("A")
        mp = Path(mask_path)
        mp.parent.mkdir(parents=True, exist_ok=True)
        alpha.save(mp)
        hist = alpha.histogram()
        total = max(sum(hist), 1)
        # fraction of fully-transparent pixels = background coverage
        metrics["transparent_ratio"] = round(hist[0] / total, 4)
        metrics["mask_path"] = str(mp)
    return metrics


__all__ = ["DEFAULT_MODEL", "matte_image"]
