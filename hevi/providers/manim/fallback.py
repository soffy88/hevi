"""Manim CLI 不可用时的逐帧回退 —— 仍是「代码即画面」,只是不用 Manim 内核。"""

from __future__ import annotations

import contextlib
import subprocess
from pathlib import Path
from typing import Any

from hevi.prompt.manim_compiler import ManimSceneIR

_BG = {
    "3b1b": (26, 26, 46),
    "light": (244, 241, 234),
}
_FG = {
    "3b1b": (236, 230, 221),
    "light": (34, 34, 34),
}
_ACCENT = {
    "3b1b": (255, 224, 48),
    "light": (181, 137, 0),
}


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


def _clamp_text(text: str, limit: int = 48) -> str:
    body = " ".join((text or "").split())
    return body if len(body) <= limit else body[: limit - 1] + "…"


def render_fallback_scene(
    ir: ManimSceneIR | None,
    dest: Path,
    *,
    width: int = 1920,
    height: int = 1080,
    fps: int = 30,
) -> Path:
    from PIL import Image, ImageDraw

    scene = ir or ManimSceneIR()
    duration = min(max(float(scene.duration_s or 5.0), 1.0), 20.0)
    frames = max(int(duration * fps), fps)
    theme = scene.theme if scene.theme in _BG else "3b1b"
    bg = _BG[theme]
    fg = _FG[theme]
    accent = _ACCENT[theme]
    title_font = _font(max(36, height // 18))
    body_font = _font(max(48, height // 14))
    small_font = _font(max(28, height // 24))
    dest.parent.mkdir(parents=True, exist_ok=True)
    work = dest.parent / f".{dest.stem}_frames"
    if work.exists():
        for old in work.glob("*.png"):
            old.unlink()
    work.mkdir(parents=True, exist_ok=True)

    title = _clamp_text(scene.title, 28)
    main = _clamp_text(scene.tex or scene.title or "HEVI", 36)
    other = _clamp_text(scene.tex_to, 36)
    bullets = [_clamp_text(item, 40) for item in scene.bullets[:6]] or None

    for index in range(frames):
        progress = index / max(frames - 1, 1)
        image = Image.new("RGB", (width, height), bg)
        draw = ImageDraw.Draw(image)
        _draw_recipe(
            draw,
            recipe=scene.recipe,
            progress=progress,
            title=title,
            main=main,
            other=other,
            bullets=bullets,
            left=scene.left_label,
            right=scene.right_label,
            series=scene.series,
            width=width,
            height=height,
            fg=fg,
            accent=accent,
            title_font=title_font,
            body_font=body_font,
            small_font=small_font,
        )
        image.save(work / f"{index:05d}.png")

    cmd = [
        "ffmpeg",
        "-y",
        "-framerate",
        str(fps),
        "-i",
        str(work / "%05d.png"),
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(dest),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    for png in work.glob("*.png"):
        png.unlink()
    with contextlib.suppress(OSError):
        work.rmdir()
    if proc.returncode != 0 or not dest.exists() or dest.stat().st_size == 0:
        raise RuntimeError(f"manim fallback ffmpeg 失败: {(proc.stderr or '')[-400:]}")
    return dest


def _draw_recipe(
    draw: Any,
    *,
    recipe: str,
    progress: float,
    title: str,
    main: str,
    other: str,
    bullets: list[str] | None,
    left: str,
    right: str,
    series: list[float],
    width: int,
    height: int,
    fg: tuple[int, int, int],
    accent: tuple[int, int, int],
    title_font: Any,
    body_font: Any,
    small_font: Any,
) -> None:
    cx, cy = width // 2, height // 2
    if title and recipe != "title_card":
        alpha = min(progress / 0.15, 1.0)
        draw.text((80, 80), title, font=title_font, fill=_fade(accent, alpha))
    if recipe == "list_reveal" and bullets:
        visible = max(1, int(progress * len(bullets) + 0.01))
        for i, item in enumerate(bullets[:visible]):
            draw.text((160, 220 + i * 90), f"· {item}", font=small_font, fill=fg)
        return
    if recipe == "comparison":
        draw.text((width * 0.18, cy), _clamp_text(left or main, 16), font=body_font, fill=fg)
        draw.text(
            (width * 0.62, cy),
            _clamp_text(right or other or title, 16),
            font=body_font,
            fill=accent,
        )
        return
    if recipe == "number_line":
        y = cy
        draw.line((160, y, width - 160, y), fill=fg, width=4)
        for tick in range(9):
            x = 160 + tick * (width - 320) / 8
            draw.line((x, y - 16, x, y + 16), fill=fg, width=3)
        x = 160 + min(progress, 1.0) * (width - 320)
        r = 16
        draw.ellipse((x - r, y - r, x + r, y + r), fill=accent)
        return
    if recipe == "axes_plot":
        values = series or [0.4, 1.1, 0.8, 1.6, 1.2]
        left_x, top, right_x, bottom = 220, 220, width - 180, height - 180
        draw.line((left_x, bottom, right_x, bottom), fill=fg, width=3)
        draw.line((left_x, top, left_x, bottom), fill=fg, width=3)
        peak = float(max(values) or 1.0)
        shown = max(2, int(progress * len(values) + 1))
        pts: list[tuple[int, int]] = []
        for i, value in enumerate(values[:shown]):
            x_pos = left_x + i * (right_x - left_x) / max(len(values) - 1, 1)
            y_pos = bottom - (value / peak) * (bottom - top) * 0.85
            pts.append((int(x_pos), int(y_pos)))
        if len(pts) >= 2:
            draw.line(pts, fill=accent, width=5)
        for x, y in pts:
            draw.ellipse((x - 8, y - 8, x + 8, y + 8), fill=accent)
        return
    if recipe == "transform" and other:
        if progress < 0.5:
            draw.text((cx, cy), main, font=body_font, fill=fg, anchor="mm")
        else:
            draw.text((cx, cy), other, font=body_font, fill=accent, anchor="mm")
        return
    alpha = min(max((progress - 0.05) / 0.35, 0.0), 1.0)
    draw.text((cx, cy), main, font=body_font, fill=_fade(fg, alpha), anchor="mm")
    if recipe == "title_card" and title and title != main:
        draw.text((cx, cy - 110), title, font=title_font, fill=_fade(accent, alpha), anchor="mm")


def _fade(color: tuple[int, int, int], alpha: float) -> tuple[int, int, int]:
    t = min(max(alpha, 0.0), 1.0)
    return tuple(int(channel * t) for channel in color)  # type: ignore[return-value]
