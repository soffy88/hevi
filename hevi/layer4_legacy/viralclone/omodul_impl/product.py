"""Product physical footage pipeline transaction (omodul layer): cutout -> card -> video."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Any

from hevi.layer4_legacy.viralclone.omodul_impl._media import (
    FFMPEG,
    _probe_video,
    _sha256,
)
from hevi.layer4_legacy.viralclone.oskill_impl.product_card import (
    remove_product_background,
    render_product_card_animation_frames,
)

_enabled_pillars = {"report", "cost", "decision_trail"}


def produce_product_asset(
    config: dict[str, Any],
    input_data: dict[str, Any],
    output_dir: str | Path,
    *,
    on_step: Any = None,
) -> dict[str, Any]:
    """Execute product background removal, card compositing, and video generation."""
    t0 = time.time()
    trail: list[dict[str, Any]] = []
    dest = Path(output_dir)
    dest.mkdir(parents=True, exist_ok=True)

    image_path = input_data.get("product_image") or input_data.get("image_path")
    if not image_path or not Path(image_path).is_file():
        return {
            "status": "blocked",
            "reason": f"INVALID_PRODUCT_IMAGE: {image_path}",
            "cost": {"total_usd": 0.0, "provider": "zero_local_cpu"},
            "decision_trail": [{"step": "validate_input", "error": "file_not_found"}],
            "report": {},
        }

    inp = Path(image_path)
    trail.append({"step": "validate_input", "source": str(inp)})

    try:
        # 1. Background removal with rembg (u2net on CPU)
        cutout_png = dest / "product_cutout.png"
        remove_product_background(inp, cutout_png)
        trail.append({"step": "remove_background", "cutout": str(cutout_png)})

        # 2. Render animation frames with Ken Burns and UI components
        width = int(input_data.get("width") or 720)
        height = int(input_data.get("height") or 1280)
        duration_s = float(input_data.get("duration_s") or 3.0)
        fps = int(input_data.get("fps") or 25)

        frames_dir = dest / "card_frames"
        frames = render_product_card_animation_frames(
            cutout_path=cutout_png,
            output_dir=frames_dir,
            width=width,
            height=height,
            duration_s=duration_s,
            fps=fps,
            product_title=str(input_data.get("product_title") or "精选爆款正品"),
            price_tag=str(input_data.get("price_tag") or "¥99"),
            cta_text=str(input_data.get("cta_text") or "立即抢购"),
            selling_points=list(input_data.get("selling_points") or ["官方正品", "权威实测", "极速发货"]),
        )
        trail.append({"step": "render_card_frames", "frame_count": len(frames)})

        # 3. Encode into product video MP4 using ffmpeg
        product_video_mp4 = dest / "product_card.mp4"
        pattern = str(frames_dir / "frame_%04d.png")
        cmd = [
            FFMPEG,
            "-y",
            "-v",
            "error",
            "-framerate",
            str(fps),
            "-i",
            pattern,
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-r",
            str(fps),
            str(product_video_mp4),
        ]
        subprocess.run(cmd, check=True)
        trail.append({"step": "encode_video", "video": str(product_video_mp4)})

        # 4. Probe and verify
        probe = _probe_video(product_video_mp4)
        sha = _sha256(product_video_mp4)

        elapsed = time.time() - t0
        report = {
            "cutout_png": str(cutout_png),
            "product_video": str(product_video_mp4),
            "sha256": sha,
            "duration_s": probe["duration_s"],
            "resolution": f"{probe['width']}x{probe['height']}",
            "fps": probe["fps"],
            "elapsed_s": round(elapsed, 2),
        }

        return {
            "status": "succeeded",
            "report": report,
            "cost": {"total_usd": 0.0, "provider": "zero_local_cpu"},
            "decision_trail": trail,
        }

    except Exception as exc:
        trail.append({"step": "exception", "error": str(exc)})
        return {
            "status": "failed",
            "reason": f"PRODUCT_PIPELINE_FAILED: {exc}",
            "cost": {"total_usd": 0.0, "provider": "zero_local_cpu"},
            "decision_trail": trail,
            "report": {},
        }
