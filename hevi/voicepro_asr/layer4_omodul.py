"""voicepro_asr omodul：文本规划/任务编排，供 studio/production 工作流调用。

ASR 规划：转写 pipeline 规划
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from hevi.voicepro_asr.schemas import (
    ASRConfig,
    ASRProvider,
    make_asr_config,
)


def plan_transcribe_pipeline(
    audio_path: str,
    user_id: str = "",
    provider: str = "faster_whisper",
    model: str = "large-v2",
    language: str = "zh",
) -> dict[str, Any]:
    """规划转写 pipeline。"""
    return {
        "pipeline": "transcribe",
        "audio_path": audio_path,
        "user_id": user_id,
        "provider": provider,
        "model": model,
        "language": language,
        "stages": [
            {"stage": "preprocess", "tool": "ffmpeg", "output": "normalized audio"},
            {"stage": "transcribe", "tool": provider, "output": "transcript + timestamps"},
            {"stage": "verify", "tool": "cer_check", "output": "verified transcript"},
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
    "plan_clip_generator",
    "plan_transcribe_pipeline",
]