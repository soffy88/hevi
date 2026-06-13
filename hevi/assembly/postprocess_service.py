from pathlib import Path
from typing import Any

from obase.ffmpeg import run

from hevi.assembly.aspect_ratio import AspectRatio, get_aspect_ratio_filter
from hevi.assembly.cover_extractor import extract_cover
from hevi.assembly.subtitle_burner import get_subtitle_filter
from hevi.assembly.transition import get_fade_in_out_filter


async def postprocess_video(
    *,
    config: Any = None,
    input_video: Path,
    aspect_ratios: list[str | AspectRatio],
    subtitle_path: Path | None = None,
    subtitle_style: str = "default",
    watermark: str | None = None,
    output_dir: Path,
) -> dict[str, Path]:
    """Orchestrate hevi post-processing for a long video.
    
    Produces multiple versions based on aspect ratios, burns subtitles,
    and extracts a cover.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    results: dict[str, Path] = {}
    
    # 1. Extract cover from original video
    cover_path = output_dir / "cover.jpg"
    await extract_cover(input_video, cover_path)
    results["cover"] = cover_path
    
    # 2. Process each aspect ratio
    for ratio_str in aspect_ratios:
        ratio = AspectRatio(ratio_str) if isinstance(ratio_str, str) else ratio_str
        version_name = ratio.value.replace(":", "_")
        output_path = output_dir / f"video_{version_name}.mp4"
        
        # Build filter chain
        filters = []
        
        # Aspect Ratio
        filters.append(get_aspect_ratio_filter(ratio))
        
        # Subtitles
        if subtitle_path:
            filters.append(get_subtitle_filter(subtitle_path, style=subtitle_style))
            
        # Fade in/out (as a basic 'transition' enhancement)
        filters.append(get_fade_in_out_filter(duration=10.0)) # dummy duration
        
        # Watermark (simple text overlay for now)
        if watermark:
            filters.append(f"drawtext=text='{watermark}':x=10:y=10:fontsize=24:fontcolor=white")
            
        filter_str = ",".join(filters)
        
        args = [
            "-i", str(input_video),
            "-vf", filter_str,
            "-c:a", "copy", # reuse audio
            str(output_path)
        ]
        
        await run(args=args, expected_output=output_path)
        results[ratio.value] = output_path
        
    return results
