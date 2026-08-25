"""magiviz 3O 包：Open-Magiviz AI 视频创作平台能力内部化。

核心五步工作流：剧情生成 → 角色设计 → 分镜生成 → 场景视频 → 视频合成
支持：多模型路由、角色一致性、并行分镜/场景生成、可中断恢复
"""

from __future__ import annotations

# ── Omodul ──
from hevi.magiviz.omodul import (
    execute_magiviz_plan,
    plan_character_generation,
    plan_magiviz_pipeline,
    plan_scene_generation,
    plan_story_generation,
    plan_storyboard_generation,
    plan_video_composition,
)

# ── Oprim ──
from hevi.magiviz.oprim import (
    compose_story_video,
    generate_all_characters,
    generate_character_image,
    generate_scene_video,
    generate_scene_videos_parallel,
    generate_story_details,
    generate_storyboard,
    generate_storyboard_frame,
    run_full_pipeline,
)

# ── Oskill ──
from hevi.magiviz.oskill import (
    skill_character_consistency,
    skill_character_generation,
    skill_run_full_pipeline,
    skill_scene_generation,
    skill_story_generation,
    skill_storyboard_generation,
    skill_video_composition,
)

# ── Schemas ──
from hevi.magiviz.schemas import (
    CharacterDesign,
    JobStatus,
    MagivizJob,
    SceneVideo,
    Storyboard,
    StoryboardFrame,
    StoryDetails,
    StoryOutline,
    VideoAspectRatio,
    VideoModel,
    make_magiviz_job,
    make_story_outline,
)

__all__ = [
    "CharacterDesign",
    "JobStatus",
    "MagivizJob",
    "SceneVideo",
    "StoryDetails",
    "StoryOutline",
    "Storyboard",
    "StoryboardFrame",
    # Schemas
    "VideoAspectRatio",
    "VideoModel",
    "compose_story_video",
    "execute_magiviz_plan",
    "generate_all_characters",
    "generate_character_image",
    "generate_scene_video",
    "generate_scene_videos_parallel",
    # Oprim
    "generate_story_details",
    "generate_storyboard",
    "generate_storyboard_frame",
    "make_magiviz_job",
    "make_story_outline",
    "plan_character_generation",
    # Omodul
    "plan_magiviz_pipeline",
    "plan_scene_generation",
    "plan_story_generation",
    "plan_storyboard_generation",
    "plan_video_composition",
    "run_full_pipeline",
    "skill_character_consistency",
    "skill_character_generation",
    # Oskill
    "skill_run_full_pipeline",
    "skill_scene_generation",
    "skill_story_generation",
    "skill_storyboard_generation",
    "skill_video_composition",
]