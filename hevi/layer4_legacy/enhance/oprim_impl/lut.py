"""LUT application via ffmpeg ``lut3d`` (real pixels, not a plan string)."""

from __future__ import annotations

import logging
from pathlib import Path

from hevi.layer4_legacy.enhance.oprim_impl.media import (
    media_kind,
    probe_media,
    run_ffmpeg,
)
from hevi.layer4_legacy.enhance.oskill_impl.lut_math import LOOKS, write_cube_lut

logger = logging.getLogger(__name__)


def ensure_lut(look: str, lut_dir: str | Path, *, size: int = 17) -> Path:
    """Materialise the ``.cube`` for ``look`` (idempotent)."""
    if look not in LOOKS:
        raise ValueError(f"unknown look '{look}'; available: {sorted(LOOKS)}")
    return write_cube_lut(look, Path(lut_dir) / f"{look}.cube", size=size)


def apply_lut(
    input_path: str | Path,
    output_path: str | Path,
    *,
    look: str,
    lut_dir: str | Path,
    intensity: float = 1.0,
    size: int = 17,
) -> dict[str, object]:
    """Apply a generated LUT to an image or video and return measured metrics."""
    src = Path(input_path)
    kind = media_kind(src)
    if kind not in ("image", "video"):
        raise ValueError(f"LUT can only be applied to image/video, got {kind}: {src}")
    cube = ensure_lut(look, lut_dir, size=size)
    dest = Path(output_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    intensity = max(0.0, min(1.0, float(intensity)))
    chain = f"lut3d=file='{cube}'"
    if intensity < 1.0:
        # blend graded frame over the source at `intensity`
        chain = f"split[a][b];[b]{chain}[g];[a][g]blend=all_mode=normal:all_opacity={intensity}"
    if kind == "image":
        run_ffmpeg(["-y", "-i", str(src), "-vf", chain, str(dest)], timeout_s=300.0)
    else:
        info = probe_media(src)
        args = [
            "-y",
            "-i",
            str(src),
            "-vf",
            chain,
            "-c:v",
            "libx264",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
        ]
        if info.has_audio:
            args += ["-c:a", "copy"]
        args.append(str(dest))
        run_ffmpeg(args)
    return {
        "look": look,
        "lut": str(cube),
        "intensity": intensity,
        "kind": kind,
        "out_w": probe_media(dest).width,
        "out_h": probe_media(dest).height,
    }


__all__ = ["apply_lut", "ensure_lut"]
