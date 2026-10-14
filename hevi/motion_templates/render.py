"""Hevi Motion Templates - Headless Chromium Canvas Renderer.

Stateless, deterministic draw(t) evaluation -> Playwright screenshots -> ffmpeg H.264 yuv420p.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont
from playwright.async_api import async_playwright

logger = logging.getLogger(__name__)

ASPECT_PRESETS: dict[str, tuple[int, int]] = {
    "9:16": (1080, 1920),
    "16:9": (1920, 1080),
    "1:1": (1080, 1080),
}


@dataclass(slots=True)
class RenderResult:
    mp4_path: Path
    contact_sheet_path: Path | None
    duration: float
    fps: int
    width: int
    height: int
    frames_count: int
    sha256: str
    contact_sha256: str | None = None


def resolve_template_path(template: str | Path) -> Path:
    """Finds the template HTML file by name or path."""
    t_path = Path(template)
    if t_path.is_file():
        return t_path.resolve()

    builtin_dir = Path(__file__).resolve().parent / "templates"
    candidate = builtin_dir / template
    if candidate.is_file():
        return candidate.resolve()
    if not template.endswith(".html"):
        candidate_html = builtin_dir / f"{template}.html"
        if candidate_html.is_file():
            return candidate_html.resolve()

    raise FileNotFoundError(f"Template not found: {template} (checked {builtin_dir})")


def compute_file_sha256(path: Path | str) -> str:
    """Computes SHA256 of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def generate_beat_click_track(
    bpm: float,
    duration: float,
    out_path: Path | str,
    freq: float = 1200.0,
) -> Path:
    """Synthesises a deterministic 120-BPM-style click track with ffmpeg lavfi.

    The kinetic specs reference ``assets/audio/beat_120bpm_10s.wav``, but ``*.wav``
    is git-ignored, so a fresh clone cannot reproduce the render. This helper builds
    the click track on the fly with the ``aevalsrc`` lavfi source: a decaying sine
    burst at every beat interval. The output is byte-deterministic for a given
    (bpm, duration, freq) triple, so renders remain reproducible.
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    beat_dur = 60.0 / float(bpm)
    expr = (
        f"0.7*exp(-55*mod(t,{beat_dur:.6f}))*sin(2*PI*{freq:.1f}*t)"
    )
    cmd = [
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        f"aevalsrc='{expr}':s=48000:d={float(duration):.6f}",
        "-c:a",
        "pcm_s16le",
        str(out_path),
    ]
    subprocess.run(cmd, check=True)
    logger.info("Generated %s beat click track at %s", bpm, out_path)
    return out_path


def _resolve_audio_path(raw: str | Path) -> Path:
    """Resolves an audio reference relative to CWD first, then the repo root."""
    cand = Path(raw)
    if cand.is_absolute():
        return cand
    cwd_cand = cand.resolve()
    if cwd_cand.is_file():
        return cwd_cand
    repo_cand = (Path(__file__).resolve().parents[2] / cand).resolve()
    return repo_cand


def create_contact_sheet(
    frames: list[tuple[float, bytes]],
    thumb_w: int,
    thumb_h: int,
    out_path: Path,
) -> Path:
    """Combines sampled frames into a 3-column contact sheet PNG with timestamp labels."""
    n = max(1, len(frames))
    grid_cols = 3 if n >= 3 else n
    grid_rows = (n + grid_cols - 1) // grid_cols
    sheet_w = thumb_w * grid_cols
    sheet_h = thumb_h * grid_rows

    sheet = Image.new("RGB", (sheet_w, sheet_h), color=(11, 15, 25))
    draw = ImageDraw.Draw(sheet)

    for idx, (t, png_bytes) in enumerate(frames[: grid_cols * grid_rows]):
        col = idx % grid_cols
        row = idx // grid_cols
        x = col * thumb_w
        y = row * thumb_h

        img = Image.open(io.BytesIO(png_bytes)).resize((thumb_w, thumb_h), Image.Resampling.LANCZOS)
        sheet.paste(img, (x, y))

        # Tile border
        draw.rectangle([x, y, x + thumb_w - 1, y + thumb_h - 1], outline=(51, 65, 85), width=2)

        # Label tag
        label = f"t={t:.2f}s"
        draw.rectangle([x + 8, y + 8, x + 80, y + 28], fill=(15, 23, 42))
        draw.text((x + 12, y + 10), label, fill=(245, 158, 11))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path, format="PNG")
    return out_path


async def _render_async(
    template: str | Path,
    spec: dict[str, Any] | str | Path,
    out_mp4: str | Path,
    w: int | None = None,
    h: int | None = None,
    fps: int = 30,
    aspect: str = "9:16",
    contact_sheet: bool = True,
    audio_path: str | Path | None = None,
    collect_frame_hashes: bool = False,
) -> tuple[RenderResult, list[str]]:
    """Internal async render worker using Playwright."""
    template_path = resolve_template_path(template)

    if isinstance(spec, (str, Path)):
        spec_path = Path(spec)
        with open(spec_path, "r", encoding="utf-8") as f:
            spec_dict = json.load(f)
    else:
        spec_dict = dict(spec)

    # Determine width and height
    if w is None or h is None:
        if aspect in ASPECT_PRESETS:
            default_w, default_h = ASPECT_PRESETS[aspect]
        else:
            default_w, default_h = (1080, 1920)
        w = w or default_w
        h = h or default_h

    # Duration rule: <= 15s
    duration = float(spec_dict.get("duration", 10.0))
    if duration > 15.0:
        logger.warning("Duration %.2fs exceeds 15s limit, clamping to 15.0s", duration)
        duration = 15.0

    out_mp4_path = Path(out_mp4).resolve()
    out_mp4_path.parent.mkdir(parents=True, exist_ok=True)

    # Resolve audio (auto-generate a deterministic beat click if the referenced
    # git-ignored WAV is missing but the spec declares a bpm).
    effective_audio: Path | None = None
    if audio_path:
        cand = _resolve_audio_path(audio_path)
        if cand.is_file():
            effective_audio = cand
    elif spec_dict.get("audio"):
        cand = _resolve_audio_path(spec_dict["audio"])
        if cand.is_file():
            effective_audio = cand
        elif spec_dict.get("bpm"):
            generate_beat_click_track(float(spec_dict["bpm"]), duration, cand)
            effective_audio = cand
    elif spec_dict.get("narration_wav"):
        cand = _resolve_audio_path(spec_dict["narration_wav"])
        if cand.is_file():
            effective_audio = cand

    frame_hashes: list[str] = []
    contact_sheet_path: Path | None = None
    contact_sha256: str | None = None

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            args=[
                "--no-sandbox",
                "--disable-gpu",
                "--disable-dev-shm-usage",
                "--force-device-scale-factor=1",
                "--font-render-hinting=none",
            ]
        )
        context = await browser.new_context(
            viewport={"width": w, "height": h},
            device_scale_factor=1,
        )
        page = await context.new_page()

        # Load template
        await page.goto(f"file://{template_path}")
        await page.evaluate(f"window.initTemplate({json.dumps(spec_dict)}, {w}, {h})")

        # Step 1: Contact sheet (6 frames, 3 columns x 2 rows)
        if contact_sheet:
            contact_frames: list[tuple[float, bytes]] = []
            n_samples = 6
            for k in range(n_samples):
                t_sample = (k / float(n_samples - 1)) * duration if duration > 0 else 0.0
                await page.evaluate(f"window.draw({t_sample:.6f})")
                png_bytes = await page.locator("#canvas").screenshot(type="png")
                contact_frames.append((t_sample, png_bytes))

            thumb_w = 360 if w >= h else 270
            thumb_h = int(thumb_w * h / w)
            contact_path = out_mp4_path.parent / f"{out_mp4_path.stem}_contact.png"
            create_contact_sheet(contact_frames, thumb_w, thumb_h, contact_path)
            contact_sheet_path = contact_path
            contact_sha256 = compute_file_sha256(contact_path)

        # Step 2: Full video rendering
        total_frames = max(1, int(round(duration * fps)))

        ffmpeg_cmd = [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-f",
            "image2pipe",
            "-vcodec",
            "png",
            "-r",
            str(fps),
            "-i",
            "-",
        ]
        if effective_audio:
            ffmpeg_cmd.extend(["-i", str(effective_audio)])

        ffmpeg_cmd.extend([
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
        ])

        if effective_audio:
            ffmpeg_cmd.extend(["-c:a", "aac", "-b:a", "192k", "-shortest"])

        ffmpeg_cmd.append(str(out_mp4_path))

        proc = subprocess.Popen(ffmpeg_cmd, stdin=subprocess.PIPE)

        for frame_idx in range(total_frames):
            t = frame_idx / float(fps)
            await page.evaluate(f"window.draw({t:.6f})")
            frame_png = await page.locator("#canvas").screenshot(type="png")

            if collect_frame_hashes:
                frame_hashes.append(hashlib.sha256(frame_png).hexdigest())

            proc.stdin.write(frame_png)

        proc.stdin.close()
        proc.wait()

        if proc.returncode != 0:
            raise RuntimeError(f"ffmpeg exited with return code {proc.returncode}")

        await context.close()
        await browser.close()

    mp4_sha256 = compute_file_sha256(out_mp4_path)

    result = RenderResult(
        mp4_path=out_mp4_path,
        contact_sheet_path=contact_sheet_path,
        duration=duration,
        fps=fps,
        width=w,
        height=h,
        frames_count=total_frames,
        sha256=mp4_sha256,
        contact_sha256=contact_sha256,
    )
    return result, frame_hashes


def render(
    template: str | Path,
    spec: dict[str, Any] | str | Path,
    out_mp4: str | Path,
    w: int | None = None,
    h: int | None = None,
    fps: int = 30,
    aspect: str = "9:16",
    contact_sheet: bool = True,
    audio_path: str | Path | None = None,
    collect_frame_hashes: bool = False,
) -> RenderResult:
    """Synchronous entry point to render a motion template."""
    result, _ = asyncio.run(
        _render_async(
            template=template,
            spec=spec,
            out_mp4=out_mp4,
            w=w,
            h=h,
            fps=fps,
            aspect=aspect,
            contact_sheet=contact_sheet,
            audio_path=audio_path,
            collect_frame_hashes=collect_frame_hashes,
        )
    )
    return result


def render_with_frame_hashes(
    template: str | Path,
    spec: dict[str, Any] | str | Path,
    out_mp4: str | Path,
    w: int | None = None,
    h: int | None = None,
    fps: int = 30,
    aspect: str = "9:16",
    contact_sheet: bool = True,
) -> tuple[RenderResult, list[str]]:
    """Renders and returns individual frame sha256 checksums for determinism testing."""
    return asyncio.run(
        _render_async(
            template=template,
            spec=spec,
            out_mp4=out_mp4,
            w=w,
            h=h,
            fps=fps,
            aspect=aspect,
            contact_sheet=contact_sheet,
            collect_frame_hashes=True,
        )
    )
