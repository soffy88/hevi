"""krillinai 3O 包的 schema 契约。

KrillinAI 核心能力内部化：Clip Generator 形式。

核心管道：视频获取 → 语音识别 → 智能分割 → 专业翻译 → TTS 配音 → 视频合成 → 封面生成
支持：横屏/竖屏、双语字幕、声纹克隆、风格化渲染
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

# ─── 核心枚举 ───────────────────────────────────────


class ASRProvider(str, Enum):
    """语音识别提供商。"""
    OPENAI_WHISPER = "openai_whisper"
    FASTER_WHISPER = "faster_whisper"
    WHISPER_KIT = "whisper_kit"
    WHISPER_CPP = "whisper_cpp"
    ALIYUN_ASR = "aliyun_asr"


class LLMProvider(str, Enum):
    """LLM 翻译提供商。"""
    OPENAI = "openai"
    GEMINI = "gemini"
    DEEPSEEK = "deepseek"
    TONGYI = "tongyi"
    LOCAL = "local"


class TTSProvider(str, Enum):
    """TTS 提供商。"""
    ALIYUN_TTS = "aliyun_tts"
    OPENAI_TTS = "openai_tts"
    MINIMAX_TTS = "minimax_tts"


class RenderMode(str, Enum):
    """渲染模式。"""
    HORIZONTAL_BILINGUAL = "horizontal_bilingual"
    HORIZONTAL_DUBBED = "horizontal_dubbed"
    VERTICAL_BILINGUAL = "vertical_bilingual"
    VERTICAL_DUBBED = "vertical_dubbed"
    COVER = "cover"


class JobStatus(str, Enum):
    """作业状态。"""
    PENDING = "pending"
    DOWNLOADING = "downloading"
    TRANSCRIBING = "transcribing"
    SEGMENTING = "segmenting"
    TRANSLATING = "translating"
    TTS_SYNTHESIZING = "tts_synthesizing"
    RENDERING = "rendering"
    COVER_GENERATING = "cover_generating"
    COMPLETED = "completed"
    FAILED = "failed"


# ─── 配置模型 ───────────────────────────────────────


class ASRConfig(BaseModel):
    """语音识别配置。"""
    provider: ASRProvider = ASRProvider.FASTER_WHISPER
    model: str = "large-v2"  # tiny/medium/large-v2
    language: str = "auto"
    device: str = "auto"  # cpu/cuda/mps
    compute_type: str = "float16"


class LLMConfig(BaseModel):
    """LLM 翻译配置。"""
    provider: LLMProvider = LLMProvider.OPENAI
    model: str = "gpt-4o-mini"
    base_url: str = ""
    api_key: str = ""
    temperature: float = 0.3
    terminology_map: dict[str, str] = Field(default_factory=dict)  # 专业词汇替换


class TTSConfig(BaseModel):
    """TTS 配置。"""
    provider: TTSProvider = TTSProvider.ALIYUN_TTS
    voice: str = "zh-CN-Xiaoyun"
    speed: float = 1.0
    pitch: float = 1.0
    voice_clone_source: str = ""  # 声纹克隆源音频路径/URL


class RenderConfig(BaseModel):
    """视频渲染配置。"""
    mode: RenderMode = RenderMode.HORIZONTAL_BILINGUAL
    resolution: str = "1920x1080"
    fps: int = 30
    # 竖屏特有
    vertical_resolution: str = "1080x1920"
    major_title: str = "今日话题"
    minor_title: str = "AI Video"
    subtitle_style: dict[str, Any] = Field(default_factory=dict)  # 字幕样式


# ─── 作业模型 ───────────────────────────────────────


class SubtitleFile(BaseModel):
    """字幕文件。"""
    path: str = ""
    language: str = ""
    format: str = "srt"


class VideoFile(BaseModel):
    """视频文件。"""
    path: str = ""
    duration_s: float = 0.0
    width: int = 0
    height: int = 0


class AudioFile(BaseModel):
    """音频文件。"""
    path: str = ""
    duration_s: float = 0.0


class CoverFile(BaseModel):
    """封面文件。"""
    path: str = ""
    platform: str = ""  # bilibili/xiaohongshu/douyin/shipinhao/kuaishou/youtube/tiktok


class ClipGeneratorJob(BaseModel):
    """Clip Generator 完整作业（对应 KrillinAI pipeline）。"""

    job_id: str = ""
    user_id: str = ""

    # ── 输入 ─────────────────────────────────────
    input_source: str = ""  # YouTube URL / 本地路径 / Bilibili URL
    workdir: str = ""

    # ── 配置 ─────────────────────────────────────
    asr: ASRConfig = Field(default_factory=ASRConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    tts: TTSConfig = Field(default_factory=TTSConfig)
    render: RenderConfig = Field(default_factory=RenderConfig)

    # ── 阶段产物 ──────────────────────────────────
    # Stage 1: 视频获取
    original_video: VideoFile = Field(default_factory=VideoFile)
    original_audio: AudioFile = Field(default_factory=AudioFile)

    # Stage 2: 语音识别
    origin_language_srt: SubtitleFile = Field(default_factory=SubtitleFile)

    # Stage 3: 智能分割
    segmented_srt: SubtitleFile = Field(default_factory=SubtitleFile)

    # Stage 4: 专业翻译
    target_language_srt: SubtitleFile = Field(default_factory=SubtitleFile)
    bilingual_srt: SubtitleFile = Field(default_factory=SubtitleFile)
    short_origin_mixed_srt: SubtitleFile = Field(default_factory=SubtitleFile)

    # Stage 5: TTS 配音
    tts_final_audio: AudioFile = Field(default_factory=AudioFile)
    video_with_tts: VideoFile = Field(default_factory=VideoFile)

    # Stage 6: 视频合成
    rendered_videos: dict[RenderMode, VideoFile] = Field(default_factory=dict)

    # Stage 7: 封面生成
    covers: list[CoverFile] = Field(default_factory=list)

    # ── 状态 ─────────────────────────────────────
    status: JobStatus = JobStatus.PENDING
    current_stage: str = ""
    error: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    def update_status(self, status: JobStatus, stage: str = "") -> None:
        self.status = status
        if stage:
            self.current_stage = stage
        self.updated_at = datetime.utcnow()


# ─── 字幕分段/翻译辅助模型 ───────────────────────────


class SubtitleSegment(BaseModel):
    """单条字幕片段。"""
    index: int = 0
    start_s: float = 0.0
    end_s: float = 0.0
    text: str = ""
    translated_text: str = ""


class TranslationPair(BaseModel):
    """翻译对。"""
    original: str = ""
    translated: str = ""
    terminology_applied: bool = False


# ─── 工厂函数 ───────────────────────────────────────


def make_clip_generator_job(
    input_source: str,
    user_id: str = "",
    workdir: str = "",
) -> ClipGeneratorJob:
    import uuid
    return ClipGeneratorJob(
        job_id=f"krillinai-{uuid.uuid4().hex[:12]}",
        user_id=user_id,
        input_source=input_source,
        workdir=workdir or f"tasks/{uuid.uuid4().hex[:12]}",
    )


# ─── 导出 ───────────────────────────────────────────

__all__ = [
    "ASRConfig",
    "ASRProvider",
    "AudioFile",
    "ClipGeneratorJob",
    "CoverFile",
    "JobStatus",
    "LLMConfig",
    "LLMProvider",
    "RenderConfig",
    "RenderMode",
    "SubtitleFile",
    "SubtitleSegment",
    "TTSConfig",
    "TTSProvider",
    "TranslationPair",
    "VideoFile",
    "make_clip_generator_job",
]