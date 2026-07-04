from pathlib import Path

# 字幕烧录样式预设。ASS force_style 颜色为 &HAABBGGRR(alpha+BGR,非 RGB)。
# 双语场景(两行文本共一个 cue)靠 large_white/compact 的字号更能兼顾两行可读性。
_STYLE_PRESETS: dict[str, str] = {
    "bold_yellow": "FontSize=24,PrimaryColour=&H00FFFF,Bold=1",
    "large_white": "FontSize=28,PrimaryColour=&HFFFFFF,Outline=2,Bold=1",
    "compact": "FontSize=18,PrimaryColour=&HFFFFFF,MarginV=16",
}


def get_subtitle_filter(subtitle_path: Path, style: str = "default") -> str:
    """Get FFmpeg filter string for burning subtitles.

    Args:
        subtitle_path: Path to the .srt or .ass file.
        style: Subtitle style preset — "default" / "bold_yellow" / "large_white" / "compact".

    Returns:
        str: FFmpeg filter string.
    """
    # Escaping path for ffmpeg filter
    path_str = str(subtitle_path).replace("\\", "/").replace(":", "\\:")

    force_style = _STYLE_PRESETS.get(style)
    if force_style:
        return f"subtitles='{path_str}':force_style='{force_style}'"

    return f"subtitles='{path_str}'"
