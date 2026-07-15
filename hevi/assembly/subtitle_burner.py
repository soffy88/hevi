from pathlib import Path

# 字幕烧录必须指定一个含中日韩字形的字体,否则 libass 回退到无 CJK 字形的默认字体,
# 中文全渲染成豆腐块(□)——线上 director-pipeline 成片实测撞过。容器里装了
# fonts-noto-cjk(见 deploy/Dockerfile.api),family 名即 "Noto Sans CJK SC"。
_CJK_FONT = "Noto Sans CJK SC"

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

    # 任何 style(含 default)都强制带上 CJK 字体,否则中文烧成豆腐块。
    preset = _STYLE_PRESETS.get(style)
    force_style = f"FontName={_CJK_FONT}" + (f",{preset}" if preset else "")
    return f"subtitles='{path_str}':force_style='{force_style}'"
