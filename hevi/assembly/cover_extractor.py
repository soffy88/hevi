from pathlib import Path

from oprim import ffmpeg_extract_cover


async def extract_cover(input_video: Path, output_path: Path, timestamp: float = 0.5) -> Path:
    """Extract a cover frame from the video at a specific timestamp.

    Uses oprim.ffmpeg_extract_cover canonical primitive.
    """
    return await ffmpeg_extract_cover(  # type: ignore[no-any-return]
        video_path=input_video,
        output_path=output_path,
        timestamp=timestamp,
    )