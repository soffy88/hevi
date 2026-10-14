"""Subframe motion blur renderer and metrics.

Implements headless frame rendering via HTML draw(t) + Playwright with subframe
sampling (subframes=N, offset by 1/(fps·N) and averaged) and ffmpeg tmix motion blur.
Provides quantitative edge sharpness and blur trail measurements.
"""

from __future__ import annotations

import json
import math
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import cv2
import numpy as np


def compute_blur_metrics(frame: np.ndarray) -> Dict[str, float]:
    """Compute quantitative sharpness and motion blur metrics for a frame.

    Returns:
        dict with:
            - laplacian_var: Variance of Laplacian (higher = sharper, lower = blurred)
            - sobel_mean: Mean edge gradient magnitude
            - intermediate_pixels: Count of intermediate luminance pixels [20, 235]
            - intermediate_ratio: Ratio of intermediate pixels to total pixels
    """
    if len(frame.shape) == 3:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    else:
        gray = frame

    # 1. Laplacian variance (classic focus / edge sharpness metric)
    laplacian = cv2.Laplacian(gray, cv2.CV_64F)
    lap_var = float(laplacian.var())

    # 2. Sobel edge magnitude
    sobel_x = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=3)
    sobel_y = cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=3)
    edge_mag = np.sqrt(sobel_x ** 2 + sobel_y ** 2)
    sobel_mean = float(np.mean(edge_mag))

    # 3. Intermediate brightness pixels (motion blur trail creates smooth gradient)
    inter_mask = (gray >= 20) & (gray <= 235)
    inter_count = int(np.sum(inter_mask))
    inter_ratio = float(inter_count / gray.size)

    return {
        "laplacian_var": round(lap_var, 3),
        "sobel_mean": round(sobel_mean, 3),
        "intermediate_pixels": inter_count,
        "intermediate_ratio": round(inter_ratio, 5),
    }


def render_html_subframes(
    html_source: Union[str, Path],
    out: Union[str, Path],
    duration: float = 2.0,
    fps: int = 60,
    subframes: int = 6,
    width: int = 720,
    height: int = 1280,
) -> Path:
    """Render an HTML animation with draw(t) into H.264 yuv420p video with subframe motion blur.

    Args:
        html_source: Path to HTML file or raw HTML string. Must define `window.draw(t)`.
        out: Output mp4 path.
        duration: Video duration in seconds.
        fps: Target output frame rate (30 or 60).
        subframes: Number of subframes sampled per output frame (1 = no blur, 4-6 = motion blur).
                   Each subframe is sampled at t + i / (fps * subframes) and averaged.
        width: Canvas/viewport width.
        height: Canvas/viewport height.

    Returns:
        Path to output mp4.
    """
    from playwright.sync_api import sync_playwright

    out_path = Path(out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Determine HTML content or file URL
    source_path = Path(html_source)
    if source_path.is_file():
        html_url = f"file://{source_path.resolve()}"
        is_file = True
    else:
        is_file = False
        raw_html = str(html_source)

    total_frames = int(round(duration * fps))
    subframes = max(1, int(subframes))
    dt_sub = 1.0 / (fps * subframes)

    # Prepare ffmpeg pipe
    ffmpeg_cmd = [
        "ffmpeg",
        "-y",
        "-f", "rawvideo",
        "-vcodec", "rawvideo",
        "-s", f"{width}x{height}",
        "-pix_fmt", "bgr24",
        "-r", str(fps),
        "-i", "-",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(out_path),
    ]

    pipe_proc = subprocess.Popen(
        ffmpeg_cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-gpu",
                "--disable-dev-shm-usage",
                "--hide-scrollbars",
            ],
        )
        page = browser.new_page(viewport={"width": width, "height": height})

        if is_file:
            page.goto(html_url)
        else:
            page.set_content(raw_html)

        # Wait for canvas or page initialization
        page.wait_for_timeout(200)

        # Inject helper for running subframe averaging in JS if canvas exists
        page.evaluate(
            """() => {
                window._accCanvas = document.createElement('canvas');
                window._accCanvas.width = window.innerWidth;
                window._accCanvas.height = window.innerHeight;
                window._accCtx = window._accCanvas.getContext('2d');
            }"""
        )

        try:
            for k in range(total_frames):
                t_frame = float(k) / float(fps)

                if subframes == 1:
                    # Single sample at t_frame
                    page.evaluate(f"window.draw && window.draw({t_frame})")
                    png_bytes = page.screenshot()
                    img = cv2.imdecode(np.frombuffer(png_bytes, np.uint8), cv2.IMREAD_COLOR)
                    if img.shape[:2] != (height, width):
                        img = cv2.resize(img, (width, height), interpolation=cv2.INTER_LINEAR)
                    pipe_proc.stdin.write(img.tobytes())
                else:
                    # Subframe sampling: sample N subframes and average
                    # Using JS accumulation context for ultra-high speed:
                    # Each subframe is rendered with window.draw(t_sub) and blended with running average alpha
                    js_subframe_render = f"""() => {{
                        const mainCanvas = document.querySelector('canvas') || document.body;
                        const w = {width};
                        const h = {height};
                        const acc = window._accCanvas;
                        const ctx = window._accCtx;
                        ctx.clearRect(0, 0, w, h);
                        
                        const N = {subframes};
                        const dt = {dt_sub};
                        const t0 = {t_frame};
                        
                        for (let i = 0; i < N; i++) {{
                            const t = t0 + i * dt;
                            if (window.draw) window.draw(t);
                            ctx.globalAlpha = 1.0 / (i + 1);
                            ctx.drawImage(mainCanvas, 0, 0, w, h);
                        }}
                        ctx.globalAlpha = 1.0;
                        const finalCtx = mainCanvas.getContext ? mainCanvas.getContext('2d') : null;
                        if (finalCtx) {{
                            finalCtx.clearRect(0, 0, w, h);
                            finalCtx.drawImage(acc, 0, 0, w, h);
                        }}
                    }}"""
                    page.evaluate(js_subframe_render)
                    png_bytes = page.screenshot()
                    img = cv2.imdecode(np.frombuffer(png_bytes, np.uint8), cv2.IMREAD_COLOR)
                    if img.shape[:2] != (height, width):
                        img = cv2.resize(img, (width, height), interpolation=cv2.INTER_LINEAR)
                    pipe_proc.stdin.write(img.tobytes())

        finally:
            browser.close()
            if pipe_proc.stdin:
                pipe_proc.stdin.close()
            stderr = pipe_proc.stderr.read() if pipe_proc.stderr else b""
            retcode = pipe_proc.wait()
            if retcode != 0:
                raise RuntimeError(f"FFmpeg render failed (code {retcode}): {stderr.decode('utf-8', errors='replace')}")

    return out_path


def apply_tmix_motion_blur(
    in_video: Union[str, Path],
    out_video: Union[str, Path],
    subframes: int = 6,
    target_fps: int = 60,
) -> Path:
    """Apply motion blur to a high-framerate video using ffmpeg tmix filter.

    Averages consecutive `subframes` frames and downsamples to `target_fps`.
    """
    in_path = Path(in_video).resolve()
    out_path = Path(out_video).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    weights = " ".join(["1"] * subframes)
    filter_expr = f"tmix=frames={subframes}:weights='{weights}',fps={target_fps}"

    cmd = [
        "ffmpeg",
        "-y",
        "-i", str(in_path),
        "-vf", filter_expr,
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-c:a", "copy",
        str(out_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"tmix motion blur failed: {proc.stderr}")
    return out_path
