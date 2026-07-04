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
        # C3: 逐镜头选优明细(omodul v1.36.0),供 task_service 落 ShotState。
        # mode="json" → Path 转 str,可直接 JSONB 落库。老版 omodul 无 shots → 空列表。
        "shots": [r.model_dump(mode="json") for r in getattr(result, "shots", [])],
    }
