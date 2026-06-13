from pathlib import Path


def get_subtitle_filter(subtitle_path: Path, style: str = "default") -> str:
    """Get FFmpeg filter string for burning subtitles.
    
    Args:
        subtitle_path: Path to the .srt or .ass file.
        style: Subtitle style preset.
    
    Returns:
        str: FFmpeg filter string.
    """
    # Escaping path for ffmpeg filter
    path_str = str(subtitle_path).replace("\\", "/").replace(":", "\\:")
    
    if style == "bold_yellow":
        return f"subtitles='{path_str}':force_style='FontSize=24,PrimaryColour=&H00FFFF,Bold=1'"
    
    return f"subtitles='{path_str}'"
