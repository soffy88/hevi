"""krillinai omodul：文本规划/任务编排，供 studio/production 工作流调用。

对应 KrillinAI Clip Generator pipeline 的 stage-by-stage 规划与执行。
Pipeline 结构：
1. acquire_video - 获取视频 + 音频
2. transcribe - 语音识别生成字幕
3. segment - LLM 智能分割
4. translate - 专业翻译 + 双语字幕
5. tts - SRT 合成 TTS + 生成 video_with_tts
6. render - 横竖屏渲染 (bilinguial/dubbed)
7. cover - 封面生成
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

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
from hevi.krillinai.schemas import (
    ASRConfig,
    ClipGeneratorJob,
    JobStatus,
    LLMConfig,
    RenderConfig,
    TTSConfig,
    make_clip_generator_job,
)

# ── Pipeline 规划 ─────────────────────────────────────

AVAILABLE_MODES = {
    "auto": "根据视频内容自动选择最佳模式",
    "horizontal_bilingual": "横屏双语 (中文上/下)",
    "horizontal_dubbed": "横屏旁白",
    "vertical_bilingual": "竖屏双语 (主流)",
    "vertical_dubbed": "竖屏旁白",
    "cover_only": "仅封面生成",
}

AVAILABLE_PLATFORMS = [
    "bilibili", "xiaohongshu", "douyin", "shipinhao",
    "kuaishou", "youtube", "tiktok",
]


def plan_clip_generator(
    input_source: str,
    user_id: str = "",
    workdir: str | None = None,
    reframing: str = "general",
    target_clips: int | None = None,
    with_voiceover: bool = True,
    publish_platforms: list[str] | None = None,
) -> dict[str, Any]:
    """规划 Clip Generator pipeline 完整执行计划。

    返回结构对应 OpenShorts/KrillinAI Clip Generator pipeline 的 7 个 stage。
    """
    workdir = workdir or f"tasks/{__import__('uuid').uuid4().hex[:8]}"
    make_clip_generator_job(input_source, user_id, workdir)

    # 自动确定 target_clips (默认 3-5)
    if target_clips is None:
        target_clips = 5

    # 确定渲染模式
    modes = ["horizontal_bilingual", "vertical_bilingual"] if target_clips > 1 else ["horizontal_bilingual"]

    return {
        "pipeline": "clip_generator",
        "input_source": input_source,
        "user_id": user_id,
        "workdir": workdir,
        "reframing": reframing,
        "target_clips": target_clips,
        "with_voiceover": with_voiceover,
        "publish_platforms": publish_platforms or ["bilibili", "tiktok"],
        "stages": [
            {"stage": "acquire_video", "mode": "auto", "desc": "下载视频 + 提取音频"},
            {"stage": "transcribe", "mode": "faster_whisper", "desc": "语音识别生成 SRT"},
            {"stage": "segment", "mode": "llm_segment", "desc": "LLM 智能分割"},
            {"stage": "translate", "mode": "llm_translate", "desc": "专业翻译 + 双语字幕"},
            {"stage": "tts", "mode": "tts_synthesize", "desc": "TTS 配音 + video_with_tts.mp4"},
            {"stage": "render", "mode": ", ".join(modes), "desc": "横竖屏渲染"},
            {"stage": "cover", "mode": ", ".join(publish_platforms or []) if publish_platforms else "all", "desc": "平台封面生成"},
        ],
        "estimated_stages": 7,
        "checkpoint_policy": "after_every_stage",
        "budget_usd_estimate": 3.0,  # 基于 Gemini + S3 + ElevenLabs 免费额度
    }


def plan_ai_short(
    description: str = "",
    url: str | None = None,
    user_id: str = "",
    cost_mode: str = "low_cost",
    publish_to: list[str] | None = None,
) -> dict[str, Any]:
    """规划 AI Shorts pipeline (从零生成 UGC 视频)。

    从描述或 URL 到完整 UGC 视频的端到端计划。
    """
    cm = "low_cost" if cost_mode == "low_cost" else "premium"

    return {
        "pipeline": "ai_shorts",
        "description": description,
        "url": url,
        "user_id": user_id,
        "cost_mode": cost_mode,
        "publish_to": publish_to or ["tiktok", "instagram", "youtube"],
        "stages": [
            {"stage": "analyze", "mode": "gemini", "desc": "网页抓取 + Gemini 研究"},
            {"stage": "script", "mode": "gemini", "desc": "病毒式脚本 (hook→problem→solution→CTA)"},
            {"stage": "actor", "mode": "flux_2_pro", "desc": "AI 演员生成"},
            {"stage": "voice", "mode": "elevenlabs", "desc": "TTS 旁白"},
            {"stage": "video", "mode": "hailuo_2.3_fast", "desc": "Talking head + lipsync"},
            {"stage": "broll", "mode": "flux_2_pro", "desc": "Ken Burns B-roll images"},
            {"stage": "composite", "mode": "ffmpeg", "desc": "ASS subtitles + hook overlays"},
            {"stage": "gallery", "mode": "s3", "desc": "上传到 public S3"},
            {"stage": "publish", "mode": "upload_post", "desc": "TikTok/Ins/YouTube"},
        ],
        "estimated_cost_usd": 0.65 if cm == "low_cost" else 2.0,
        "checkpoint_policy": "after_every_major_stage",
    }


def plan_youtube_studio(
    video_path: str,
    user_id: str = "",
    source_title: str = "",
    source_description: str = "",
) -> dict[str, Any]:
    """规划 YouTube Studio pipeline。

    AI 生成标题 + 缩略图 + 描述 + 章节。
    """
    return {
        "pipeline": "youtube_studio",
        "video_path": video_path,
        "user_id": user_id,
        "stages": [
            {"stage": "titles", "mode": "gemini", "desc": "10 个带 viral_score 的标题"},
            {"stage": "thumbnail", "mode": "flux_2_pro + ffmpeg", "desc": "AI 缩略图 + face overlay"},
            {"stage": "description", "mode": "gemini", "desc": "SEO 描述 + 章节时间戳 + hashtags"},
            {"stage": "publish", "mode": "upload_post", "desc": "一键发布到 YouTube"},
        ],
        "estimated_cost_usd": 0.0,
        "checkpoint_policy": "after_titles",
    }


# ── 执行器 ────────────────────────────────────────────

async def execute_clip_generator(
    input_source: str,
    user_id: str = "",
    modes: list[str] | None = None,
    line_mode: str = "target-only",
) -> ClipGeneratorJob:
    """执行 Clip Generator pipeline（由 hevi studio pipeline 调用）。

    1. acquire_video + extract_audio
    2. transcribe (FasterWhisper)
    3. segment (LLM)
    4. translate (LLM + 术语映射)
    5. tts (目标语言合成)
    6. render (横/竖屏)
    6. cover (平台封面)
    """
    job = make_clip_generator_job(input_source, user_id)

    # Stage 1
    job = skill_acquire_video(job)

    # Stage 2
    job = skill_transcribe(job)

    # Stage 3
    job = skill_segment(job)

    # Stage 4
    job = skill_translate(job)

    # Stage 5
    job = skill_tts(job, line_mode)

    # Stage 6
    from hevi.krillinai.schemas import RenderMode

    render_modes = [
        RenderMode(mode)
        for mode in (modes or ["horizontal_bilingual", "vertical_bilingual"])
    ]
    job = skill_render(job, render_modes)

    # Stage 6.5: 封面 (依赖 original_video 是否存在)
    if job.original_video.path:
        job = skill_cover(job, platforms=["bilibili", "tiktok"])

    return job


# ── 导出 ───────────────────────────────────────────────

__all__ = [
    # 规划
    "plan_clip_generator",
    "plan_ai_short",
    "plan_youtube_studio",
    # 执行
    "execute_clip_generator",
]
