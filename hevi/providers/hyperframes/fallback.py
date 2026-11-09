"""无 HyperFrames CLI 时的逐卡回退 —— 仍按构图时码出可播 mp4。"""

from __future__ import annotations

import contextlib
import subprocess
from pathlib import Path
from typing import Any

from hevi.providers.hyperframes.compiler import HyperComposition


def _font(size: int) -> Any:
    from PIL import ImageFont

    candidates = (
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    )
    for path in candidates:
        if Path(path).is_file():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def _hex(color: str, default: tuple[int, int, int]) -> tuple[int, int, int]:
    raw = (color or "").strip().lstrip("#")
    if len(raw) == 3:
        raw = "".join(ch * 2 for ch in raw)
    if len(raw) != 6:
        return default
    try:
        return int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16)
    except ValueError:
        return default


def _wrap(text: str, limit: int = 16) -> str:
    body = " ".join((text or "").split())
    if len(body) <= limit:
        return body
    lines: list[str] = []
    while body:
        lines.append(body[:limit])
        body = body[limit:]
        if len(lines) >= 4:
            if body:
                lines[-1] = lines[-1][:-1] + "…"
            break
    return "\n".join(lines)


def render_fallback_composition(
    comp: HyperComposition,
    dest: Path,
    *,
    width: int | None = None,
    height: int | None = None,
    fps: int | None = None,
) -> Path:
    from PIL import Image, ImageDraw

    w = int(width or comp.width or 1920)
    h = int(height or comp.height or 1080)
    rate = int(fps or comp.fps or 30)
    dest.parent.mkdir(parents=True, exist_ok=True)
    work = dest.parent / f".{dest.stem}_hf_frames"
    if work.exists():
        for old in work.glob("*.png"):
            old.unlink()
    work.mkdir(parents=True, exist_ok=True)

    bg = _hex(comp.css_vars.get("--color-bg", ""), (11, 15, 26))
    fg = _hex(comp.css_vars.get("--color-fg", ""), (245, 245, 245))
    accent = _hex(comp.css_vars.get("--color-accent", ""), (245, 158, 11))
    title_font = _font(max(36, h // 12))
    body_font = _font(max(28, h // 18))
    clips = comp.clips or []
    if not clips:
        from hevi.providers.hyperframes.compiler import HyperClip

        clips = [HyperClip(0.0, 3.0, comp.title or "HEVI", kind="title")]

    # The fallback used to write one identical frame per clip, so a 9 s card
    # was reported by raea check as frozen.  Every frame now carries a slow
    # push-in plus a travelling accent bar and a per-card fade, so a card never
    # holds still while its clip plays.
    index = 0
    for clip in clips:
        frames = max(int(clip.duration_s * rate), 1)
        font = title_font if clip.kind == "title" else body_font
        text = _wrap(clip.text, 14 if clip.kind == "title" else 18)
        # Base card at 1.18x so the push-in has real pixels to sample from.
        bw, bh = int(w * 1.18), int(h * 1.18)
        base = Image.new("RGB", (bw, bh), bg)
        bdraw = ImageDraw.Draw(base)
        bdraw.rectangle((0, 0, int(18 * 1.18), bh), fill=accent)
        bbox = bdraw.multiline_textbbox((0, 0), text, font=font, align="center")
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        bdraw.multiline_text(
            ((bw - tw) / 2, (bh - th) / 2),
            text,
            fill=fg,
            font=font,
            align="center",
        )
        for local in range(frames):
            progress = local / max(frames - 1, 1)
            zoom = 1.10 + 0.07 * progress
            crop_w, crop_h = int(bw / zoom), int(bh / zoom)
            pan_x = int((bw - crop_w) * (0.25 + 0.5 * progress))
            pan_y = int((bh - crop_h) * 0.5)
            frame = base.crop((pan_x, pan_y, pan_x + crop_w, pan_y + crop_h)).resize(
                (w, h), Image.LANCZOS
            )
            draw = ImageDraw.Draw(frame)
            # travelling accent bar: at least a few visible pixels move each frame
            bar_w = int(w * 0.22)
            bar_x = int((w - bar_w) * progress)
            draw.rectangle((bar_x, h - 10, bar_x + bar_w, h - 2), fill=accent)
            draw.rectangle((0, 0, int(16 * (1 - progress)) + 2, h), fill=accent)
            fade = min(progress / 0.08, (1.0 - progress) / 0.08, 1.0)
            if fade < 1.0:
                frame = Image.blend(Image.new("RGB", (w, h), (0, 0, 0)), frame, max(0.0, fade))
            frame.save(work / f"f{index:05d}.png")
            index += 1

    if index == 0:
        raise RuntimeError("hyperframes fallback produced no frames")

    cmd = [
        "ffmpeg",
        "-y",
        "-framerate",
        str(rate),
        "-i",
        str(work / "f%05d.png"),
        "-pix_fmt",
        "yuv420p",
        "-c:v",
        "libx264",
        str(dest),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    with contextlib.suppress(OSError):
        for old in work.glob("*.png"):
            old.unlink()
        work.rmdir()
    return dest
