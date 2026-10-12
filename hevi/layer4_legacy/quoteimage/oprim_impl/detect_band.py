from __future__ import annotations

from pathlib import Path
from typing import Sequence
import numpy as np
from PIL import ImageChops, ImageFilter

from hevi.layer4_legacy.quoteimage.oprim_impl.vendor_stitch import grab_frame


def detect_subtitle_band(
    *,
    video_path: str | Path,
    times: Sequence[float],
) -> tuple[float, float]:
    """Detect vertical bounds (top, bottom as fraction of height 0..1) of the subtitle band.
    
    Uses temporal and edge differences across multiple sample frames to tightly isolate
    text rows in the lower half of the frame.
    """
    if len(times) < 2:
        return 0.78, 0.96

    h = None
    summed_rows = None

    try:
        ref_frame = grab_frame(str(video_path), times[0]).convert("L")
        ref2_frame = grab_frame(str(video_path), times[-1]).convert("L")
    except Exception:
        return 0.78, 0.96

    for t in times:
        try:
            f1 = grab_frame(str(video_path), t)
            f2 = grab_frame(str(video_path), t + 0.2)
            gray1 = f1.convert("L")
            gray2 = f2.convert("L")

            edges = ImageChops.subtract(gray1, gray1.filter(ImageFilter.MinFilter(3)))
            diff_fast = ImageChops.difference(gray1, gray2)
            diff_slow1 = ImageChops.difference(gray1, ref_frame)
            diff_slow2 = ImageChops.difference(gray1, ref2_frame)

            edges_np = np.array(edges)
            dfast_np = np.array(diff_fast)
            dslow1_np = np.array(diff_slow1)
            dslow2_np = np.array(diff_slow2)

            subtitle_mask = (edges_np > 20) & (dfast_np < 5) & ((dslow1_np > 30) | (dslow2_np > 30))
            row_sums = subtitle_mask.sum(axis=1)

            if h is None:
                h = f1.height
                summed_rows = np.zeros(h)

            # Only analyze lower portion of the frame
            row_sums[: int(h * 0.45)] = 0
            summed_rows += row_sums
        except Exception:
            pass

    if h is None or summed_rows is None:
        return 0.78, 0.96

    window = max(1, int(h * 0.015))
    smoothed = np.convolve(summed_rows, np.ones(window) / window, mode="same")

    peak_val = np.max(smoothed)
    if peak_val < 5:
        return 0.78, 0.96

    threshold = peak_val * 0.35
    text_rows = np.where(smoothed > threshold)[0]

    if len(text_rows) > 0:
        pad = max(4, int(h * 0.012))
        y_top = max(int(h * 0.45), text_rows[0] - pad)
        y_bottom = min(h, text_rows[-1] + pad)
        return float(round(y_top / h, 4)), float(round(y_bottom / h, 4))

    return 0.78, 0.96
