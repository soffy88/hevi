"""voicepro_tts omodul：文本规划/任务编排，供 studio/production 工作流调用。

TTS 规划：Clip Generator / AI Shorts / YouTube Studio pipeline 规划
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from hevi.voicepro_tts.schemas import (
    TTSConfig,
    TTSProvider,
    VoiceCloneMode,
    make_tts_config,
)


def plan_clip_generator(
    video_path: str,
    user_id: str = "",
    reframing: str = "general",
    target_clips: int = 5,
    with_voiceover: bool = True,
    with_hook_text: bool = True,
) -> dict[str, Any]:
    """规划 Clip Generator pipeline。"""
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
        "estimated_cost_usd": 0.0,
        "checkpoint_policy": "guided",
    }


def plan_ai_short(
    description: str = "",
    url: str = "",
    user_id: str = "",
    cost_mode: str = "low_cost",
    publish_to: list[str] | None = None,
) -> dict[str, Any]:
    """规划 AI Shorts pipeline。"""
    return {
        "pipeline": "ai_shorts",
        "description": description,
        "url": url,
        "user_id": user_id,
        "cost_mode": cost_mode,
        "publish_to": publish_to or ["tiktok", "instagram", "youtube"],
        "stages": [
            {"stage": "analyze", "tool": "gemini", "description": "网页抓取 + Gemini 研究"},
            {"stage": "script", "tool": "gemini", "description": "病毒式脚本 (hook→problem→solution→CTA)"},
            {"stage": "actor", "tool": "flux_2_pro", "description": "AI 演员生成"},
            {"stage": "voice", "tool": "elevenlabs", "description": "TTS 旁白"},
            {"stage": "video", "tool": "hailuo_2.3_fast", "description": "Talking head + lipsync"},
            {"stage": "broll", "tool": "flux_2_pro", "description": "Ken Burns B-roll images"},
            {"stage": "composite", "tool": "ffmpeg", "description": "ASS subtitles + hook overlays"},
            {"stage": "gallery", "tool": "s3", "description": "上传到 public S3"},
            {"stage": "publish", "tool": "upload_post", "description": "TikTok/Ins/YouTube"},
        ],
        "estimated_cost_usd": 0.65 if cost_mode == "low_cost" else 2.0,
        "checkpoint_policy": "guided",
    }


def plan_youtube_studio(
    video_path: str,
    user_id: str = "",
    source_title: str = "",
    source_description: str = "",
) -> dict[str, Any]:
    """规划 YouTube Studio pipeline。"""
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
        "estimated_cost_usd": 0.0,
        "checkpoint_policy": "guided",
    }


# ── 导出 ───────────────────────────────────────────────

__all__ = [
    "plan_ai_short",
    "plan_clip_generator",
    "plan_youtube_studio",
]