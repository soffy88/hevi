from pathlib import Path

from obase.ffmpeg import run


async def extract_cover(input_video: Path, output_path: Path, timestamp: float = 1.0) -> Path:
    """Extract a cover frame from the video at a specific timestamp."""
    args = [
        "-ss", str(timestamp),
        "-i", str(input_video),
        "-frames:v", "1",
        "-q:v", "2",
        str(output_path)
    ]
    await run(args=args, expected_output=output_path)
    return output_path
