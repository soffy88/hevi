"""Seek frame renderer and video rendering engine for RISO animations.

Minimal Playwright seek frame capture adapter following webrender conventions:
- Viewport 1080x1920
- Paused GSAP timeline driven by seek(t)
- Strict font loading verification: fails fast on missing/fallback fonts
- ffmpeg streaming pipeline with zero intermediate disk waste
- PSNR verification for frame-accurate proof sheet match
- Built-in disk space guard (<5G halts immediately)
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from PIL import Image
import numpy as np

from hevi.riso.constants import CANVAS_HEIGHT, CANVAS_WIDTH, FPS
from hevi.riso.templates import render_template_html


class RisoRenderError(RuntimeError):
    """Raised when rendering fails."""


class FontLoadError(RisoRenderError):
    """Raised when custom fonts fail to load (silent fallback forbidden)."""


def check_disk_space() -> None:
    """Halt immediately if /data has less than 5GB available."""
    try:
        usage = shutil.disk_usage("/data")
        if usage.free < 5 * 1024 * 1024 * 1024:
            note_path = Path("DISK_FULL_NOTE.md")
            note_path.write_text(
                f"HALT: Disk space on /data is below 5GB ({usage.free / (1024**3):.2f}GB available).\n",
                encoding="utf-8",
            )
            raise SystemExit("Disk space on /data is below 5GB. Halting immediately.")
    except FileNotFoundError:
        # If /data is not mounted, check current directory disk
        usage = shutil.disk_usage(".")
        if usage.free < 5 * 1024 * 1024 * 1024:
            raise SystemExit("Disk space below 5GB. Halting immediately.")


def compute_image_psnr(image_path_a: Path | str, image_path_b: Path | str) -> float:
    """Calculate Peak Signal-to-Noise Ratio (PSNR) between two images."""
    im_a = Image.open(image_path_a).convert("RGB")
    im_b = Image.open(image_path_b).convert("RGB")
    if im_a.size != im_b.size:
        raise RisoRenderError(f"Image sizes do not match for PSNR: {im_a.size} vs {im_b.size}")

    arr_a = np.array(im_a, dtype=np.float64)
    arr_b = np.array(im_b, dtype=np.float64)
    mse = np.mean((arr_a - arr_b) ** 2)
    if mse <= 1e-10:
        return 99.0
    return float(10.0 * np.log10((255.0 ** 2) / mse))


def extract_video_last_frame(
    video_path: Path | str,
    out_png: Path | str,
    total_frames: int | None = None,
) -> Path:
    """Extract the exact last frame of an MP4 video using ffmpeg."""
    out_path = Path(out_png)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    video_path = Path(video_path)

    cmd = [
        "ffmpeg",
        "-y",
        "-sseof",
        "-0.04",
        "-i",
        str(video_path),
        "-update",
        "1",
        "-vframes",
        "1",
        str(out_path),
    ]
    res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    if res.returncode != 0 or not out_path.exists():
        # Fallback to select filter if sseof fails
        cmd_fallback = [
            "ffmpeg",
            "-y",
            "-i",
            str(video_path),
            "-vf",
            "select=eq(n\\,999999)+1",
            "-vframes",
            "1",
            str(out_path),
        ]
        subprocess.run(cmd_fallback, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if not out_path.exists():
            raise RisoRenderError(f"Failed to extract last frame from {video_path}: {res.stderr}")

    return out_path


def probe_video(video_path: Path | str) -> dict[str, Any]:
    """Run ffprobe on video to verify validity, format, dimensions, duration."""
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration,size,bit_rate:stream=width,height,codec_name,pix_fmt,nb_frames,r_frame_rate",
        "-of",
        "json",
        str(video_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RisoRenderError(f"ffprobe failed for {video_path}: {proc.stderr}")
    return json.loads(proc.stdout)


class WebRenderSession:
    """Playwright-based deterministic seek renderer for RISO HTML animations."""

    def __init__(
        self,
        html_path: Path | str,
        width: int = CANVAS_WIDTH,
        height: int = CANVAS_HEIGHT,
    ) -> None:
        self.html_path = Path(html_path).resolve()
        self.width = width
        self.height = height
        self._playwright = None
        self._browser = None
        self._page = None

    def __enter__(self) -> WebRenderSession:
        check_disk_space()
        try:
            from hevi.layer4_legacy.scene3d.browser import resolve_browsers_path
            resolve_browsers_path()
        except Exception:
            pass
        from playwright.sync_api import sync_playwright

        self._playwright = sync_playwright().start()
        _CHROMIUM_ARGS = [
            "--use-angle=swiftshader",
            "--enable-unsafe-swiftshader",
            "--no-sandbox",
            "--disable-gpu-sandbox",
            "--ignore-gpu-blocklist",
            "--disable-dev-shm-usage",
        ]
        self._browser = self._playwright.chromium.launch(args=_CHROMIUM_ARGS)
        self._page = self._browser.new_page(
            viewport={"width": self.width, "height": self.height},
            device_scale_factor=1.0,
        )
        self._page.goto(self.html_path.as_uri())

        # Strict font loading verification gate
        try:
            self._page.wait_for_function(
                "() => window.__fontsReady === true || window.__fontError !== null",
                timeout=8000,
            )
        except Exception as e:
            raise FontLoadError(f"Timed out waiting for fonts to load: {e}")

        font_error = self._page.evaluate("() => window.__fontError")
        if font_error:
            raise FontLoadError(f"Custom font loading failed: {font_error}")

        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if self._page:
            self._page.close()
        if self._browser:
            self._browser.close()
        if self._playwright:
            self._playwright.stop()

    def render_frame_bytes(self, time_s: float) -> bytes:
        """Seek GSAP timeline to time_s and return PNG bytes."""
        if not self._page:
            raise RisoRenderError("WebRenderSession not started")
        self._page.evaluate("t => window.__renderFrame(t)", time_s)
        return self._page.screenshot(type="png")

    def render_frame(self, time_s: float, out_png: Path | str) -> Path:
        """Seek GSAP timeline to time_s and write PNG image."""
        check_disk_space()
        out_path = Path(out_png)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        png_bytes = self.render_frame_bytes(time_s)
        out_path.write_bytes(png_bytes)
        return out_path

    def render_video(
        self,
        out_path: Path | str,
        duration_s: float,
        fps: int = FPS,
        alpha: bool = False,
        pix_fmt: str = "yuv444p",
    ) -> Path:
        """Render animated frames and pipe directly to ffmpeg, zero intermediate files."""
        check_disk_space()
        out_video = Path(out_path)
        out_video.parent.mkdir(parents=True, exist_ok=True)

        total_frames = max(1, int(round(duration_s * fps)))

        if alpha:
            # Transparent output (ProRes 4444 or VP9 alpha)
            if out_video.suffix.lower() == ".webm":
                ffmpeg_cmd = [
                    "ffmpeg",
                    "-y",
                    "-f",
                    "image2pipe",
                    "-vcodec",
                    "png",
                    "-r",
                    str(fps),
                    "-i",
                    "-",
                    "-c:v",
                    "libvpx-vp9",
                    "-pix_fmt",
                    "yuva420p",
                    str(out_video),
                ]
            else:
                ffmpeg_cmd = [
                    "ffmpeg",
                    "-y",
                    "-f",
                    "image2pipe",
                    "-vcodec",
                    "png",
                    "-r",
                    str(fps),
                    "-i",
                    "-",
                    "-c:v",
                    "prores_ks",
                    "-profile:v",
                    "4444",
                    "-pix_fmt",
                    "yuva444p10le",
                    str(out_video),
                ]
        else:
            # Standard MP4 30fps High fidelity 4:4:4 (PSNR >= 45 dB)
            ffmpeg_cmd = [
                "ffmpeg",
                "-y",
                "-f",
                "image2pipe",
                "-vcodec",
                "png",
                "-r",
                str(fps),
                "-i",
                "-",
                "-c:v",
                "libx264",
                "-crf",
                "10",
                "-preset",
                "medium",
                "-pix_fmt",
                pix_fmt,
                str(out_video),
            ]

        proc = subprocess.Popen(
            ffmpeg_cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )

        try:
            for i in range(total_frames):
                time_s = i / float(fps)
                frame_png = self.render_frame_bytes(time_s)
                proc.stdin.write(frame_png)
            proc.stdin.close()
            stderr_out = proc.stderr.read().decode("utf-8", errors="replace")
            proc.wait()
            if proc.returncode != 0:
                raise RisoRenderError(f"ffmpeg video encoding failed: {stderr_out}")
        except Exception as e:
            proc.kill()
            raise RisoRenderError(f"Rendering aborted during frame stream: {e}")

        # Validate with ffprobe
        probe_info = probe_video(out_video)
        streams = probe_info.get("streams", [])
        if not streams or streams[0].get("codec_name") not in ("h264", "prores", "vp9"):
            raise RisoRenderError(f"Invalid output video generated: {out_video}")

        return out_video


def _render_clip_sync(
    template_name: str,
    data: dict[str, Any],
    out_dir: Path | str,
    clip_id: str = "clip_01",
    duration_s: float = 3.5,
    palette_key: str = "ink_blue_neon_pink",
    seed: int = 42,
    render_video: bool = True,
    alpha: bool = False,
) -> dict[str, Any]:
    """Execute clean-room render for one clip: HTML -> Proof Keyframe -> MP4 -> PSNR verify."""
    out_dir_path = Path(out_dir).resolve()
    out_dir_path.mkdir(parents=True, exist_ok=True)

    # 1. Generate HTML
    html_content = render_template_html(
        template_name=template_name,
        data=data,
        palette_key=palette_key,
        seed=seed,
    )
    html_file = out_dir_path / f"{clip_id}.html"
    html_file.write_text(html_content, encoding="utf-8")

    keyframe_png = out_dir_path / f"{clip_id}_keyframe.png"
    mp4_path = out_dir_path / f"{clip_id}.mp4"

    # Total frames for video and end frame timestamp
    total_frames = max(1, int(round(duration_s * FPS)))
    last_frame_time_s = (total_frames - 1) / float(FPS)

    psnr = None
    with WebRenderSession(html_file) as session:
        # 2. Render Proof Keyframe at exact last frame timestamp
        session.render_frame(time_s=last_frame_time_s, out_png=keyframe_png)

        # 3. Render MP4
        if render_video:
            session.render_video(
                out_path=mp4_path,
                duration_s=duration_s,
                fps=FPS,
                alpha=alpha,
                pix_fmt="yuv444p",
            )

            # 4. Verify end frame PSNR
            extracted_last = out_dir_path / f"{clip_id}_last_extracted.png"
            try:
                extract_video_last_frame(mp4_path, extracted_last)
                psnr = compute_image_psnr(keyframe_png, extracted_last)
            finally:
                if extracted_last.exists():
                    extracted_last.unlink()  # Clean up temporary verification frame

    return {
        "clip_id": clip_id,
        "template": template_name,
        "html_path": html_file,
        "keyframe_png": keyframe_png,
        "mp4_path": mp4_path if render_video else None,
        "duration": duration_s,
        "psnr": psnr,
        "palette": palette_key,
    }


def render_clip(
    template_name: str,
    data: dict[str, Any],
    out_dir: Path | str,
    clip_id: str = "clip_01",
    duration_s: float = 3.5,
    palette_key: str = "ink_blue_neon_pink",
    seed: int = 42,
    render_video: bool = True,
    alpha: bool = False,
) -> dict[str, Any]:
    """Execute clean-room render for one clip, routing through a worker thread if in an active event loop."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None and loop.is_running():
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(
                _render_clip_sync,
                template_name,
                data,
                out_dir,
                clip_id,
                duration_s,
                palette_key,
                seed,
                render_video,
                alpha,
            ).result()

    return _render_clip_sync(
        template_name,
        data,
        out_dir,
        clip_id,
        duration_s,
        palette_key,
        seed,
        render_video,
        alpha,
    )
