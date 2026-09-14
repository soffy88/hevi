"""magiviz omodul：文本规划/任务编排，供 studio/production 工作流调用。

Magiviz 规划：五步工作流规划 + 可中断恢复。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from hevi.magiviz.oprim import run_full_pipeline
from hevi.magiviz.schemas import (
    MagivizJob,
    StoryOutline,
    VideoAspectRatio,
    VideoModel,
    make_magiviz_job,
    make_story_outline,
)

# ── 完整流水线规划 ────────────────────────────────────


def plan_magiviz_pipeline(
    story_outline: StoryOutline,
    user_id: str = "",
    preferred_models: list[str] | None = None,
) -> dict[str, Any]:
    """规划完整的 Magiviz 五步工作流。"""
    job = make_magiviz_job(story_outline, user_id)

    if preferred_models:
        job.preferred_models = [VideoModel(m) for m in preferred_models]

    return {
        "pipeline": "magiviz",
        "job_id": job.job_id,
        "story_outline": story_outline.model_dump(),
        "preferred_models": [m.value for m in job.preferred_models],
        "steps": [
            {"step": "story_generation", "skill": "skill_story_generation", "parallel": False},
            {"step": "character_generation", "skill": "skill_character_generation", "parallel": True},
            {"step": "storyboard_generation", "skill": "skill_storyboard_generation", "parallel": True},
            {"step": "scene_generation", "skill": "skill_scene_generation", "parallel": True},
            {"step": "video_composition", "skill": "skill_video_composition", "parallel": False},
        ],
        "checkpoint_policy": "after_each_step",
        "estimated_duration_minutes": 30,
    }


def plan_story_generation(
    outline: StoryOutline,
    llm_model: str = "gpt-4o",
) -> dict[str, Any]:
    """规划剧情生成阶段。"""
    return {
        "stage": "story_generation",
        "llm_model": llm_model,
        "outputs": ["story_details", "scenes", "characters", "dialogues", "director_notes"],
    }


def plan_character_generation(
    story_details: dict[str, Any],
    image_model: str = "flux",
) -> dict[str, Any]:
    """规划角色生成阶段。"""
    return {
        "stage": "character_generation",
        "image_model": image_model,
        "character_count": len(story_details.get("characters", [])),
        "outputs": ["character_images", "consistency_prompts"],
    }


def plan_storyboard_generation(
    story_details: dict[str, Any],
    aspect_ratio: str = "16:9",
) -> dict[str, Any]:
    """规划分镜生成阶段。"""
    scene_count = len(story_details.get("scenes", []))
    return {
        "stage": "storyboard_generation",
        "scene_count": scene_count,
        "estimated_frames": scene_count * 3,
        "aspect_ratio": aspect_ratio,
        "outputs": ["storyboard_frames", "visual_prompts"],
    }


def plan_scene_generation(
    storyboard: dict[str, Any],
    video_model: str = "wan",
) -> dict[str, Any]:
    """规划场景视频生成阶段。"""
    frame_count = len(storyboard.get("frames", []))
    return {
        "stage": "scene_generation",
        "video_model": video_model,
        "frame_count": frame_count,
        "parallel": True,
        "outputs": ["scene_videos"],
    }


def plan_video_composition(
    scene_videos: list[dict[str, Any]],
) -> dict[str, Any]:
    """规划视频合成阶段。"""
    return {
        "stage": "video_composition",
        "scene_count": len(scene_videos),
        "outputs": ["final_video"],
    }


# ── 完整执行器 ────────────────────────────────────────


async def execute_magiviz_plan(
    job: MagivizJob,
) -> MagivizJob:
    """执行完整的 Magiviz 计划。"""
    return run_full_pipeline(job)


# ── 导出 ───────────────────────────────────────────────

__all__ = [
    "execute_magiviz_plan",
    "plan_character_generation",
    "plan_magiviz_pipeline",
    "plan_scene_generation",
    "plan_story_generation",
    "plan_storyboard_generation",
    "plan_video_composition",
]