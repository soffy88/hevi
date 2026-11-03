"""Exact-frame subtitle stitching (``image.native_subtitle_stitch``).

One local video in, one long 3:4 image out: a hero frame on top and
one subtitle strip per further timestamp, stacked with no gap. The
frames are real decoded frames from the caller's own video file;
nothing here downloads, transcribes, recognises text, or calls a
model. Two modes, kept strictly apart and never switched silently:

1. Native mode. The subtitle band is cropped out of the frame
   pixels and stacked at one uniform scale for every strip. No
   text is read, redrawn, translated, or rewritten. If the video
   has no burned-in subtitle in the band, native mode has nothing
   to show and the caller must pick script mode explicitly.
2. Script mode. Lines the caller has already reviewed are drawn
   onto real frames and the result is labelled on the picture
   itself as script subtitles drawn afterwards. The drawn words
   are never presented as the video's original subtitles.

Speaker discipline: one image holds one speaker's lines, unless
the caller declares a question-and-answer structure, in which
case exactly two lines from two speakers, adjacent in the source,
are allowed and both speakers are recorded in the manifest.
Watermarks, logos, and corner marks are never covered, blurred,
or removed; they stay in the frame pixels.

Rights gate: the caller must declare, for every render, where the
video came from and on what basis it may be processed and
published. No declaration, no render. This module cannot verify
a rights claim; it only refuses to work without one, so an
unreviewed claim is never mistaken for a checked one.

Failure contract: a missing video, an unreadable video, missing
or empty rights, an unknown or missing mode, timestamps that are
not strictly increasing or outside the video, more than seven
timestamps, mixed speakers, duplicate frames, a missing CJK
font in script mode, or an existing output without an explicit
overwrite all raise CapabilityError. Layout numbers are
heuristics, documented where they appear; they are not
measurements of readability.

Method ideas only were learned from chengyi-ai/native-subtitle-quote-image
(MIT, Copyright 2026 Cheng Yi, v2.10.3). No code, prompt, data
table, formula, or sentence was copied from that repository;
this module is written from scratch for hevi.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageStat

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

CAPABILITY_NAME = "image.native_subtitle_stitch"
_PREFIX = CAPABILITY_NAME + ": "

MAX_TIMESTAMPS = 7
MIN_TIMESTAMPS = 2
MIN_HEIGHT = 720
DEFAULT_BAND_TOP = 0.78
DEFAULT_BAND_BOTTOM = 0.96
OUT_WIDTH = 1440
OUT_HEIGHT = 1920
HERO_FRACTION_MIN = 0.48
HERO_FRACTION_MAX = 0.82
# Heuristic: each strip claims this share of the script canvas
# height; the hero takes what is left, clamped to the range above.
STRIP_SHARE = 0.075
# Heuristic: two frames whose small downscaled copies differ by
# less than this mean fraction are treated as the same picture.
DUPLICATE_THRESHOLD = 0.01
SCRIPT_LABEL = "脚本字幕 · 后期绘制"

_FONT_CANDIDATES = (
    "NotoSansCJK-Regular.ttc",
    "NotoSansCJK-Bold.ttc",
    "NotoSansCJK-Medium.ttc",
    "NotoSansCJK-DemiLight.ttc",
    "NotoSerifCJK-Regular.ttc",
    "wqy-zenhei.ttc",
    "WenQuanYi Zen Hei.ttc",
    "DejaVuSans.ttf",
)

_FONT_DIRS = (
    "/usr/share/fonts/opentype/noto",
    "/usr/share/fonts/truetype/noto",
    "/usr/share/fonts/truetype/wqy",
    "/usr/share/fonts/truetype/dejavu",
    "/usr/share/fonts",
)

_STRUCTURES = ("single_speaker", "question_answer")


def _fail(detail: str) -> CapabilityError:
    return CapabilityError(_PREFIX + detail)


def _is_num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def require_rights(rights: Any) -> dict[str, Any]:
    """Normalise a rights declaration, or refuse without one."""
    if not isinstance(rights, dict):
        raise _fail("rights must be an object with source and basis")
    source = rights.get("source")
    basis = rights.get("basis")
    if not isinstance(source, str) or not source.strip():
        raise _fail("rights.source must be a non-empty string naming the video source")
    if not isinstance(basis, str) or not basis.strip():
        raise _fail(
            "rights.basis must be a non-empty string stating the basis "
            "for processing and publishing this video"
        )
    publish = rights.get("publish", False)
    if not isinstance(publish, bool):
        raise _fail("rights.publish must be a boolean when supplied")
    return {"source": source.strip(), "basis": basis.strip(), "publish": publish}


def validate_timestamps(times: Any, duration_sec: Any) -> list[float]:
    """Validate the timestamp list against the video duration."""
    if not _is_num(duration_sec) or float(duration_sec) <= 0:
        raise _fail("duration_sec must be a positive number from a real probe")
    duration = float(duration_sec)
    if not isinstance(times, list) or not times:
        raise _fail("times must be a non-empty list of seconds")
    if len(times) < MIN_TIMESTAMPS:
        raise _fail(f"times needs at least {MIN_TIMESTAMPS} entries (hero plus one strip)")
    if len(times) > MAX_TIMESTAMPS:
        raise _fail(f"times allows at most {MAX_TIMESTAMPS} entries")
    checked: list[float] = []
    for value in times:
        if not _is_num(value):
            raise _fail("every time must be a number of seconds")
        checked.append(float(value))
    for index, value in enumerate(checked):
        if value < 0:
            raise _fail(f"times[{index}] is negative")
        if value >= duration:
            raise _fail(f"times[{index}] {value} is at or past the duration {duration}")
        if index and checked[index] <= checked[index - 1] + 1e-6:
            raise _fail("times must be strictly increasing")
    return checked


def check_speakers(lines: list[dict[str, Any]], structure: str) -> list[str]:
    """Return the distinct speakers, enforcing one speaker per image.

    The question_answer structure is the single exception: exactly
    two lines from exactly two speakers. Anything else with more
    than one speaker is refused, because a reader will credit
    every strip to the hero speaker.
    """
    if structure not in _STRUCTURES:
        raise _fail(f"structure must be one of {list(_STRUCTURES)}")
    speakers: list[str] = []
    for line in lines:
        speaker = line.get("speaker", "")
        if isinstance(speaker, str) and speaker.strip() and speaker.strip() not in speakers:
            speakers.append(speaker.strip())
    if structure == "question_answer":
        if len(lines) != 2:
            raise _fail("question_answer structure needs exactly two lines")
        if len(speakers) != 2:
            raise _fail("question_answer structure needs exactly two speakers")
    elif len(speakers) > 1:
        raise _fail(f"mixed speakers in one image: {speakers}")
    return speakers


def validate_lines(
    lines: Any, times: list[float], mode: str, structure: str
) -> list[dict[str, Any]]:
    """Validate reviewed lines for script mode; refuse them in native mode."""
    if mode == "native":
        if lines not in (None, []):
            raise _fail(
                "native mode draws no text; supplying script lines "
                "with native mode is a mode confusion, pick script mode"
            )
        return []
    if mode != "script":
        raise _fail("mode must be 'native' or 'script'")
    if not isinstance(lines, list) or len(lines) != len(times):
        raise _fail("script mode needs one reviewed line per timestamp")
    checked: list[dict[str, Any]] = []
    for index, line in enumerate(lines):
        if not isinstance(line, dict):
            raise _fail(f"lines[{index}] must be an object")
        stamp = line.get("t")
        if not _is_num(stamp) or abs(float(stamp) - times[index]) > 1e-6:
            raise _fail(f"lines[{index}].t must equal times[{index}]")
        text = line.get("text")
        if not isinstance(text, str) or not text.strip():
            raise _fail(f"lines[{index}].text must be reviewed, non-empty text")
        speaker = line.get("speaker", "")
        if speaker is not None and not isinstance(speaker, str):
            raise _fail(f"lines[{index}].speaker must be a string when supplied")
        checked.append(
            {"t": float(stamp), "text": text.strip(), "speaker": str(speaker or "").strip()}
        )
    check_speakers(checked, structure)
    return checked


def script_layout(
    strip_count: int,
    hero_fraction: float | None = None,
    out_width: int = OUT_WIDTH,
    out_height: int = OUT_HEIGHT,
) -> dict[str, Any]:
    """Hero/strip heights for the fixed script canvas.

    The hero share is one minus a fixed share per strip, clamped
    to the documented range. A caller-supplied share is clamped
    the same way and the clamping is reported, never silent.
    Strip heights split the remainder evenly; leftover pixels go
    to the earliest strips so the heights always sum exactly.
    """
    if strip_count < 1:
        raise _fail("script layout needs at least one strip")
    requested = hero_fraction
    if requested is None:
        fraction = 1.0 - strip_count * STRIP_SHARE
    else:
        if not _is_num(requested):
            raise _fail("hero_fraction must be a number")
        fraction = float(requested)
    clamped = fraction < HERO_FRACTION_MIN or fraction > HERO_FRACTION_MAX
    fraction = min(HERO_FRACTION_MAX, max(HERO_FRACTION_MIN, fraction))
    hero_height = int(round(out_height * fraction))
    rest = out_height - hero_height
    base, extra = divmod(rest, strip_count)
    heights = [base + (1 if i < extra else 0) for i in range(strip_count)]
    return {
        "hero_fraction": fraction,
        "hero_fraction_requested": requested,
        "hero_fraction_clamped": clamped,
        "hero_height": hero_height,
        "strip_heights": heights,
        "out_width": out_width,
        "out_height": out_height,
    }


def native_layout(
    source_width: int,
    source_height: int,
    strip_count: int,
    band_top: float = DEFAULT_BAND_TOP,
    band_bottom: float = DEFAULT_BAND_BOTTOM,
    out_width: int = OUT_WIDTH,
) -> dict[str, Any]:
    """Uniform-scale geometry for native mode.

    Every part is scaled by the same factor, so the hero and the
    strips keep one scale and no part is enlarged on its own.
    The total height follows the source; it is not stretched to
    a fixed canvas.
    """
    if source_width <= 0 or source_height <= 0:
        raise _fail("source dimensions must be positive")
    if not 0 <= band_top < band_bottom <= 1:
        raise _fail("band needs 0 <= band_top < band_bottom <= 1")
    scale = out_width / source_width
    hero_height = int(round(band_bottom * source_height * scale))
    strip_height = int(round((band_bottom - band_top) * source_height * scale))
    return {
        "scale": scale,
        "hero_height": hero_height,
        "strip_height": strip_height,
        "total_height": hero_height + strip_count * strip_height,
        "out_width": out_width,
    }


def find_cjk_font(explicit: str | None = None) -> Path | None:
    """First usable CJK-capable font on this system, or None.

    Nothing is downloaded. A caller-supplied path wins when it
    exists; otherwise the well-known system locations are tried
    in order. Returning None is a signal to refuse script mode,
    not to fall back to a bitmap font that cannot draw CJK.
    """
    if explicit:
        candidate = Path(explicit)
        if candidate.is_file():
            return candidate
        raise _fail(f"font_path does not exist: {explicit}")
    seen: set[str] = set()
    for directory in _FONT_DIRS:
        root = Path(directory)
        if not root.is_dir():
            continue
        for name in _FONT_CANDIDATES:
            candidate = root / name
            key = str(candidate)
            if key in seen:
                continue
            seen.add(key)
            if candidate.is_file():
                return candidate
    home = Path.home() / ".local" / "share" / "fonts"
    for candidate in sorted(home.rglob("*.ttc")) + sorted(home.rglob("*.ttf")):
        if "CJK" in candidate.name or "ZenHei" in candidate.name or "wqy" in candidate.name.lower():
            return candidate
    return None

def _resample() -> int:
    resampling = getattr(Image, "Resampling", None)
    if resampling is not None:
        return int(resampling.LANCZOS)
    return int(Image.LANCZOS)


def frames_are_duplicates(
    first: Image.Image, second: Image.Image, threshold: float = DUPLICATE_THRESHOLD
) -> bool:
    """Heuristic duplicate check on small downscaled copies.

    Both frames are reduced to the same small grey copy and the
    mean absolute difference is compared with the threshold.
    Cropping, colour grading, and small motion all move the
    score; the value is a tripwire for a frozen picture, not a
    proof that two frames are identical.
    """
    small_a = first.convert("L").resize((64, 36), _resample())
    small_b = second.convert("L").resize((64, 36), _resample())
    diff = ImageChops.difference(small_a, small_b)
    mean = ImageStat.Stat(diff).mean[0] / 255.0
    return mean < threshold


def check_frames_distinct(
    frames: list[Image.Image], times: list[float], threshold: float = DUPLICATE_THRESHOLD
) -> None:
    """Refuse consecutive frames that look like the same picture."""
    for index in range(1, len(frames)):
        if frames_are_duplicates(frames[index - 1], frames[index], threshold):
            raise _fail(
                f"frames at {times[index - 1]}s and {times[index]}s look "
                "near-identical; refusing a frozen-picture stitch"
            )


def _crop_band(frame: Image.Image, top: float, bottom: float) -> Image.Image:
    height = frame.height
    return frame.crop((0, int(round(top * height)), frame.width, int(round(bottom * height))))


def _resize_cover(image: Image.Image, width: int, height: int) -> Image.Image:
    """Fill a box by scaling then centre-cropping; never stretch."""
    scale = max(width / image.width, height / image.height)
    grown = image.resize(
        (max(1, int(round(image.width * scale))), max(1, int(round(image.height * scale)))),
        _resample(),
    )
    left = (grown.width - width) // 2
    top = (grown.height - height) // 2
    return grown.crop((left, top, left + width, top + height))


def _wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    """Greedy character wrap measured with the real font."""
    lines: list[str] = []
    current = ""
    for char in text:
        trial = current + char
        probe = Image.new("RGB", (8, 8))
        width = ImageDraw.Draw(probe).textlength(trial, font=font)
        if width <= max_width or not current:
            current = trial
        else:
            lines.append(current)
            current = char
    if current:
        lines.append(current)
    return lines


def _fit_font(
    text: str, font_path: Path, max_width: int, start_size: int, min_size: int = 24
) -> ImageFont.FreeTypeFont:
    size = start_size
    while size > min_size:
        font = ImageFont.truetype(str(font_path), size)
        probe = Image.new("RGB", (8, 8))
        if ImageDraw.Draw(probe).textlength(text, font=font) <= max_width:
            return font
        size -= 4
    return ImageFont.truetype(str(font_path), min_size)


def _draw_lines(
    canvas: Image.Image,
    box: tuple[int, int, int, int],
    text: str,
    font_path: Path,
    start_size: int,
) -> list[str]:
    """Draw wrapped text inside a box, white with a dark outline."""
    left, top, right, bottom = box
    max_width = right - left
    font = _fit_font(text, font_path, max_width, start_size)
    lines = _wrap_text(text, font, max_width)
    draw = ImageDraw.Draw(canvas)
    ascent, descent = font.getmetrics()
    line_height = ascent + descent + 6
    total = line_height * len(lines)
    y = top + max(0, (bottom - top - total) // 2)
    stroke = max(2, start_size // 14)
    for line in lines:
        draw.text((left, y), line, font=font, fill=(255, 255, 255), stroke_width=stroke,
                  stroke_fill=(0, 0, 0))
        y += line_height
    return lines


def build_stitched_image(
    mode: str,
    frames: list[Image.Image],
    lines: list[dict[str, Any]] | None = None,
    *,
    band_top: float = DEFAULT_BAND_TOP,
    band_bottom: float = DEFAULT_BAND_BOTTOM,
    out_width: int = OUT_WIDTH,
    out_height: int = OUT_HEIGHT,
    hero_fraction: float | None = None,
    font_path: Path | None = None,
    structure: str = "single_speaker",
) -> Image.Image:
    """Assemble the stitched image from already-extracted frames.

    This function does no video work, so it is testable with
    synthetic frames. Native mode stacks one uniform scale;
    script mode fills a fixed 3:4 canvas and labels itself.
    """
    if len(frames) < MIN_TIMESTAMPS:
        raise _fail("need at least two frames to stitch")
    width, height = frames[0].size
    for frame in frames:
        if frame.size != (width, height):
            raise _fail("all extracted frames must share dimensions")
    if mode == "native":
        geometry = native_layout(width, height, len(frames) - 1, band_top, band_bottom, out_width)
        parts: list[Image.Image] = []
        hero = _crop_band(frames[0], 0.0, band_bottom)
        parts.append(hero.resize((out_width, geometry["hero_height"]), _resample()))
        for frame in frames[1:]:
            band = _crop_band(frame, band_top, band_bottom)
            parts.append(band.resize((out_width, geometry["strip_height"]), _resample()))
        canvas = Image.new("RGB", (out_width, geometry["total_height"]), (0, 0, 0))
        y = 0
        for part in parts:
            canvas.paste(part, (0, y))
            y += part.height
        return canvas
    if mode != "script":
        raise _fail("mode must be 'native' or 'script'")
    if lines is None or len(lines) != len(frames):
        raise _fail("script mode needs one reviewed line per frame")
    if font_path is None:
        raise _fail("script mode needs a CJK font; none was found on this system")
    geometry = script_layout(len(frames) - 1, hero_fraction, out_width, out_height)
    canvas = Image.new("RGB", (out_width, out_height), (0, 0, 0))
    hero = _resize_cover(frames[0], out_width, geometry["hero_height"])
    canvas.paste(hero, (0, 0))
    label_font = ImageFont.truetype(str(font_path), 30)
    overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    tag_draw = ImageDraw.Draw(overlay)
    label = SCRIPT_LABEL
    pad = 16
    text_width = int(tag_draw.textlength(label, font=label_font))
    tag_box = (28, 28, 28 + text_width + 2 * pad, 28 + 58)
    tag_draw.rounded_rectangle(tag_box, radius=12, fill=(0, 0, 0, 170))
    canvas.paste(Image.alpha_composite(canvas.convert("RGBA"), overlay).convert("RGB"), (0, 0))
    tag = ImageDraw.Draw(canvas)
    tag.text((tag_box[0] + pad, tag_box[1] + 12), label, font=label_font, fill=(255, 255, 255))
    # The hero line is drawn on the hero frame itself, so every
    # reviewed line stays visible: the hero carries lines[0] and
    # each strip carries one later line.
    hero_line = lines[0]
    hero_spoken = hero_line["text"]
    if hero_line.get("speaker"):
        hero_spoken = f"{hero_line['speaker']}: {hero_spoken}"
    caption_height = min(200, geometry["hero_height"] // 4)
    _draw_lines(
        canvas,
        (48, geometry["hero_height"] - caption_height - 16,
         out_width - 48, geometry["hero_height"] - 16),
        hero_spoken,
        font_path,
        56,
    )
    y = geometry["hero_height"]
    previous_speaker = hero_line.get("speaker", "")
    for index, line in enumerate(lines[1:], start=1):
        strip_height = geometry["strip_heights"][index - 1]
        strip = _resize_cover(frames[index], out_width, strip_height)
        canvas.paste(strip, (0, y))
        speaker = line.get("speaker", "")
        spoken = line["text"]
        if speaker and speaker != previous_speaker:
            spoken = f"{speaker}: {spoken}"
        previous_speaker = speaker
        _draw_lines(
            canvas,
            (48, y + 8, out_width - 48, y + strip_height - 8),
            spoken,
            font_path,
            max(28, strip_height // 3),
        )
        y += strip_height
    return canvas


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(command, capture_output=True, text=True, timeout=120)
    except FileNotFoundError as exc:
        raise _fail(f"required tool not found: {command[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise _fail(f"tool timed out: {command[0]}") from exc


def probe_video(
    video_path: Path, *, ffprobe_exe: str = "ffprobe", ffmpeg_exe: str = "ffmpeg"
) -> dict[str, Any]:
    """Probe width, height, and duration with ffprobe, ffmpeg as fallback."""
    if not video_path.is_file():
        raise _fail(f"video file not found: {video_path}")
    if shutil.which(ffprobe_exe):
        result = _run([
            ffprobe_exe, "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-show_entries", "format=duration",
            "-of", "json", str(video_path),
        ])
        if result.returncode == 0:
            try:
                data = json.loads(result.stdout)
                stream = (data.get("streams") or [{}])[0]
                width = int(stream["width"])
                height = int(stream["height"])
                duration = float(data["format"]["duration"])
                return {"width": width, "height": height, "duration_sec": duration}
            except (ValueError, KeyError, TypeError, IndexError):
                pass
    result = _run([ffmpeg_exe, "-hide_banner", "-i", str(video_path)])
    text = result.stderr or ""
    duration_match = re.search(r"Duration: (\d+):(\d+):([\d.]+)", text)
    size_match = re.search(r"Video:.*?, (\d+)x(\d+)", text)
    if not duration_match or not size_match:
        raise _fail("could not probe video dimensions or duration")
    hours, minutes, seconds = duration_match.groups()
    duration = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    return {
        "width": int(size_match.group(1)),
        "height": int(size_match.group(2)),
        "duration_sec": duration,
    }


def extract_frame(
    video_path: Path, seconds: float, out_path: Path, *, ffmpeg_exe: str = "ffmpeg"
) -> Path:
    """Extract one decoded frame; seek flag goes before the input."""
    if shutil.which(ffmpeg_exe) is None:
        raise _fail("ffmpeg is required to extract frames")
    result = _run([
        ffmpeg_exe, "-hide_banner", "-loglevel", "error", "-y",
        "-ss", f"{seconds:.3f}", "-i", str(video_path),
        "-frames:v", "1", "-q:v", "2", str(out_path),
    ])
    if result.returncode != 0 or not out_path.is_file():
        raise _fail(f"ffmpeg could not extract a frame at {seconds}s")
    try:
        with Image.open(out_path) as probe:
            probe.verify()
    except Exception as exc:
        raise _fail(f"extracted frame at {seconds}s is not a readable image") from exc
    return out_path


def build_contact_sheet(image_paths: list[Path], out_path: Path, thumb_width: int = 360) -> Path:
    """A small grid preview of the finished images."""
    columns = 4
    thumbs: list[Image.Image] = []
    for path in image_paths:
        with Image.open(path) as source:
            thumb = source.convert("RGB")
            scale = thumb_width / thumb.width
            thumbs.append(thumb.resize((thumb_width, int(round(thumb.height * scale))), _resample()))
    if not thumbs:
        raise _fail("contact sheet needs at least one image")
    row_height = max(thumb.height for thumb in thumbs)
    rows = (len(thumbs) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * thumb_width, rows * row_height), (16, 16, 16))
    for index, thumb in enumerate(thumbs):
        sheet.paste(thumb, ((index % columns) * thumb_width, (index // columns) * row_height))
    sheet.save(out_path, format="JPEG", quality=85)
    return out_path


def _safe_output_name(name: Any) -> str:
    if not isinstance(name, str) or not name.strip():
        return "subtitle_quote.jpg"
    if "/" in name or "\\" in name or name.strip() in (".", ".."):
        raise _fail("output_name must be a plain file name, not a path")
    if not name.lower().endswith((".jpg", ".jpeg")):
        raise _fail("output_name must end in .jpg")
    return name.strip()


def stitch_video(
    *,
    video_path: str,
    mode: str,
    times: list[Any],
    rights: dict[str, Any],
    out_dir: Path,
    lines: list[dict[str, Any]] | None = None,
    structure: str = "single_speaker",
    band_top: float = DEFAULT_BAND_TOP,
    band_bottom: float = DEFAULT_BAND_BOTTOM,
    hero_fraction: float | None = None,
    out_width: int = OUT_WIDTH,
    out_height: int = OUT_HEIGHT,
    allow_low_resolution: bool = False,
    overwrite: bool = False,
    font_path: str | None = None,
    output_name: str = "subtitle_quote.jpg",
    ffmpeg_exe: str = "ffmpeg",
    ffprobe_exe: str = "ffprobe",
) -> dict[str, Any]:
    """Run the full local stitch and return the manifest payload."""
    if mode not in ("native", "script"):
        raise _fail("mode must be 'native' or 'script'")
    if structure not in _STRUCTURES:
        raise _fail(f"structure must be one of {list(_STRUCTURES)}")
    if not 0 <= band_top < band_bottom <= 1:
        raise _fail("band needs 0 <= band_top < band_bottom <= 1")
    if out_width <= 0 or out_height <= 0:
        raise _fail("output dimensions must be positive")
    if mode == "script" and abs(out_width / out_height - 0.75) > 0.01:
        raise _fail("script output must keep the 3:4 canvas ratio")
    checked_rights = require_rights(rights)
    source = Path(video_path)
    probe = probe_video(source, ffprobe_exe=ffprobe_exe, ffmpeg_exe=ffmpeg_exe)
    checked_times = validate_timestamps(times, probe["duration_sec"])
    checked_lines = validate_lines(lines, checked_times, mode, structure)
    warnings: list[str] = []
    if probe["height"] < MIN_HEIGHT and not allow_low_resolution:
        raise _fail(
            f"source height is {probe['height']}px, below {MIN_HEIGHT}px; "
            "pass allow_low_resolution=true only after confirming with the user"
        )
    if probe["height"] < MIN_HEIGHT:
        warnings.append(f"low source height {probe['height']}px was explicitly allowed")
    if probe["width"] < out_width:
        warnings.append("output is upscaled from the source width; this is not real clarity")
    resolved_font: Path | None = None
    if mode == "script":
        resolved_font = find_cjk_font(font_path)
        if resolved_font is None:
            raise _fail("script mode needs a CJK font and none was found on this system")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    image_name = _safe_output_name(output_name)
    image_path = out_dir / image_name
    manifest_path = out_dir / "subtitle_stitch_manifest.json"
    sheet_path = out_dir / "subtitle_stitch_contact.jpg"
    existing = [p for p in (image_path, manifest_path, sheet_path) if p.exists()]
    if existing and not overwrite:
        raise _fail(f"output already exists, refusing without overwrite: {[str(p) for p in existing]}")
    frames: list[Image.Image] = []
    with tempfile.TemporaryDirectory(prefix="subtitle_stitch_") as tmp_name:
        tmp_dir = Path(tmp_name)
        for index, stamp in enumerate(checked_times):
            frame_path = tmp_dir / f"frame_{index}.png"
            extract_frame(source, stamp, frame_path, ffmpeg_exe=ffmpeg_exe)
            frames.append(Image.open(frame_path).convert("RGB").copy())
    try:
        check_frames_distinct(frames, checked_times)
        image = build_stitched_image(
            mode, frames, checked_lines,
            band_top=band_top, band_bottom=band_bottom,
            out_width=out_width, out_height=out_height,
            hero_fraction=hero_fraction, font_path=resolved_font,
            structure=structure,
        )
        image.save(image_path, format="JPEG", quality=90)
        build_contact_sheet([image_path], sheet_path)
    finally:
        for frame in frames:
            frame.close()
    speakers = check_speakers(checked_lines, structure) if checked_lines else []
    manifest = {
        "capability": CAPABILITY_NAME,
        "mode": mode,
        "structure": structure,
        "video_path": str(source),
        "video_width": probe["width"],
        "video_height": probe["height"],
        "duration_sec": probe["duration_sec"],
        "times": checked_times,
        "band_top": band_top,
        "band_bottom": band_bottom,
        "hero_fraction": hero_fraction,
        "out_width": image.width,
        "out_height": image.height,
        "requested_width": out_width,
        "requested_height": out_height,
        "lines": checked_lines,
        "speakers": speakers,
        "rights": checked_rights,
        "script_labelled": mode == "script",
        "warnings": warnings,
        "image": str(image_path),
        "contact_sheet": str(sheet_path),
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest

def _render(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    video_path = params.get("video_path")
    if not isinstance(video_path, str) or not video_path.strip():
        raise _fail("video_path must be a non-empty local file path")
    mode = params.get("mode")
    if mode not in ("native", "script"):
        raise _fail("mode must be 'native' or 'script'")
    kwargs: dict[str, Any] = {
        "video_path": video_path,
        "mode": mode,
        "times": params.get("times"),
        "rights": params.get("rights"),
        "out_dir": out_dir,
    }
    if params.get("lines") is not None:
        kwargs["lines"] = list(params["lines"])
    if params.get("structure"):
        kwargs["structure"] = str(params["structure"])
    if params.get("band_top") is not None:
        kwargs["band_top"] = float(params["band_top"])
    if params.get("band_bottom") is not None:
        kwargs["band_bottom"] = float(params["band_bottom"])
    if params.get("hero_fraction") is not None:
        kwargs["hero_fraction"] = float(params["hero_fraction"])
    if params.get("out_width") is not None:
        kwargs["out_width"] = int(params["out_width"])
    if params.get("out_height") is not None:
        kwargs["out_height"] = int(params["out_height"])
    if params.get("allow_low_resolution") is not None:
        kwargs["allow_low_resolution"] = bool(params["allow_low_resolution"])
    if params.get("overwrite") is not None:
        kwargs["overwrite"] = bool(params["overwrite"])
    if params.get("font_path"):
        kwargs["font_path"] = str(params["font_path"])
    if params.get("output_name"):
        kwargs["output_name"] = str(params["output_name"])
    manifest = stitch_video(**kwargs)
    image_path = Path(manifest["image"])
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(image_path),
        qa={
            "image_jpg": str(image_path),
            "manifest_json": str(out_dir / "subtitle_stitch_manifest.json"),
            "contact_sheet": str(out_dir / "subtitle_stitch_contact.jpg"),
            "mode": manifest["mode"],
            "times": manifest["times"],
            "speakers": manifest["speakers"],
            "warnings": manifest["warnings"],
            "out_width": manifest["out_width"],
            "out_height": manifest["out_height"],
        },
    )


def register_native_subtitle_stitch_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name=CAPABILITY_NAME,
            kind="shot",
            aspects=["3:4"],
            params_schema={
                "type": "object",
                "properties": {
                    "video_path": {"type": "string"},
                    "mode": {"type": "string", "enum": ["native", "script"]},
                    "times": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 7},
                    "rights": {"type": "object"},
                    "lines": {"type": "array", "items": {"type": "object"}},
                    "structure": {"type": "string", "enum": ["single_speaker", "question_answer"]},
                    "band_top": {"type": "number", "minimum": 0, "maximum": 1},
                    "band_bottom": {"type": "number", "minimum": 0, "maximum": 1},
                    "hero_fraction": {"type": "number", "exclusiveMinimum": 0, "maximum": 1},
                    "out_width": {"type": "integer", "exclusiveMinimum": 0},
                    "out_height": {"type": "integer", "exclusiveMinimum": 0},
                    "allow_low_resolution": {"type": "boolean"},
                    "overwrite": {"type": "boolean"},
                    "font_path": {"type": "string"},
                    "output_name": {"type": "string"},
                },
                "required": ["video_path", "mode", "times", "rights"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Exact-frame subtitle stitching from a local video file "
                "into one 3:4 long image (hero frame plus subtitle strips, "
                "no gap). Native mode crops only the burned-in subtitle "
                "band at one uniform scale and draws no text; script mode "
                "draws already-reviewed lines onto real frames and labels "
                "the picture as script subtitles. A rights declaration "
                "is required, speakers are checked per image, duplicate "
                "frames abort, and sources below 720p need explicit "
                "confirmation. Local files only: no downloads, no "
                "transcription, no OCR, no network."
            ),
            line="edit",
        )
    )
    return [CAPABILITY_NAME]


register_native_subtitle_stitch_capabilities_once()
