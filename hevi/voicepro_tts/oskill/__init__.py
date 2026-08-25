"""voicepro_tts oskill：组合 ≥2 个 oprim 原子，不得引用 omodul。

TTS 技能：组合语音生成 + 声纹克隆 + 音频后处理
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hevi.voicepro_tts.oprim import (
    make_tts_config,
    make_tts_result,
    synthesize_azure_tts,
    synthesize_cosyvoice,
    synthesize_edge_tts,
    synthesize_f5_tts,
    synthesize_kokoro_tts,
    synthesize_minimax_tts,
    synthesize_openai_tts,
    synthesize_tts,
)
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

# ── TTS 技能：完整语音合成流程 ─────────────────────────


async def skill_synthesize_tts(
    text: str,
    provider: TTSProvider | str = TTSProvider.EDGE_TTS,
    voice: str = "zh-CN-Xiaoyan",
    speed: float = 1.0,
    config: TTSConfig | None = None,
) -> TTSSResult:
    """TTS 完整合成技能：配置 → 合成 → 后处理。

    根据 provider 自动选择后端。
    """
    if config is None:
        config = make_tts_config(provider, voice, speed)

    # 合成语音
    result = await synthesize_tts(text, config)

    return result


# ── 声纹克隆技能 ────────────────────────────────────

async def skill_clone_voice(
    text: str,
    voice_ref: str = "",
    provider: TTSProvider | str = TTSProvider.COSYVOICE_TTS,
    speed: float = 1.0,
) -> TTSSResult:
    """声纹克隆技能：从参考音频克隆声音。

    支持 CosyVoice / F5-TTS / OpenAI TTS 的声纹克隆。
    """
    if isinstance(provider, str):
        provider = TTSProvider(provider)

    if provider == TTSProvider.COSYVOICE_TTS:
        return await synthesize_cosyvoice(text, voice_ref, "zero_shot", speed)
    if provider == TTSProvider.F5_TTS:
        return await synthesize_f5_tts(text, voice_ref=voice_ref, speed=speed)
    if provider == TTSProvider.OPEN_AI_TTS:
        return await synthesize_openai_tts(text, voice=voice_ref, speed=speed)
    raise ValueError(f"不支持的声纹克隆提供商: {provider}")


# ── 批量合成技能 ────────────────────────────────────

async def skill_batch_synthesize(
    texts: list[str],
    provider: TTSProvider | str = TTSProvider.EDGE_TTS,
    voice: str = "zh-CN-Xiaoyan",
    speed: float = 1.0,
) -> list[TTSSResult]:
    """批量 TTS 合成技能。"""
    results = []
    for text in texts:
        result = await skill_synthesize_tts(text, provider, voice, speed)
        results.append(result)
    return results


# ── 导出 ───────────────────────────────────────────────

__all__ = [
    "make_tts_config",
    "make_tts_result",
    "skill_batch_synthesize",
    "skill_clone_voice",
    "skill_synthesize_tts",
]
