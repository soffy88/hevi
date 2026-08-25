"""magiviz 3O 包的 schema 契约。

Open-Magiviz AI 视频创作平台能力内部化。
核心五步工作流：剧情生成 → 角色设计 → 分镜生成 → 场景视频 → 视频合成
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# ─── 核心枚举 ─────────────────────────────────────


class VideoAspectRatio(str, Enum):
    """视频宽高比。"""

    LANDSCAPE_16_9 = "16:9"
    PORTRAIT_9_16 = "9:16"
    SQUARE_1_1 = "1:1"
    VERTICAL_4_5 = "4:5"


class VideoModel(str, Enum):
    """支持的视频生成模型。"""

    VEO = "veo"
    KLING = "kling"
    SEEDANCE = "seedance"
    WAN = "wan"
    RUNWAY = "runway"
    MINIMAX = "minimax"
    LUMA = "luma"


class JobStatus(str, Enum):
    """作业状态。"""

    PENDING = "pending"
    STORY_GENERATING = "story_generating"
    CHARACTER_GENERATING = "character_generating"
    STORYBOARD_GENERATING = "storyboard_generating"
    SCENES_GENERATING = "scenes_generating"
    COMPOSING = "composing"
    COMPLETED = "completed"
    FAILED = "failed"


# ─── 剧情/故事模型 ────────────────────────────────


class StoryOutline(BaseModel):
    """用户输入的故事大纲。"""
    model_config = ConfigDict(extra="allow")

    title: str = ""
    premise: str = ""  # 核心设定
    genre: str = ""  # 类型：好莱坞影视、动漫、故事剧情、广告、科普
    target_audience: str = ""  # 目标受众
    duration_target_s: int = 60  # 目标时长(秒)
    aspect_ratio: VideoAspectRatio = VideoAspectRatio.LANDSCAPE_16_9
    style: str = ""  # 风格描述
    reference_images: list[str] = Field(default_factory=list)  # 参考图


class CharacterDesign(BaseModel):
    """角色设计。"""
    model_config = ConfigDict(extra="allow")

    character_id: str = ""
    name: str = ""
    role: str = ""  # protagonist/antagonist/supporting
    visual_description: str = ""  # 外观描述
    personality: str = ""  # 性格特征
    voice_profile: str = ""  # 声音配置
    reference_image: str = ""  # 参考图
    consistency_prompt: str = ""  # 一致性维护提示词


class StoryDetails(BaseModel):
    """AI 生成的详细故事。"""
    model_config = ConfigDict(extra="allow")

    outline: StoryOutline = Field(default_factory=StoryOutline)
    characters: list[CharacterDesign] = Field(default_factory=list)
    scenes: list[dict[str, Any]] = Field(default_factory=list)  # 场景分解
    dialogues: list[dict[str, Any]] = Field(default_factory=list)  # 对话
    director_notes: list[str] = Field(default_factory=list)  # 导演指令


# ─── 分镜模型 ────────────────────────────────────


class StoryboardFrame(BaseModel):
    """单个分镜帧。"""
    model_config = ConfigDict(extra="allow")

    frame_id: str = ""
    scene_number: int = 0
    shot_number: int = 0
    description: str = ""  # 画面描述
    composition: str = ""  # 构图建议
    lighting: str = ""  # 光影氛围
    camera_angle: str = ""  # 机位角度
    camera_movement: str = ""  # 运镜方式
    duration_s: float = 3.0
    characters_present: list[str] = Field(default_factory=list)
    visual_prompt: str = ""  # 图像生成提示词
    reference_image: str = ""  # 生成的参考图


class Storyboard(BaseModel):
    """完整分镜。"""
    model_config = ConfigDict(extra="allow")

    frames: list[StoryboardFrame] = Field(default_factory=list)
    total_duration_s: float = 0.0
    aspect_ratio: VideoAspectRatio = VideoAspectRatio.LANDSCAPE_16_9


# ─── 场景视频模型 ────────────────────────────────


class SceneVideo(BaseModel):
    """单个场景视频。"""
    model_config = ConfigDict(extra="allow")

    scene_id: str = ""
    storyboard_frame_ids: list[str] = Field(default_factory=list)
    video_model: VideoModel = VideoModel.WAN
    video_path: str = ""
    duration_s: float = 0.0
    resolution: str = ""
    seed: int = 0
    prompt: str = ""  # 视频生成提示词
    negative_prompt: str = ""
    status: str = "pending"


# ─── 完整作业模型 ────────────────────────────────


class MagivizJob(BaseModel):
    """Magiviz 完整视频创作作业。"""
    model_config = ConfigDict(extra="allow")

    job_id: str = Field(default_factory=lambda: f"magiviz-{__import__('uuid').uuid4().hex[:12]}")
    user_id: str = ""
    status: JobStatus = JobStatus.PENDING
    current_step: str = "story_generating"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    # 输入
    story_outline: StoryOutline = Field(default_factory=StoryOutline)

    # 步骤产物
    story_details: StoryDetails = Field(default_factory=StoryDetails)
    storyboard: Storyboard = Field(default_factory=Storyboard)
    scene_videos: list[SceneVideo] = Field(default_factory=list)
    final_video_path: str = ""
    final_video_duration_s: float = 0.0

    # 配置
    preferred_models: list[VideoModel] = Field(default_factory=list)
    fallback_models: list[VideoModel] = Field(default_factory=list)

    # 统计
    total_generation_time_s: float = 0.0
    error: str = ""


# ─── 工厂函数 ────────────────────────────────────


def make_magiviz_job(
    story_outline: StoryOutline,
    user_id: str = "",
) -> MagivizJob:
    return MagivizJob(
        user_id=user_id,
        story_outline=story_outline,
    )


def make_story_outline(
    title: str,
    premise: str,
    genre: str = "故事剧情",
    duration_target_s: int = 60,
    aspect_ratio: VideoAspectRatio = VideoAspectRatio.LANDSCAPE_16_9,
) -> StoryOutline:
    return StoryOutline(
        title=title,
        premise=premise,
        genre=genre,
        duration_target_s=duration_target_s,
        aspect_ratio=aspect_ratio,
    )


# ─── 导出 ────────────────────────────────────────


__all__ = [
    "CharacterDesign",
    "JobStatus",
    "MagivizJob",
    "SceneVideo",
    "StoryDetails",
    "StoryOutline",
    "Storyboard",
    "StoryboardFrame",
    "VideoAspectRatio",
    "VideoModel",
    "make_magiviz_job",
    "make_story_outline",
]