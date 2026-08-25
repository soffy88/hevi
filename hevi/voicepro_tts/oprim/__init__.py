"""voicepro_tts oprim：无状态原子，不得引用 oskill/omodul。

TTS 语音生成原子：Edge-TTS / OpenAI TTS / MiniMax TTS / CosyVoice / F5-TTS / Kokoro / Azure TTS
"""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path
from typing import Any

from hevi.voicepro_tts.schemas import (
    AudioOutput,
    TTSConfig,
    TTSProvider,
    TTSSResult,
    VoiceCloneMode,
    VoiceConfig,
    make_tts_config,
    make_tts_result,
)

# ── Edge-TTS 合成 ───────────────────────────────────

async def synthesize_edge_tts(
    text: str,
    voice: str = "zh-CN-Xiaoyan",
    speed: float = 1.0,
    pitch: float = 1.0,
    output_path: str = "",
) -> TTSSResult:
    """使用 Edge-TTS 合成语音。

    支持 100+ 语言，400+ 声音。
    """
    try:
        import edge_tts
    except ImportError:
        raise RuntimeError("edge-tts 未安装")

    if not output_path:
        output_path = "/tmp/edge_tts_output.mp3"

    communicate = edge_tts.Communicate(text, voice, rate=f"{int((speed - 1.0) * 100)}%", pitch=f"{int((pitch - 1.0) * 100)}%")
    await communicate.save(output_path)

    return make_tts_result(
        audio_path=output_path,
        text=text,
        duration_s=0.0,  # 由 ffprobe 获取
        voice=voice,
        provider=TTSProvider.EDGE_TTS,
    )


# ── OpenAI TTS 合成 ─────────────────────────────────

async def synthesize_openai_tts(
    text: str,
    voice: str = "alloy",
    model: str = "tts-1",
    speed: float = 1.0,
    output_path: str = "",
) -> TTSSResult:
    """使用 OpenAI TTS 合成语音。"""
    try:
        from openai import AsyncOpenAI
    except ImportError:
        raise RuntimeError("openai 未安装")

    if not output_path:
        output_path = "/tmp/openai_tts_output.mp3"

    client = AsyncOpenAI()
    response = await client.audio.speech.create(
        model=model,
        voice=voice,
        input=text,
        speed=speed,
    )
    response.write_to_file(output_path)

    return make_tts_result(
        audio_path=output_path,
        text=text,
        duration_s=0.0,
        voice=voice,
        provider=TTSProvider.OPEN_AI_TTS,
    )


# ── MiniMax TTS 合成 ────────────────────────────────

async def synthesize_minimax_tts(
    text: str,
    voice: str = "Chinese Male",
    speed: float = 1.0,
    output_path: str = "",
) -> TTSSResult:
    """使用 MiniMax TTS 合成语音。"""
    # 占位：实际实现需调用 MiniMax API
    return make_tts_result(
        audio_path=output_path or "/tmp/minimax_tts_output.mp3",
        text=text,
        duration_s=0.0,
        voice=voice,
        provider=TTSProvider.MINIMAX_TTS,
    )


# ── CosyVoice 合成 ─────────────────────────────────

async def synthesize_cosyvoice(
    text: str,
    voice_ref: str = "",
    inference_mode: str = "zero_shot",
    speed: float = 1.0,
    output_path: str = "",
) -> TTSSResult:
    """使用 CosyVoice 合成语音（支持零样本克隆）。"""
    # 占位：实际实现需调用 CosyVoice 模型
    return make_tts_result(
        audio_path=output_path or "/tmp/cosyvoice_output.wav",
        text=text,
        duration_s=0.0,
        voice=voice_ref or "default",
        provider=TTSProvider.COSYVOICE_TTS,
    )


# ── F5-TTS 合成 ────────────────────────────────────

async def synthesize_f5_tts(
    text: str,
    model: str = "F5TTS_v1_Base",
    voice_ref: str = "",
    speed: float = 1.0,
    output_path: str = "",
) -> TTSSResult:
    """使用 F5-TTS 合成语音（支持零样本克隆）。"""
    # 占位：实际实现需调用 F5-TTS 模型
    return make_tts_result(
        audio_path=output_path or "/tmp/f5_tts_output.wav",
        text=text,
        duration_s=0.0,
        voice=voice_ref or "default",
        provider=TTSProvider.F5_TTS,
    )


# ── Kokoro TTS 合成 ────────────────────────────────

async def synthesize_kokoro_tts(
    text: str,
    voice: str = "af_bella",
    speed: float = 1.0,
    output_path: str = "",
) -> TTSSResult:
    """使用 Kokoro TTS 合成语音。"""
    # 占位：实际实现需调用 Kokoro 模型
    return make_tts_result(
        audio_path=output_path or "/tmp/kokoro_output.wav",
        text=text,
        duration_s=0.0,
        voice=voice,
        provider=TTSProvider.KOKORO_TTS,
    )


# ── Azure TTS 合成 ─────────────────────────────────

async def synthesize_azure_tts(
    text: str,
    voice: str = "zh-CN-Xiaoyun",
    speed: float = 1.0,
    output_path: str = "",
) -> TTSSResult:
    """使用 Azure TTS 合成语音。"""
    # 占位：实际实现需调用 Azure SDK
    return make_tts_result(
        audio_path=output_path or "/tmp/azure_tts_output.wav",
        text=text,
        duration_s=0.0,
        voice=voice,
        provider=TTSProvider.AZURE_TTS,
    )


# ── 通用 TTS 合成（根据 provider 自动选择） ─────────

async def synthesize_tts(
    text: str,
    config: TTSConfig,
) -> TTSSResult:
    """通用 TTS 合成：根据 provider 自动选择后端。"""
    if config.provider == TTSProvider.EDGE_TTS:
        return await synthesize_edge_tts(text, config.voice, config.speed, config.pitch)
    if config.provider == TTSProvider.OPEN_AI_TTS:
        return await synthesize_openai_tts(text, config.voice, speed=config.speed)
    if config.provider == TTSProvider.MINIMAX_TTS:
        return await synthesize_minimax_tts(text, config.voice, config.speed)
    if config.provider == TTSProvider.COSYVOICE_TTS:
        return await synthesize_cosyvoice(text, config.clone_source_audio, config.clone_mode.value, config.speed)
    if config.provider == TTSProvider.F5_TTS:
        return await synthesize_f5_tts(text, voice_ref=config.clone_source_audio, speed=config.speed)
    if config.provider == TTSProvider.KOKORO_TTS:
        return await synthesize_kokoro_tts(text, config.voice, config.speed)
    if config.provider == TTSProvider.AZURE_TTS:
        return await synthesize_azure_tts(text, config.voice, config.speed)
    raise ValueError(f"不支持的 TTS 提供商: {config.provider}")


# ── 导出 ───────────────────────────────────────────────

__all__ = [
    "AudioOutput",
    "TTSConfig",
    "TTSProvider",
    "TTSSResult",
    "VoiceCloneMode",
    "VoiceConfig",
    "make_tts_config",
    "make_tts_result",
    "synthesize_azure_tts",
    "synthesize_cosyvoice",
    "synthesize_edge_tts",
    "synthesize_f5_tts",
    "synthesize_kokoro_tts",
    "synthesize_minimax_tts",
    "synthesize_openai_tts",
    "synthesize_tts",
]
