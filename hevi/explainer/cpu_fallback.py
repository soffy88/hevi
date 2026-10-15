"""Dependency-light explainer renderer used when the Remotion CLI is absent.

It renders safe pastel cue cards with Pillow and muxes the original per-cue
speech using FFmpeg. It is intentionally a resilience path, not a replacement
for the richer Remotion scene renderer.
"""

from __future__ import annotations

import json
import math
import subprocess
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

_FPS = 24
_PALETTES = [
    ("#DFF5FF", "#77C9B9", "#FFD76A", "#FFFDF8"),
    ("#FCE5F0", "#9BD8B7", "#FFC857", "#FFFFFF"),
    ("#E6E2FF", "#8ED8C6", "#FFC857", "#FFFFFF"),
    ("#FFF0D9", "#92D8C5", "#FFCF69", "#FFFFFF"),
    ("#E0F3E5", "#80CDB6", "#FFD16B", "#FFFFFF"),
]


def _font(size: int, *, bold: bool = False) -> ImageFont.ImageFont:
    paths = (
        [
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
            "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        ]
        if bold
        else [
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        ]
    )
    for path in paths:
        if Path(path).is_file():
            try:
                return ImageFont.truetype(path, size=size)
            except OSError:
                continue
    return ImageFont.load_default()


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, width: int) -> list[str]:
    out: list[str] = []
    for paragraph in (text or "").splitlines() or [""]:
        current = ""
        for char in paragraph:
            candidate = current + char
            if current and draw.textlength(candidate, font=font) > width:
                out.append(current)
                current = char
            else:
                current = candidate
        if current:
            out.append(current)
    return out or [""]


def _draw_bunny(draw: ImageDraw.ImageDraw, cx: int, cy: int, scale: float, palette: tuple[str, str, str, str]) -> None:
    cream, pink, dark = "#FFFDF6", "#F3A4B4", "#6D7B8D"
    # Soft ears and body; rounded geometry is supported by Pillow on this image path.
    draw.ellipse((cx - 44 * scale, cy - 105 * scale, cx - 10 * scale, cy - 25 * scale), fill=cream)
    draw.ellipse((cx + 9 * scale, cy - 110 * scale, cx + 42 * scale, cy - 25 * scale), fill=cream)
    draw.ellipse((cx - 35 * scale, cy - 91 * scale, cx - 19 * scale, cy - 37 * scale), fill=pink)
    draw.ellipse((cx + 19 * scale, cy - 96 * scale, cx + 33 * scale, cy - 37 * scale), fill=pink)
    draw.ellipse((cx - 67 * scale, cy - 44 * scale, cx + 68 * scale, cy + 83 * scale), fill=cream)
    draw.ellipse((cx - 76 * scale, cy - 66 * scale, cx + 76 * scale, cy + 55 * scale), fill=cream)
    eye = max(2, int(4 * scale))
    draw.ellipse((cx - 37 * scale, cy - 21 * scale, cx - 37 * scale + eye, cy - 21 * scale + eye), fill=dark)
    draw.ellipse((cx + 31 * scale, cy - 21 * scale, cx + 31 * scale + eye, cy - 21 * scale + eye), fill=dark)
    draw.ellipse((cx - 6 * scale, cy - 5 * scale, cx + 6 * scale, cy + 4 * scale), fill=pink)
    draw.arc((cx - 20 * scale, cy - 8 * scale, cx, cy + 15 * scale), 5, 120, fill=dark, width=max(1, int(2 * scale)))
    draw.arc((cx, cy - 8 * scale, cx + 20 * scale, cy + 15 * scale), 60, 175, fill=dark, width=max(1, int(2 * scale)))
    draw.ellipse((cx - 105 * scale, cy + 63 * scale, cx - 61 * scale, cy + 100 * scale), fill="#FFFFFF")


def _make_card(path: Path, width: int, height: int, title: str, body: str, index: int, *, cover: bool) -> None:
    bg, green, sun, white = _PALETTES[index % len(_PALETTES)]
    image = Image.new("RGB", (width, height), bg)
    draw = ImageDraw.Draw(image)
    # Sun, soft cloud, and rolling hills establish a gentle preschool art direction.
    sun_x, sun_y = int(width * 0.83), int(height * 0.13)
    sun_r = max(18, int(min(width, height) * 0.055))
    draw.ellipse((sun_x - sun_r, sun_y - sun_r, sun_x + sun_r, sun_y + sun_r), fill=sun)
    for offset in (-2, 0, 2):
        draw.arc((sun_x - sun_r - 15 + offset, sun_y - sun_r - 15 + offset,
                  sun_x + sun_r + 15 - offset, sun_y + sun_r + 15 - offset), 200, 340, fill="#F5BD4D", width=2)
    hill_y = int(height * 0.70)
    draw.ellipse((-width * 0.25, hill_y, width * 0.73, height * 1.12), fill=green)
    draw.ellipse((width * 0.24, hill_y - height * 0.04, width * 1.2, height * 1.12), fill="#B5E5B9")
    _draw_bunny(draw, int(width * 0.22), int(height * 0.67), min(width, height) / 720, (bg, green, sun, white))
    # White caption panel provides predictable legibility against the scenery.
    panel_x = int(width * 0.07)
    panel_y = int(height * (0.20 if cover else 0.17))
    panel_w = int(width * 0.86)
    panel_h = int(height * (0.39 if cover else 0.43))
    draw.rounded_rectangle((panel_x, panel_y, panel_x + panel_w, panel_y + panel_h),
                           radius=max(20, int(min(width, height) * 0.035)), fill=white)
    badge_font = _font(max(15, int(min(width, height) * 0.028)), bold=True)
    title_font = _font(max(22, int(min(width, height) * (0.060 if cover else 0.052))), bold=True)
    body_font = _font(max(15, int(min(width, height) * 0.030)))
    draw.rounded_rectangle((panel_x + 22, panel_y + 18, panel_x + min(panel_w - 22, 170), panel_y + 18 + int(min(width, height) * 0.055)),
                           radius=18, fill="#E5F7EF")
    draw.text((panel_x + 34, panel_y + 19), "一起发现" if cover else f"第 {index} 站", font=badge_font, fill="#397A69")
    title_y = panel_y + int(panel_h * 0.30)
    title_lines = _wrap(draw, title.strip() or "小兔子的新发现", title_font, panel_w - 48)[:2]
    for line in title_lines:
        draw.text((panel_x + 24, title_y), line, font=title_font, fill="#36566A", stroke_width=0)
        title_y += title_font.size + 7
    if body:
        body_lines = _wrap(draw, body, body_font, panel_w - 52)[:3]
        body_y = min(panel_y + panel_h - int(body_font.size * (len(body_lines) + 1)), title_y + 4)
        for line in body_lines:
            draw.text((panel_x + 26, body_y), line, font=body_font, fill="#5D7883")
            body_y += body_font.size + 5
    draw.ellipse((int(width * 0.70), int(height * 0.82), int(width * 0.75), int(height * 0.87)), fill="#FFF6B8")
    draw.ellipse((int(width * 0.82), int(height * 0.85), int(width * 0.85), int(height * 0.88)), fill="#FFF6B8")
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="PNG", optimize=True)


def _quote_concat(path: Path) -> str:
    # FFmpeg concat demuxer single-quotes path strings; escape embedded quotes.
    return str(path.resolve()).replace("'", "'\\''")


def _render_one(
    *, width: int, height: int, output: Path, frame_dir: Path, audio_paths: list[Path],
    audio_offsets: list[float], audio_duration: float, cover_title: str, cue_texts: list[str],
    cue_durations: list[float],
) -> dict[str, Any]:
    frame_dir.mkdir(parents=True, exist_ok=True)
    durations = [3.0, *cue_durations]
    labels = ["小兔子的奇妙花园", *cue_texts]
    images: list[Path] = []
    for index, (label, duration) in enumerate(zip(labels, durations, strict=True)):
        p = frame_dir / f"card-{index:03d}.png"
        body = "跟着小兔子一起看一看，听一听！" if index == 0 else f"慢慢说，认真听。约 {duration:.1f} 秒"
        _make_card(p, width, height, cover_title if index == 0 else label, body, index, cover=index == 0)
        images.append(p)

    concat = frame_dir / "frames.ffconcat"
    with concat.open("w", encoding="utf-8") as handle:
        handle.write("ffconcat version 1.0\n")
        for p, duration in zip(images, durations, strict=True):
            handle.write(f"file '{_quote_concat(p)}'\n")
            handle.write(f"duration {max(0.15, float(duration)):.6f}\n")
        handle.write(f"file '{_quote_concat(images[-1])}'\n")

    args = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(concat)]
    for audio in audio_paths:
        args += ["-i", str(audio)]
    filters: list[str] = []
    for index, offset in enumerate(audio_offsets):
        delay = max(0, int(round(offset * 1000)))
        filters.append(f"[{index + 1}:a]aformat=sample_rates=48000:channel_layouts=stereo,adelay={delay}|{delay}[a{index}]")
    filters.append("".join(f"[a{index}]" for index in range(len(audio_paths))) +
                   f"amix=inputs={len(audio_paths)}:duration=longest:normalize=0:dropout_transition=0,aresample=48000[aout]")
    args += [
        "-filter_complex", ";".join(filters), "-map", "0:v", "-map", "[aout]",
        "-r", str(_FPS), "-t", f"{audio_duration:.6f}", "-c:v", "libx264",
        "-preset", "veryfast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart", str(output),
    ]
    output.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(args, capture_output=True, text=True, check=False, timeout=300)
    if proc.returncode != 0 or not output.is_file() or output.stat().st_size <= 0:
        raise RuntimeError(f"CPU explainer render failed ({proc.returncode}): {(proc.stderr or '')[-2000:]}")
    return {"path": str(output), "width": width, "height": height, "fps": _FPS, "duration_s": audio_duration, "renderer": "ffmpeg-pillow-cpu-fallback"}


def render_storyboard_cpu_fallback(
    manifest: list[Any],
    public_dir: Path,
    output_dir: Path,
    *,
    topic: str,
    temp_root: Path,
) -> dict[str, Any]:
    """Render a portrait/landscape explainer pair and preserve cue-level speech timing."""
    cues: list[str] = []
    durations: list[float] = []
    paths: list[Path] = []
    offsets: list[float] = []
    cursor = 0.0
    for index, seg in enumerate(manifest):
        get = (lambda name, default=None: getattr(seg, name, default))
        text = str(get("text", "") or "").strip()
        audio_rel = str(get("audio_file", "") or "").strip()
        audio_path = (public_dir / audio_rel).resolve()
        if not audio_rel or not audio_path.is_relative_to(public_dir.resolve()):
            raise RuntimeError(f"unsafe or missing audio path in cue {index}: {audio_rel!r}")
        if not audio_path.is_file() or audio_path.stat().st_size <= 0:
            raise RuntimeError(f"audio asset for cue {index} is missing: {audio_path}")
        duration = float(get("duration_sec", 0.0) or 0.0)
        if not math.isfinite(duration) or duration <= 0:
            raise RuntimeError(f"cue {index} has invalid duration: {duration}")
        paths.append(audio_path)
        cues.append(text or f"第 {index + 1} 个小发现")
        durations.append(duration)
        offsets.append(3.0 + float(get("start_sec", cursor) or 0.0))
        cursor += duration
    if not paths:
        raise RuntimeError("cannot render an explainer without narrated cues")
    # Match Remotion's title card plus per-cue sequence durations.
    total_duration = 3.0 + sum(durations)
    root = temp_root.resolve() / "explainer_cpu_fallback"
    root.mkdir(parents=True, exist_ok=True)
    result = {
        "portrait": _render_one(
            width=540, height=960, output=output_dir / "portrait.mp4", frame_dir=root / "portrait",
            audio_paths=paths, audio_offsets=offsets, audio_duration=total_duration,
            cover_title=topic, cue_texts=cues, cue_durations=durations,
        ),
        "landscape": _render_one(
            width=960, height=540, output=output_dir / "landscape.mp4", frame_dir=root / "landscape",
            audio_paths=paths, audio_offsets=offsets, audio_duration=total_duration,
            cover_title=topic, cue_texts=cues, cue_durations=durations,
        ),
    }
    (output_dir / "cpu_fallback.render.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result
