"""voicepro_tts oprim：无状态原子，不得引用 oskill/omodul。

TTS 语音生成原子：Edge-TTS / OpenAI TTS / MiniMax TTS / CosyVoice / F5-TTS / Kokoro / Azure TTS
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import importlib
import json
import os
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
    api_key = os.getenv("MINIMAX_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("MiniMax TTS requires MINIMAX_API_KEY")
    output = Path(output_path or "/tmp/minimax_tts_output.mp3")
    endpoint = os.getenv("MINIMAX_TTS_URL", "https://api.minimax.io/v1/t2a_v2").strip()
    payload = {
        "model": os.getenv("MINIMAX_TTS_MODEL", "speech-2.6-hd"),
        "text": text,
        "stream": False,
        "voice_setting": {"voice_id": voice, "speed": speed, "vol": 1, "pitch": 0},
        "audio_setting": {"format": output.suffix.lstrip(".") or "mp3"},
    }
    import httpx

    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            response = await client.post(
                endpoint,
                headers={"Authorization": f"Bearer {api_key}"},
                json=payload,
            )
            response.raise_for_status()
            body = response.json()
    except (httpx.HTTPError, OSError, ValueError) as exc:
        raise RuntimeError(f"MiniMax TTS request failed: {exc}") from exc
    encoded = ((body.get("data") or {}).get("audio") if isinstance(body, dict) else None)
    if not encoded:
        raise RuntimeError("MiniMax TTS response did not contain audio")
    try:
        audio = bytes.fromhex(str(encoded))
    except ValueError:
        try:
            audio = base64.b64decode(str(encoded), validate=True)
        except (ValueError, binascii.Error) as exc:
            raise RuntimeError("MiniMax TTS returned invalid audio encoding") from exc
    _write_nonempty_audio(output, audio, "MiniMax")
    return make_tts_result(audio_path=str(output), text=text, voice=voice, provider=TTSProvider.MINIMAX_TTS)


# ── CosyVoice 合成 ─────────────────────────────────

async def synthesize_cosyvoice(
    text: str,
    voice_ref: str = "",
    inference_mode: str = "zero_shot",
    speed: float = 1.0,
    output_path: str = "",
) -> TTSSResult:
    """使用 CosyVoice 合成语音（支持零样本克隆）。"""
    from types import SimpleNamespace

    from hevi.audio.cosyvoice_service import cosyvoice_synthesize

    output = Path(output_path or "/tmp/cosyvoice_output.wav")
    line = SimpleNamespace(
        text=text,
        voice_ref=voice_ref or None,
        inference_mode=inference_mode,
    )
    await cosyvoice_synthesize(script=[line], output_path=output)
    _require_nonempty_audio(output, "CosyVoice")
    return make_tts_result(audio_path=str(output), text=text, voice=voice_ref or "default", provider=TTSProvider.COSYVOICE_TTS)


# ── F5-TTS 合成 ────────────────────────────────────

async def synthesize_f5_tts(
    text: str,
    model: str = "F5TTS_v1_Base",
    voice_ref: str = "",
    speed: float = 1.0,
    output_path: str = "",
) -> TTSSResult:
    """使用 F5-TTS 合成语音（支持零样本克隆）。"""
    from hevi.audio.f5_tts_service import f5_tts_synthesize

    reference_text = os.getenv("F5_TTS_REFERENCE_TEXT", "").strip()
    if not voice_ref:
        raise RuntimeError("F5-TTS requires a reference audio path")
    if not reference_text:
        raise RuntimeError("F5-TTS requires F5_TTS_REFERENCE_TEXT")
    output = Path(output_path or "/tmp/f5_tts_output.wav")
    await f5_tts_synthesize(
        text=text,
        output_path=output,
        reference_audio=voice_ref,
        reference_text=reference_text,
        speed=speed,
        model_name=model,
    )
    _require_nonempty_audio(output, "F5-TTS")
    return make_tts_result(audio_path=str(output), text=text, voice=voice_ref or "default", provider=TTSProvider.F5_TTS)


# ── Kokoro TTS 合成 ────────────────────────────────

async def synthesize_kokoro_tts(
    text: str,
    voice: str = "af_bella",
    speed: float = 1.0,
    output_path: str = "",
) -> TTSSResult:
    """使用 Kokoro TTS 合成语音。"""
    output = Path(output_path or "/tmp/kokoro_output.wav")
    try:
        sf = importlib.import_module("soundfile")
        pipeline_name = "KPipeline"
        KPipeline = getattr(importlib.import_module("kokoro"), pipeline_name)
    except ImportError as exc:
        raise RuntimeError("Kokoro TTS requires kokoro and soundfile") from exc
    language = os.getenv("KOKORO_LANG_CODE", "a").strip() or "a"
    try:
        pipeline = KPipeline(lang_code=language)
        chunks = [audio for _, _, audio in pipeline(text, voice=voice, speed=speed)]
        if not chunks:
            raise RuntimeError("Kokoro returned no audio frames")
        import numpy as np

        output.parent.mkdir(parents=True, exist_ok=True)
        sf.write(str(output), np.concatenate(chunks), 24_000)
    except Exception as exc:
        raise RuntimeError(f"Kokoro TTS failed: {exc}") from exc
    _require_nonempty_audio(output, "Kokoro")
    return make_tts_result(audio_path=str(output), text=text, voice=voice, provider=TTSProvider.KOKORO_TTS)


# ── Azure TTS 合成 ─────────────────────────────────

async def synthesize_azure_tts(
    text: str,
    voice: str = "zh-CN-Xiaoyun",
    speed: float = 1.0,
    output_path: str = "",
) -> TTSSResult:
    """使用 Azure TTS 合成语音。"""
    key = os.getenv("AZURE_SPEECH_KEY", "").strip()
    region = os.getenv("AZURE_SPEECH_REGION", "").strip()
    if not key or not region:
        raise RuntimeError("Azure TTS requires AZURE_SPEECH_KEY and AZURE_SPEECH_REGION")
    try:
        speechsdk = importlib.import_module("azure.cognitiveservices.speech")
    except ImportError as exc:
        raise RuntimeError("Azure TTS requires azure-cognitiveservices-speech") from exc
    output = Path(output_path or "/tmp/azure_tts_output.wav")

    def _run() -> None:
        speech_config = speechsdk.SpeechConfig(subscription=key, region=region)
        speech_config.speech_synthesis_voice_name = voice
        audio_config = speechsdk.audio.AudioOutputConfig(filename=str(output))
        synthesizer = speechsdk.SpeechSynthesizer(
            speech_config=speech_config,
            audio_config=audio_config,
        )
        result = synthesizer.speak_text_async(text).get()
        if result.reason != speechsdk.ResultReason.SynthesizingAudioCompleted:
            details = getattr(result, "cancellation_details", None)
            raise RuntimeError(str(getattr(details, "error_details", result.reason)))

    await asyncio.to_thread(_run)
    _require_nonempty_audio(output, "Azure")
    return make_tts_result(audio_path=str(output), text=text, voice=voice, provider=TTSProvider.AZURE_TTS)


def _write_nonempty_audio(path: Path, data: bytes, provider: str) -> None:
    if not data:
        raise RuntimeError(f"{provider} returned empty audio")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    _require_nonempty_audio(path, provider)


def _require_nonempty_audio(path: Path, provider: str) -> None:
    if not path.is_file() or path.stat().st_size == 0:
        raise RuntimeError(f"{provider} completed without a non-empty audio artifact")


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
