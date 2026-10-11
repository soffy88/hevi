"""Subtitle styling and ASS / SRT generator for comic narration.

Subtitle colours / sizes come from the shared keyframe style presets so every
consumer renders readable, high-contrast captions.

3O Pillar: oprim.comicnarr_subtitle
"""

from __future__ import annotations

import re

from hevi.layer4_legacy.keyframe.oprim_impl.style_presets import (
    DEFAULT_STYLE,
    get_style_preset,
)

#: Maximum CJK characters per subtitle line before an explicit ``\N`` break.
DEFAULT_MAX_CHARS_PER_LINE = 16


def format_srt_time(seconds: float) -> str:
    """Format seconds into standard SRT timestamp HH:MM:SS,mmm."""
    sec = max(0.0, float(seconds))
    millis = int(round((sec - int(sec)) * 1000))
    s = int(sec) % 60
    m = (int(sec) // 60) % 60
    h = int(sec) // 3600
    return f"{h:02d}:{m:02d}:{s:02d},{millis:03d}"


def format_ass_time(seconds: float) -> str:
    """Format seconds into ASS timestamp H:MM:SS.cc."""
    sec = max(0.0, float(seconds))
    cs = int(round((sec - int(sec)) * 100))
    s = int(sec) % 60
    m = (int(sec) // 60) % 60
    h = int(sec) // 3600
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"


def build_srt_content(*, cues: list[tuple[float, float, str]]) -> str:
    """Build standard .srt text from cues [(start_s, end_s, text), ...]."""
    lines = []
    for idx, (st, et, text) in enumerate(cues, start=1):
        clean_text = text.strip()
        if not clean_text:
            continue
        lines.append(f"{idx}")
        lines.append(f"{format_srt_time(st)} --> {format_srt_time(et)}")
        lines.append(f"{clean_text}\n")
    return "\n".join(lines)


def wrap_subtitle_text(text: str, max_chars_per_line: int = DEFAULT_MAX_CHARS_PER_LINE) -> str:
    """Wrap a caption into lines no longer than *max_chars_per_line*.

    Breaks preferentially after Chinese punctuation, otherwise hard-wraps so
    that no character is ever dropped.  Returns ``\\N``-joined lines ready for
    the ASS ``Dialogue`` text field.
    """
    clean = re.sub(r"\s+", "", (text or "").strip())
    if not clean:
        return ""
    limit = max(4, int(max_chars_per_line))

    lines: list[str] = []
    remaining = clean
    while len(remaining) > limit:
        # Prefer to break just after punctuation within the limit window.
        window = remaining[: limit + 1]
        break_at = -1
        for i in range(len(window) - 1, 3, -1):
            if window[i - 1] in "，。！？、；：…,.!?;:":
                break_at = i
                break
        if break_at <= 0:
            break_at = limit
        lines.append(remaining[:break_at])
        remaining = remaining[break_at:]
    if remaining:
        lines.append(remaining)
    return "\\N".join(lines)


def build_comic_ass(
    *,
    cues: list[tuple[float, float, str]],
    width: int = 1080,
    height: int = 1920,
    style_name: str = DEFAULT_STYLE,
    bubble: bool = False,
) -> str:
    """Build an ASS subtitle script with high-contrast comic styling.

    ``bubble=False`` renders a bold bottom banner (white text, thick black
    outline).  ``bubble=True`` renders an opaque speech box whose text/box
    colours are guaranteed to contrast (manga: white on black, colour: black on
    amber).
    """
    preset = get_style_preset(style_name)

    if bubble:
        font_size = preset.bubble_font_size
        primary_colour = preset.bubble_primary
        outline_colour = preset.bubble_outline
        back_colour = preset.bubble_back
        border_style = 3  # opaque box
        outline_width = 3
        margin_v = max(preset.subtitle_margin_v, 160)
    else:
        font_size = max(preset.font_size, 52)
        primary_colour = preset.subtitle_primary
        outline_colour = preset.subtitle_outline
        back_colour = preset.subtitle_back
        border_style = preset.subtitle_border_style
        outline_width = max(preset.subtitle_outline_width, 4)
        margin_v = max(preset.subtitle_margin_v, 200)

    # Keep wrapped lines inside the frame with a small safety margin.
    max_chars = max(10, int(width / (font_size * 1.02)))
    if bubble:
        max_chars = max(10, int(width / (font_size * 1.15)))

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
ScaledBorderAndShadow: yes
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: ComicSub,{preset.font_name},{font_size},{primary_colour},&H000000FF,{outline_colour},{back_colour},-1,0,0,0,100,100,1,0,{border_style},{outline_width},2,2,50,50,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = []
    for st, et, text in cues:
        clean = wrap_subtitle_text(text, max_chars)
        if not clean:
            continue
        events.append(
            f"Dialogue: 0,{format_ass_time(st)},{format_ass_time(et)},ComicSub,,0,0,0,,{clean}"
        )

    return header + "\n".join(events) + "\n"


__all__ = [
    "DEFAULT_MAX_CHARS_PER_LINE",
    "build_comic_ass",
    "build_srt_content",
    "format_ass_time",
    "format_srt_time",
    "wrap_subtitle_text",
]
