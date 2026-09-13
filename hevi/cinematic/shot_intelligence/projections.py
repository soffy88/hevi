"""Renderer projections. They are lossy views of canonical ShotPlan only."""

from __future__ import annotations

from hevi.cinematic.shot_intelligence.beat_sync import beat_projection
from hevi.cinematic.shot_intelligence.models import ShotPlan, ShotRecipe


def to_remotion(plan: ShotPlan) -> dict[str, object]:
    return {"renderer": "remotion", "shots": [_shot(s) for s in plan.shots], "beat_sync": beat_projection(plan)}


def to_ffmpeg(plan: ShotPlan) -> dict[str, object]:
    return {"renderer": "ffmpeg", "segments": [_shot(s) for s in plan.shots], "beat_sync": beat_projection(plan)}


def to_generated_video_prompt(plan: ShotPlan) -> list[str]:
    return [f"{s.framing} {s.shot_type}, {s.camera_motion.name}, {s.lens_intent}" for s in plan.shots]


def _shot(recipe: ShotRecipe) -> dict[str, object]:
    return {"shot_type": recipe.shot_type, "framing": recipe.framing, "camera_motion": recipe.camera_motion.name, "duration_range_s": recipe.duration_range_s}
