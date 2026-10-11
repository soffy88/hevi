"""Subtitle styling and ASS / SRT generator for comic narration.

3O Pillar: oprim.comicnarr_subtitle
"""

from __future__ import annotations


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


def build_comic_ass(
    *,
    cues: list[tuple[float, float, str]],
    width: int = 1080,
    height: int = 1920,
    style_name: str = "comic_color",
    bubble: bool = False,
) -> str:
    """Build ASS subtitle script with comic styling (speech box or bottom banner)."""
    is_manga = "manga" in style_name.lower() or "bw" in style_name.lower()

    if bubble:
        # Comic dialogue bubble / banner box style
        # BorderStyle 3 = Opaque box with border
        if is_manga:
            # White speech box with black border and black text
            primary_colour = "&H00000000"  # Black text
            outline_colour = "&H00000000"  # Black box border
            back_colour = "&H00FFFFFF"     # White box background
        else:
            # Comic yellow speech box with dark border and deep blue/black text
            primary_colour = "&H00111111"  # Near-black text
            outline_colour = "&H00222222"  # Dark border
            back_colour = "&H0080EAFF"     # Light yellow / comic amber background
        border_style = 3
        outline_width = 3
        margin_v = 140
        font_size = 36
    else:
        # High readability bottom subtitle
        primary_colour = "&H00FFFFFF"      # Crisp white
        outline_colour = "&H00000000"      # Solid black border
        back_colour = "&H80000000"         # Semi-transparent drop shadow
        border_style = 1
        outline_width = 4
        margin_v = 120
        font_size = 40

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: ComicSub,WenQuanYi Zen Hei,{font_size},{primary_colour},&H000000FF,{outline_colour},{back_colour},-1,0,0,0,100,100,1,0,{border_style},{outline_width},2,2,60,60,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = []
    for st, et, text in cues:
        clean = text.strip().replace("\n", "\\N")
        if not clean:
            continue
        events.append(
            f"Dialogue: 0,{format_ass_time(st)},{format_ass_time(et)},ComicSub,,0,0,0,,{clean}"
        )

    return header + "\n".join(events) + "\n"


__all__ = [
    "build_comic_ass",
    "build_srt_content",
    "format_ass_time",
    "format_srt_time",
]
