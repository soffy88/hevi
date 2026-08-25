"""voicepro_translate omodul：文本规划/任务编排，供 studio/production 工作流调用。

翻译规划。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from hevi.voicepro_translate.schemas import (
    TranslateConfig,
    TranslateProvider,
    make_translate_config,
)


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
            {"stage": "script", "tool": "gemini", "description": "病毒式脚本"},
            {"stage": "actor", "tool": "flux_2_pro", "description": "AI 演员生成"},
            {"stage": "voice", "tool": "elevenlabs", "description": "TTS 旁白"},
            {"stage": "video", "tool": "hailuo_2.3_fast", "description": "Talking head + lipsync"},
            {"stage": "broll", "tool": "flux_2_pro", "description": "Ken Burns B-roll"},
            {"stage": "composite", "tool": "ffmpeg", "description": "ASS subtitles + overlays"},
            {"stage": "publish", "tool": "upload_post", "description": "TikTok/Ins/YouTube"},
        ],
        "estimated_cost_usd": 0.65 if cost_mode == "low_cost" else 2.0,
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
        "stages": [
            {"stage": "titles", "tool": "gemini"},
            {"stage": "thumbnail", "tool": "flux_2_pro + ffmpeg"},
            {"stage": "description", "tool": "gemini"},
            {"stage": "publish", "tool": "upload_post"},
        ],
    }


def plan_clip_generator(
    video_path: str,
    user_id: str = "",
    reframing: str = "general",
    target_clips: int = 5,
) -> dict[str, Any]:
    """规划 Clip Generator pipeline。"""
    return {
        "pipeline": "clip_generator",
        "stages": [
            {"stage": "transcribe", "tool": "faster-whisper"},
            {"stage": "detect_scenes", "tool": "PySceneDetect"},
            {"stage": "reframe", "tool": reframing},
            {"stage": "subtitles", "tool": "ass_generator"},
            {"stage": "compose", "tool": "ffmpeg"},
        ],
    }


__all__ = [
    "plan_ai_short",
    "plan_clip_generator",
    "plan_youtube_studio",
]