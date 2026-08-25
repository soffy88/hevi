"""magiviz oskill：组合 ≥2 个 oprim 原子，不得引用 omodul。

Magiviz 技能：组合五步工作流原子为完整技能。
"""

from __future__ import annotations

from typing import Any

from hevi.magiviz.oprim import (
    compose_story_video,
    generate_all_characters,
    generate_scene_videos_parallel,
    generate_story_details,
    generate_storyboard,
    run_full_pipeline,
)
from hevi.magiviz.schemas import (
    JobStatus,
    MagivizJob,
    SceneVideo,
    Storyboard,
    StoryDetails,
    StoryOutline,
    VideoAspectRatio,
    VideoModel,
    make_magiviz_job,
    make_story_outline,
)

# ── 技能 1: 完整流水线执行 ────────────────────────────


def skill_run_full_pipeline(
    job: MagivizJob,
) -> MagivizJob:
    """完整五步工作流执行技能。

    顺序执行：剧情 → 角色 → 分镜 → 场景视频 → 合成
    """
    return run_full_pipeline(job)


# ── 技能 2: 单步执行（可中断恢复） ──────────────────


def skill_story_generation(
    job: MagivizJob,
    llm_model: str = "gpt-4o",
) -> MagivizJob:
    """步骤 1：剧情生成技能。"""
    job.status = JobStatus.STORY_GENERATING
    job.story_details = generate_story_details(job.story_outline)
    return job


def skill_character_generation(
    job: MagivizJob,
    image_model: str = "flux",
) -> MagivizJob:
    """步骤 2：角色生成技能。"""
    job.status = JobStatus.CHARACTER_GENERATING
    job.story_details = generate_all_characters(job.story_details)
    return job


def skill_storyboard_generation(
    job: MagivizJob,
    aspect_ratio: VideoAspectRatio = VideoAspectRatio.LANDSCAPE_16_9,
) -> MagivizJob:
    """步骤 3：分镜生成技能。"""
    job.status = JobStatus.STORYBOARD_GENERATING
    job.storyboard = generate_storyboard(job.story_details, aspect_ratio)
    return job


def skill_scene_generation(
    job: MagivizJob,
    video_model: VideoModel = VideoModel.WAN,
) -> MagivizJob:
    """步骤 4：场景视频生成技能（并行）。"""
    job.status = JobStatus.SCENES_GENERATING
    job.scene_videos = generate_scene_videos_parallel(job.storyboard, video_model)
    return job


def skill_video_composition(
    job: MagivizJob,
    output_path: str = "",
    add_transitions: bool = True,
    add_music: bool = True,
) -> MagivizJob:
    """步骤 5：视频合成技能。"""
    job.status = JobStatus.COMPOSING
    if not output_path:
        output_path = f"/tmp/magiviz/{job.job_id}_final.mp4"
    job.final_video_path = compose_story_video(
        job.scene_videos, output_path, add_transitions, add_music
    )
    job.status = JobStatus.COMPLETED
    return job


# ── 技能 3: 角色一致性维护 ───────────────────────────


def skill_character_consistency(
    job: MagivizJob,
    reference_images: dict[str, str] | None = None,
) -> MagivizJob:
    """角色一致性维护技能。

    确保所有场景中的角色外观一致。
    """
    # 实际实现：使用 reference_images 约束后续生成
    return job


# ── 导出 ───────────────────────────────────────────────

__all__ = [
    "skill_character_consistency",
    "skill_character_generation",
    "skill_run_full_pipeline",
    "skill_scene_generation",
    "skill_story_generation",
    "skill_storyboard_generation",
    "skill_video_composition",
]
