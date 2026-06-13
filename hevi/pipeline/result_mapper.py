from typing import Any

from omodul.agentic_longvideo_pipeline import LongVideoResult


def map_longvideo_result(result: LongVideoResult) -> dict[str, Any]:
    """Map omodul.LongVideoResult to hevi app business result."""
    return {
        "id": f"hevi_{result.video_path.stem}",
        "url": str(result.video_path),
        "duration": result.duration_s,
        "metadata": {
            "chapters": result.chapters,
            "shots": result.shots_generated,
            "providers": result.provider_used,
        },
    }
