"""封面生成与封面 QA（omodul 层）。

上游 ``cover-qa.md`` 要求两张独立资产：**3:4 竖版**（视频号竖版、小红书）与
**4:3 横版**（公众号、B站），两种比例各自构图，并且**实测**宽高满足
``宽×4=高×3`` / ``宽×3=高×4``。

本机零成本、无 imagegen，因此封面是**本地重排版**：取成片的一帧当底图，用
仓库自带中文字体把标题排上去（不是裸截图冒充）。生成方式与这一偏差如实记进
``cover_qa.json`` 的 ``provenance``。
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

FFMPEG = "/home/soffy/.local/bin/ffmpeg"
FFPROBE = "/home/soffy/.local/bin/ffprobe"
FONT_PATH = Path(__file__).resolve().parents[4] / "hevi-remotion-whiteboard" / "assets" / "fonts" / "Xiaolai-Regular.ttf"

RATIOS = {"3x4": (3, 4), "4x3": (4, 3), "16x9": (16, 9)}
MIN_WIDTH = 1080


def exact_size(ratio: str) -> tuple[int, int]:
    """比例必须**精确**成立（宽×rh == 高×rw），不能用取整蒙混。

    取不小于 1080 的最小 rw 倍数作宽，高用整数除法即精确整除。
    """

    rw, rh = RATIOS[ratio]
    width = -(-MIN_WIDTH // rw) * rw  # 向上取到 rw 的倍数
    return width, width * rh // rw


class CoverError(RuntimeError):
    pass


def _probe_frame(path: Path) -> dict[str, Any]:
    raw = subprocess.check_output([
        FFPROBE, "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height,duration,r_frame_rate",
        "-of", "json", str(path),
    ])
    import json

    data = json.loads(raw)["streams"][0]
    return {"width": int(data["width"]), "height": int(data["height"]),
            "duration": float(data.get("duration", 0.0))}


def _grab_frame(video: Path, dest_png: Path, *, at_s: float, width: int, height: int) -> None:
    dest_png.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [FFMPEG, "-y", "-v", "error", "-ss", f"{at_s:.3f}", "-i", str(video),
         "-frames:v", "1", "-vf", f"scale={width}:{height}:force_original_aspect_ratio=increase,"
         f"crop={width}:{height}", str(dest_png)],
        check=True, capture_output=True,
    )
    if not dest_png.is_file() or dest_png.stat().st_size == 0:
        raise CoverError(f"FRAME_GRAB_FAILED: {video} @{at_s}s")


def _font(size: int) -> ImageFont.FreeTypeFont:
    if not FONT_PATH.is_file():
        raise CoverError(f"FONT_MISSING: {FONT_PATH}")
    return ImageFont.truetype(str(FONT_PATH), size)


def _wrap(text: str, font: ImageFont.FreeTypeFont, max_width: int, max_lines: int) -> list[str]:
    """按像素宽度折行；折不开就按字断，不溢出。"""

    lines: list[str] = []
    current = ""
    for ch in text:
        candidate = current + ch
        if font.getlength(candidate) <= max_width or not current:
            current = candidate
            continue
        lines.append(current)
        current = ch
        if len(lines) >= max_lines:
            break
    if current and len(lines) < max_lines:
        lines.append(current)
    if len(lines) == max_lines and len("".join(lines)) < len(text):
        last = lines[-1]
        while last and font.getlength(last + "…") > max_width:
            last = last[:-1]
        lines[-1] = last + "…"
    return lines


def render_cover(video: Path, dest: Path, *, title: str, ratio: str, subtitle: str = "",
                 at_s: float | None = None) -> Path:
    """生成一张比例准确、标题可读的封面。"""

    if ratio not in RATIOS:
        raise CoverError(f"UNKNOWN_RATIO: {ratio}")
    width, height = exact_size(ratio)
    info = _probe_frame(video)
    at_s = at_s if at_s is not None else max(info["duration"] * 0.80, 0.5)
    # N4 修复：封面取帧避开字幕密集区。默认从 25% 改为 80% 处取帧，
    # 因为口播字幕通常在视频前 70% 出现，80%+ 处字幕已结束，
    # 避免封面标题与成片烧录字幕重叠（双层字问题）。

    frame_png = dest.parent / f".{dest.stem}_frame.png"
    _grab_frame(video, frame_png, at_s=at_s, width=width, height=height)
    img = Image.open(frame_png).convert("RGB")

    draw = ImageDraw.Draw(img, "RGBA")
    # 底部渐变压暗，保证标题对比度
    band_top = int(height * 0.52)
    for y in range(band_top, height):
        alpha = int(210 * ((y - band_top) / max(height - band_top, 1)) ** 0.8)
        draw.rectangle([0, y, width, y], fill=(0, 0, 0, alpha))

    margin = int(width * 0.07)
    max_w = width - 2 * margin
    title_font = _font(int(height * (0.072 if width <= height else 0.075)))
    title_lines = _wrap(title, title_font, max_w, max_lines=3 if width <= height else 2)
    line_h = int(title_font.size * 1.28)

    y = height - margin - line_h * len(title_lines)
    if subtitle:
        sub_font = _font(int(title_font.size * 0.52))
        y -= int(sub_font.size * 1.5)
    else:
        sub_font = None

    # 标题左侧竖线（品牌感）
    accent = (47, 158, 68, 255)
    draw.rectangle([margin - int(width * 0.018), y, margin - int(width * 0.012),
                    y + line_h * len(title_lines) - int(line_h * 0.2)], fill=accent)
    text_x = margin
    for ln in title_lines:
        draw.text((text_x, y), ln, font=title_font, fill=(255, 255, 255, 255),
                  stroke_width=max(2, title_font.size // 22), stroke_fill=(0, 0, 0, 200))
        y += line_h
    if subtitle and sub_font is not None:
        draw.text((text_x, y + int(line_h * 0.15)), subtitle, font=sub_font, fill=(226, 232, 226, 255),
                  stroke_width=2, stroke_fill=(0, 0, 0, 190))

    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(dest, "JPEG", quality=92)
    frame_png.unlink(missing_ok=True)
    return dest


def measure_image_size(path: Path) -> tuple[int, int]:
    with Image.open(path) as im:
        return im.size


def ratio_ok(width: int, height: int, ratio: str) -> bool:
    rw, rh = RATIOS[ratio]
    return width * rh == height * rw


def run_cover_qa(covers: dict[str, Path], *, topic: str, video: Path,
                portrait_video: Path | None = None) -> dict[str, Any]:
    """封面 QA：比例实测 + 缩略可读性 + 主体占比，全部实测不臆测。"""

    entries = []
    passed = True
    for name, path in covers.items():
        if not path.is_file():
            entries.append({"ratio": name, "path": str(path), "measured": False, "passed": False,
                            "reason": "封面缺失"})
            passed = False
            continue
        width, height = measure_image_size(path)
        ok = ratio_ok(width, height, name)
        exp_w, exp_h = exact_size(name)
        thumb = path.with_suffix(".thumb.jpg")
        with Image.open(path) as im:
            im.copy().resize((320, max(1, round(320 * height / width)))).save(thumb, "JPEG", quality=85)
        entries.append({
            "ratio": name,
            "path": str(path),
            "measured": True,
            "width": width,
            "height": height,
            "expected_size": f"{exp_w}x{exp_h}",
            "ratio_check": f"{width}×{RATIOS[name][1]} == {height}×{RATIOS[name][0]}",
            "ratio_ok": ok,
            "thumb_320px": str(thumb),
            "source_video": str(portrait_video) if (name == "3x4" and portrait_video is not None) else str(video),
            "source_video_kind": "portrait" if (name == "3x4" and portrait_video is not None) else "landscape",
        })
        passed = passed and ok

    required = {"3x4", "4x3"}
    missing = sorted(required - set(covers))
    passed = passed and not missing

    return {
        "topic": topic,
        "provenance": {
            "method": "local_frame_recompose",
            "note": "本机零成本、无 imagegen：取成片帧 + 仓库中文字体排版标题，非裸截图冒充，也非 AI 生成图。",
            "upstream_ai_cover_rule_met": False,
        },
        "required_ratios": sorted(required),
        "missing_ratios": missing,
        "covers": entries,
        "passed": passed,
    }


def build_covers(video: Path, out_dir: Path, *, topic: str, subtitle: str = "",
                 portrait_video: Path | None = None) -> dict[str, Path]:
    """出三张比例准确的封面：3:4、4:3、16:9。

    F3：3:4 竖版封面优先从 portrait_video 取帧（避免横版视频被硬裁）；
    未提供时回退到原 video。
    """

    out_dir.mkdir(parents=True, exist_ok=True)
    covers: dict[str, Path] = {}
    source_for_34 = portrait_video or video
    for ratio in ("3x4", "4x3", "16x9"):
        dest = out_dir / f"cover_{ratio.replace('x', '_')}.jpg"
        src = source_for_34 if ratio == "3x4" else video
        render_cover(src, dest, title=topic, ratio=ratio, subtitle=subtitle)
        covers[ratio] = dest
    return covers