"""openshorts 3O 包的 schema 契约。

OpenShorts 三大能力内部化：
1. Clip Generator —— 长视频 → 3-15 竖屏 Short
2. AI Shorts —— 从零生成 UGC 视频（网站→脚本→演员→视频→分发）
3. YouTube Studio —— AI 标题/缩略图/描述/章节

出品形式：每项能力均可独立调用，也可通过 Pipeline 串联。
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

# ─── Clip Generator ─────────────────────────────────


class ReframingMode(str, Enum):
    """OpenShorts 三种 9:16 重构模式。"""
    TRACK = "track"      # MediaPipe + YOLOv8 面部跟踪
    GENERAL = "general"  # 模糊背景
    SPLIT = "split"      # 两位说话人叠加


class ClipSpec(BaseModel):
    """单个 Short clip 规格。"""
    clip_index: int
    start_time_s: float
    end_time_s: float
    duration_s: float = 0.0
    headline: str = ""
    subtitle_text: str = ""
    reframe_mode: ReframingMode = ReframingMode.GENERAL
    reframe_params: dict[str, Any] = Field(default_factory=dict)
    voiceover_path: str = ""
    effects: dict[str, Any] = Field(default_factory=dict)

    def model_post_init(self, __context: Any) -> None:
        if self.duration_s == 0:
            self.duration_s = round(self.end_time_s - self.start_time_s, 3)


class ClipGeneratorJob(BaseModel):
    """Clip Generator 完整作业。"""
    job_id: str = ""
    user_id: str = ""
    video_path: str = ""
    reframing: ReframingMode = ReframingMode.GENERAL
    target_clips: int = 5
    with_voiceover: bool = True
    with_hook_text: bool = True
    with_subtitles: bool = True
    clips: list[ClipSpec] = Field(default_factory=list)
    transcript: dict[str, Any] = Field(default_factory=dict)
    video_duration_s: float = 0.0
    status: str = "pending"
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ─── AI Shorts ───────────────────────────────────────


class AICostMode(str, Enum):
    """AI Shorts 两种成本模式。"""
    LOW_COST = "low_cost"        # ~$0.65/video: Hailuo 2.3 Fast + VEED Lipsync
    PREMIUM = "premium"          # ~$2/video: Kling Avatar v2


class AICostPlan(BaseModel):
    """AI Shorts 成本计划。"""
    mode: AICostMode = AICostMode.LOW_COST
    estimated_cost_usd: float = 0.65
    video_gen_provider: str = "hailuo_2.3_fast"
    lipsync_provider: str = "veed"
    actor_provider: str = "flux_2_pro"


class AIActor(BaseModel):
    """AI 演员生成参数。"""
    provider: str = "flux_2_pro"
    source_image: str = ""      # 上传照片路径（可选）
    source_url: str = ""        # 上传照片 URL（可选）
    prompt: str = ""            # 生成提示
    style: str = "professional"  # professional | casual | lifestyle
    portrait_path: str = ""     # 生成的肖像路径
    gallery_id: str = ""        # 共享角色库 ID


class AIScript(BaseModel):
    """AI Shorts 脚本。"""
    hook: str = ""              # 前 3 秒 Hook
    problem: str = ""           # 问题描述
    solution: str = ""          # 解决方案
    cta: str = ""               # 行动号召
    segments: list[dict[str, Any]] = Field(default_factory=list)
    total_duration_s: float = 60.0


class AIShortJob(BaseModel):
    """AI Shorts 完整作业。"""
    job_id: str = ""
    user_id: str = ""
    # 输入
    product_url: str = ""       # 产品 URL（可选）
    product_description: str = ""  # 手动描述
    # 脚本
    script: AIScript = Field(default_factory=AIScript)
    # 演员
    actor: AIActor = Field(default_factory=AIActor)
    # 成本
    cost_plan: AICostPlan = Field(default_factory=AICostPlan)
    # 生成产物
    voiceover_path: str = ""
    talking_head_path: str = ""
    b_roll_paths: list[str] = Field(default_factory=list)
    composite_path: str = ""
    # 分发
    publish_platforms: list[str] = Field(default_factory=list)
    publish_status: str = ""
    # 状态
    status: str = "pending"
    error: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ─── YouTube Studio ──────────────────────────────────


class YouTubeTitle(BaseModel):
    """AI 生成的 YouTube 标题。"""
    title: str
    viral_score: float = 0.0  # 0-10
    reasoning: str = ""


class YouTubeThumbnail(BaseModel):
    """YouTube 缩略图。"""
    path: str = ""
    face_overlay: bool = True
    style: str = "bold_text"


class YouTubeChapter(BaseModel):
    """YouTube 章节。"""
    title: str
    start_s: float
    end_s: float


class YouTubeDescription(BaseModel):
    """YouTube 描述。"""
    text: str = ""
    chapters: list[YouTubeChapter] = Field(default_factory=list)
    hashtags: list[str] = Field(default_factory=list)


class YouTubeStudioJob(BaseModel):
    """YouTube Studio 完整作业。"""
    job_id: str = ""
    user_id: str = ""
    video_path: str = ""
    # 输入
    source_title: str = ""
    source_description: str = ""
    # AI 产物
    titles: list[YouTubeTitle] = Field(default_factory=list)
    selected_title: str = ""
    thumbnail: YouTubeThumbnail = Field(default_factory=YouTubeThumbnail)
    description: YouTubeDescription = Field(default_factory=YouTubeDescription)
    # 发布
    publish_to_youtube: bool = False
    publish_status: str = ""
    # 状态
    status: str = "pending"
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ─── 公共模型 ───────────────────────────────────────


class SceneDetection(BaseModel):
    """场景检测结果。"""
    scene_id: str = ""
    start_s: float = 0.0
    end_s: float = 0.0
    headline: str = ""
    viral_score: float = 0.0
    face_positions: list[dict[str, float]] = Field(default_factory=list)


class TranscriptWindow(BaseModel):
    """转录窗口。"""
    window_id: str = ""
    start_s: float = 0.0
    end_s: float = 0.0
    text: str = ""


class WordTimestamp(BaseModel):
    """词级时间戳。"""
    word: str = ""
    start_s: float = 0.0
    end_s: float = 0.0


class ViralMoment(BaseModel):
    """病毒时刻标记。"""
    moment_id: str = ""
    start_s: float = 0.0
    end_s: float = 0.0
    viral_score: float = 0.0
    reasoning: str = ""


class PublishTicket(BaseModel):
    """社交分发交接单。"""
    platform: str
    media_path: str
    title: str = ""
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    scheduled_date: str | None = None
    status: str = "pending"


# ─── 工厂函数 ───────────────────────────────────────


def make_clip_generator_job(video_path: str, user_id: str = "") -> ClipGeneratorJob:
    import uuid
    return ClipGeneratorJob(
        job_id=f"clipgen-{uuid.uuid4().hex[:12]}",
        user_id=user_id,
        video_path=video_path,
    )


def make_ai_short_job(description: str = "", url: str = "", user_id: str = "") -> AIShortJob:
    import uuid
    return AIShortJob(
        job_id=f"aishort-{uuid.uuid4().hex[:12]}",
        user_id=user_id,
        product_url=url,
        product_description=description,
    )


def make_youtube_studio_job(video_path: str, user_id: str = "") -> YouTubeStudioJob:
    import uuid
    return YouTubeStudioJob(
        job_id=f"ytstudio-{uuid.uuid4().hex[:12]}",
        user_id=user_id,
        video_path=video_path,
    )