"""digital_human 3O 包的 schema 契约。

对应 lanshu-create-ai-presenter-video 的完整作业模型：
账号/人物配置 + 作业状态机 + 时间轴/字幕规划 + QA 验收。
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

# ─── 作业状态机模型 ──────────────────────────────


class JobStatus(str, Enum):
    """作业状态机。对应 lanshu 的 intake→verified 流程。"""

    INTAKE = "intake"
    CONTENT_LOCKED = "content_locked"
    AUDIO_LOCKED = "audio_locked"
    VISUAL_PLAN_LOCKED = "visual_plan_locked"
    PRESENTER_GENERATED = "presenter_generated"
    COMPOSITION_CHECKED = "composition_checked"
    RENDERED = "rendered"
    VERIFIED = "verified"


class JobPriority(str, Enum):
    """作业优先级。"""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class PresenterJob(BaseModel):
    """完整的数字人视频作业模型。

    对应 lanshu 的 job.json 全量模型，但为 Pydantic BaseModel
    以便在无数据库时直接使用，或与 SQLAlchemy 模型互换。
    """

    id: int | None = None
    job_id: str = Field(default_factory=lambda: f"presenter-{uuid4()}")
    status: JobStatus = JobStatus.INTAKE
    priority: JobPriority = JobPriority.NORMAL
    user_id: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    # ── 输入 ────────────────────────────────────
    topic: str = ""
    script_path: str = ""
    presenter_image: str = ""  # 本地路径或 remote URL
    voice_sample: str = ""  # 本地语音样本路径
    supporting_media: list[str] = Field(default_factory=list)

    # ── 授权/确认 ───────────────────────────────
    rights_confirmed: bool = False
    adult_presenter_confirmed: bool = False
    remote_upload_approved: bool = False
    voice_clone_approved: bool = False

    # ── 创意参数 ─────────────────────────────────
    language: str = "auto"
    audience: str = "general"
    goal: str = "explain clearly"
    duration_target_s: int = 60
    aspect: str = "9:16"
    width: int = 1080
    height: int = 1920
    fps: int = 30
    style: str = "credible contemporary presenter"
    watermark: str = ""
    cta: str = ""

    # ── 声音配置 ─────────────────────────────────
    voice_strategy: str = "auto"
    voice_id: str = ""
    rate: float = 1.06
    segment_lufs: float = -17
    program_lufs: float = -16

    # ── 计划/产物 ────────────────────────────────
    script: str = ""
    beat_sheet: str = ""
    timeline: str = ""
    storyboard: str = ""
    final_audio: str = ""
    caption_json: str = ""
    rendered: str = ""  # 母版路径
    share: str = ""  # 分享版路径

    # ── QA 报告 ─────────────────────────────────
    qa_preflight: str = ""  # qa/reports/preflight.json 路径
    qa_asr: str = ""  # qa/reports/asr_report.json 路径
    qa_composition: str = ""  # qa/reports/composition_report.json 路径
    qa_delivery: str = ""  # qa/reports/delivery_report.json 路径
    manual_visual_review: str = ""

    def is_available(self) -> bool:
        """检查作业是否可以进入下一阶段。"""
        return {
            JobStatus.INTAKE: self.rights_confirmed and self.adult_presenter_confirmed,
            JobStatus.CONTENT_LOCKED: self.script != "",
            JobStatus.AUDIO_LOCKED: self.final_audio != "",
            JobStatus.VISUAL_PLAN_LOCKED: self.timeline != "",
            JobStatus.PRESENTER_GENERATED: self.rendered != "",
            JobStatus.COMPOSITION_CHECKED: self.qa_composition != "",
            JobStatus.RENDERED: self.rendered != "",
            JobStatus.VERIFIED: True,
        }.get(self.status, False)


# ─── QA 契约 ───────────────────────────────────────


class QAReport(BaseModel):
    """统一的 QA 验收报告。

    包含：技术检查 + 人工检查 + 授权检查 三位一体的验收结果。
    """

    model: str = "qa-report"
    ok: bool = False
    remote_ready: bool = False

    # 技术检查
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    media: dict[str, Any] = Field(default_factory=dict)

    # 授权检查
    rights_confirmed: bool = False
    adult_presenter_confirmed: bool = False
    remote_upload_approved: bool = False
    voice_clone_approved: bool = False

    # 生成指标
    measured_lufs: float = -17
    program_lufs: float = -16
    duration_s: float = 0.0
    black_frame_events: int = 0
    decode_passed: bool = False

    # 人工检查项
    identity_coherent: bool = False
    mouth_sync: bool = False
    no_black_frames: bool = False
    no_overlay: bool = False
    captions_readable: bool = False
    safe_zones_ok: bool = False


# ─── 时间轴/剪辑模型 ───────────────────────────────


class ClipSpec(BaseModel):
    """时间轴剪辑规范。

    承担 lanshu 的三独立值：authored_start, authored_duration, source_start
    """

    authored_start_s: float = 0.0
    authored_duration_s: float = 0.0
    source_start_s: float = 0.0
    source_duration_s: float = 0.0
    media_path: str = ""
    media_type: str = "video"  # video | audio | image | caption

    def is_valid(self) -> bool:
        """检查剪辑规范是否完整。"""
        return (
            self.authored_duration_s > 0
            and self.authored_start_s >= 0
            and self.source_duration_s > 0
        )


class ChapterSpec(BaseModel):
    """章节规范。

    每一章节的开始时间、时长和标题。
    """

    title: str = ""
    start_s: float = 0.0
    duration_s: float = 0.0
    thumbnail_path: str = ""


class TimelinePlan(BaseModel):
    """确定性时间轴计划。

    锁定音频为主时钟，所有剪辑按音频边界对齐。
    """

    model: str = "timeline-plan"
    narration_duration_s: float = 0.0
    total_video_duration_s: float = 0.0
    opening_target_s: float = 4.0
    closing_target_s: float = 5.0
    chapters: list[ChapterSpec] = Field(default_factory=list)
    clips: list[ClipSpec] = Field(default_factory=list)

    # ── 验收步骤 ────────────────────────────────
    validation_steps: list[dict[str, Any]] = Field(
        default_factory=lambda: [
            {"step": "account_check", "required": True},
            {"step": "media_check", "required": True},
            {"step": "timeline_check", "required": True},
            {"step": "qe_check", "required": True},
        ]
    )

    def is_available(self) -> bool:
        """检查时间轴是否完整可执行。"""
        return (
            self.narration_duration_s > 0
            and len(self.clips) > 0
            and self.opening_target_s >= 0
            and self.closing_target_s >= 0
        )


# ─── 字幕模型 ──────────────────────────────────────


class CaptionPhrase(BaseModel):
    """单条字幕短语。

    包含：文本、词级时间戳、样式预设
    """

    text: str = ""
    start_s: float = 0.0
    duration_s: float = 0.0
    style: str = "default"  # default | keyword | emphasis

    def is_valid(self) -> bool:
        """检查短语是否完整。"""
        return bool(self.text.strip()) and self.duration_s > 0


class CaptionPlan(BaseModel):
    """字幕计划。

    词级时间戳 + 关键词动效预设绑定
    """

    model: str = "caption-plan"
    phrases: list[CaptionPhrase] = Field(default_factory=list)
    keyword_presets: list[str] = Field(
        default_factory=lambda: [
            "radial_burst",
            "tilted_ribbon",
            "hand_drawn_circle",
            "type_contrast",
            "word_chip_cluster",
            "outline_lockup",
        ]
    )

    def is_available(self) -> bool:
        return len(self.phrases) > 0


# ─── 音频/QA 辅助模型 ──────────────────────────────


class AudioMeasurement(BaseModel):
    """音频测量结果（来自 loudnorm 双遍处理）。"""

    input_i: float = -23.0  # 输入原始响度
    input_tp: float = -3.0  # 真峰值
    input_lra: float = 20.0  # 动态范围
    input_thresh: float = -18.0  # 阈值
    target_offset: float = 0.0  # 调整偏移
    measured_lufs: float = -16.0  # 测得响度
    program_lufs: float = -16.0  # 程序响度目标


# ─── 工厂函数 ─────────────────────────────────────


def make_default_job() -> PresenterJob:
    """创建一个默认的 intake 状态作业。"""
    return PresenterJob()


def make_default_qa_report() -> QAReport:
    """创建一个默认的 QA 报告。"""
    return QAReport()


def make_default_timeline() -> TimelinePlan:
    """创建一个默认的时间轴计划。"""
    return TimelinePlan()


def make_default_caption_plan() -> CaptionPlan:
    """创建一个默认的字幕计划。"""
    return CaptionPlan()