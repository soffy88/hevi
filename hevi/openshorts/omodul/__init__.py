"""openshorts omodul：文本规划/任务编排，供 studio/production 工作流调用。

对应 OpenShorts 三大核心能力的出品形式规划：
Clip Generator / AI Shorts / YouTube Studio
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from hevi.openshorts.oprim import (
    clip_reframing_params,
    generate_script_from_description,
    generate_youtube_description,
    generate_youtube_thumbnail,
    generate_youtube_titles,
    plan_ai_short_actor,
)
from hevi.openshorts.oskill import (
    create_publish_tickets,
    generate_ai_short,
    generate_clips,
    generate_youtube_package,
)
from hevi.openshorts.schemas import (
    AICostMode,
    AIShortJob,
    ClipGeneratorJob,
    PublishTicket,
    ReframingMode,
    YouTubeStudioJob,
    make_ai_short_job,
    make_clip_generator_job,
    make_youtube_studio_job,
)

# ── Clip Generator Pipeline 规划 ──────────────────────

AVAILABLE_LAYOUTS = {
    "auto": "自动选择 TRACK / GENERAL / SPLIT",
    "track": "MediaPipe + YOLOv8 面部跟踪",
    "general": "模糊背景 + 中心主体",
    "split": "两位说话人叠加布局",
}


def plan_clip_generator(
    video_path: str,
    user_id: str = "",
    reframing: str = "general",
    target_clips: int = 5,
    with_voiceover: bool = False,
    with_hook_text: bool = True,
) -> dict[str, Any]:
    """规划 Clip Generator pipeline。

    返回完整的 stage-by-stage 执行计划，对应 OpenShorts Clip Generator 流程。
    """
    return {
        "pipeline": "clip_generator",
        "video_path": video_path,
        "user_id": user_id,
        "reframing": reframing,
        "target_clips": target_clips,
        "with_voiceover": with_voiceover,
        "with_hook_text": with_hook_text,
        "stages": [
            {"stage": "transcribe", "tool": "faster-whisper", "output": "transcript + word timestamps"},
            {"stage": "detect_scenes", "tool": "PySceneDetect/TransNet v2", "output": "scene boundaries"},
            {"stage": "viral_detect", "tool": "gemini", "output": "3-15 viral moments with scores"},
            {"stage": "build_windows", "tool": "clip_selection.py", "output": "transcript windows"},
            {"stage": "reframe", "tool": reframing, "output": f"9:16 clips in {reframing} mode"},
            {"stage": "subtitles", "tool": "ass_generator", "output": "word-level ASS subtitles"},
            {"stage": "hook_text", "tool": "gemini_ffmpeg", "output": "hook overlays (first clip)"},
            {"stage": "compose", "tool": "ffmpeg", "output": "final clips"},
        ],
        "estimated_cost_usd": 0.0,  # Gemini + S3 = free tier
        "checkpoint_policy": "guided",
    }


# ── AI Shorts Pipeline 规划 ───────────────────────────

AVAILABLE_COST_MODES = {
    "low_cost": {
        "label": "低成本 (~$0.65/video)",
        "video_gen": "Hailuo 2.3 Fast",
        "lipsync": "VEED",
        "actor": "Flux 2 Pro",
    },
    "premium": {
        "label": "高级 (~$2/video)",
        "video_gen": "Kling Avatar v2",
        "lipsync": "Kling",
        "actor": "Flux 2 Pro / Kling",
    },
}

SOCIAL_PLATFORMS = ["tiktok", "instagram", "youtube"]


def plan_ai_short(
    description: str = "",
    url: str = "",
    user_id: str = "",
    cost_mode: str = "low_cost",
    publish_to: list[str] | None = None,
) -> dict[str, Any]:
    """规划 AI Shorts pipeline。

    从描述/URL 到完整 UGC 视频的端到端计划。
    """
    AICostMode(cost_mode)
    cost_info = AVAILABLE_COST_MODES.get(cost_mode, AVAILABLE_COST_MODES["low_cost"])

    return {
        "pipeline": "ai_shorts",
        "description": description,
        "url": url,
        "user_id": user_id,
        "cost_mode": cost_mode,
        "publish_to": publish_to or [],
        "stages": [
            {"stage": "analyze", "tool": "gemini", "description": "网页抓取 + Gemini 研究"},
            {"stage": "script", "tool": "gemini", "description": "病毒式脚本 (hook→problem→solution→CTA)"},
            {"stage": "actor", "tool": cost_info["actor"], "description": "AI 演员生成"},
            {"stage": "voice", "tool": "elevenlabs", "description": "TTS 旁白 (English/Spanish)"},
            {"stage": "video", "tool": cost_info["video_gen"], "description": "Talking head + lipsync"},
            {"stage": "broll", "tool": cost_info["actor"], "description": "Ken Burns B-roll images"},
            {"stage": "composite", "tool": "ffmpeg", "description": "ASS subtitles + hook overlays"},
            {"stage": "gallery", "tool": "s3", "description": "上传到 public S3 + SEO pages"},
            {"stage": "publish", "tool": "upload_post", "description": "TikTok/Instagram/YouTube"},
        ],
        "estimated_cost_usd": cost_info.get("estimated_cost_usd", 0.65),
        "checkpoint_policy": "guided",
    }


# ── YouTube Studio Pipeline 规划 ──────────────────────

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
            {"stage": "titles", "tool": "gemini", "description": "10 个带 viral_score 的标题"},
            {"stage": "thumbnail", "tool": "flux_2_pro + ffmpeg", "description": "AI 缩略图 + face overlay"},
            {"stage": "description", "tool": "gemini", "description": "SEO 描述 + 章节时间戳 + hashtags"},
            {"stage": "publish", "tool": "upload_post", "description": "一键发布到 YouTube"},
        ],
        "estimated_cost_usd": 0.0,  # Gemini free tier
        "checkpoint_policy": "guided",
    }


# ── 执行器 ────────────────────────────────────────────


async def execute_clip_generator(
    video_path: str,
    user_id: str = "",
    reframing: str = "general",
    target_clips: int = 5,
    with_voiceover: bool = False,
) -> ClipGeneratorJob:
    """执行 Clip Generator pipeline。"""
    mode = ReframingMode(reframing) if reframing in ReframingMode.__members__.values() else ReframingMode.GENERAL
    return generate_clips(
        video_path=video_path,
        user_id=user_id,
        reframing=mode,
        target_clips=target_clips,
        with_voiceover=with_voiceover,
    )


async def execute_ai_short(
    description: str = "",
    url: str = "",
    user_id: str = "",
    cost_mode: str = "low_cost",
    publish_to: list[str] | None = None,
) -> AIShortJob:
    """执行 AI Shorts pipeline。"""
    cm = AICostMode(cost_mode) if cost_mode in AICostMode.__members__.values() else AICostMode.LOW_COST
    return generate_ai_short(
        description=description,
        url=url,
        user_id=user_id,
        cost_mode=cm,
        publish_platforms=publish_to,
    )


async def execute_youtube_studio(
    video_path: str,
    user_id: str = "",
    source_title: str = "",
    source_description: str = "",
) -> YouTubeStudioJob:
    """执行 YouTube Studio pipeline。"""
    return generate_youtube_package(
        video_path=video_path,
        user_id=user_id,
        source_title=source_title,
        source_description=source_description,
    )


# ── 导出 ───────────────────────────────────────────────

__all__ = [
    # 规划
    "plan_clip_generator",
    "plan_ai_short",
    "plan_youtube_studio",
    "AVAILABLE_LAYOUTS",
    "AVAILABLE_COST_MODES",
    "SOCIAL_PLATFORMS",
    # 执行
    "execute_clip_generator",
    "execute_ai_short",
    "execute_youtube_studio",
]