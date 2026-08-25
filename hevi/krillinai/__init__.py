"""KrillinAI Clip Generator 3O §3 Task 3.x 出品。

KrillinAI 是视频翻译和配音解决方案，核心管道：
视频获取 → 语音识别 → 智能分割 → 专业翻译 → TTS 配音 → 视频合成 → 封面生成

本包内部化 KrillinAI Clip Generator 能力为 hevi 3O 形式：
schemas → oprim → oskill → omodul
"""

from __future__ import annotations

# ── Omodul ──
from hevi.krillinai.omodul import (
    execute_clip_generator,
    plan_ai_short,
    plan_clip_generator,
    plan_youtube_studio,
)

# ── Oprim ──
from hevi.krillinai.oprim import (
    download_video,
    extract_audio,
    generate_cover,
    generate_short_mixed_srt,
    get_artifact_path,
    merge_tts_to_video,
    read_manifest,
    render_horizontal_bilingual,
    render_horizontal_dubbed,
    render_vertical,
    segment_subtitle,
    synthesize_tts,
    synthesize_with_aliyun_tts,
    synthesize_with_minimax_tts,
    synthesize_with_openai_tts,
    transcribe_audio,
    transcribe_with_faster_whisper,
    transcribe_with_whisper_cpp,
    translate_subtitle,
    write_manifest,
)

# ── Oskill ──
from hevi.krillinai.oskill import (
    skill_acquire_video,
    skill_cover,
    skill_full_pipeline,
    skill_render,
    skill_segment,
    skill_transcribe,
    skill_translate,
    skill_tts,
)

# ── Schemas ──
from hevi.krillinai.schemas import (
    ASRConfig,
    ASRProvider,
    AudioFile,
    ClipGeneratorJob,
    CoverFile,
    JobStatus,
    LLMConfig,
    LLMProvider,
    RenderConfig,
    RenderMode,
    SubtitleFile,
    SubtitleSegment,
    TranslationPair,
    TTSConfig,
    TTSProvider,
    VideoFile,
    make_clip_generator_job,
)

__all__ = [
    "ASRConfig",
    # Schemas
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
    # Oprim
    "download_video",
    "execute_clip_generator",
    "extract_audio",
    "generate_cover",
    "generate_short_mixed_srt",
    "get_artifact_path",
    "make_clip_generator_job",
    "merge_tts_to_video",
    "plan_ai_short",
    # Omodul
    "plan_clip_generator",
    "plan_youtube_studio",
    "read_manifest",
    "render_horizontal_bilingual",
    "render_horizontal_dubbed",
    "render_vertical",
    "segment_subtitle",
    # Oskill
    "skill_acquire_video",
    "skill_cover",
    "skill_full_pipeline",
    "skill_render",
    "skill_segment",
    "skill_transcribe",
    "skill_translate",
    "skill_tts",
    "synthesize_tts",
    "synthesize_with_aliyun_tts",
    "synthesize_with_minimax_tts",
    "synthesize_with_openai_tts",
    "transcribe_audio",
    "transcribe_with_faster_whisper",
    "transcribe_with_whisper_cpp",
    "translate_subtitle",
    "write_manifest",
]