"""voicepro_asr oskill：组合 ≥2 个 oprim 原子，不得引用 omodul。

ASR 技能：组合音频预处理 + 模型推理 + 结果验证
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hevi.voicepro_asr.oprim import (
    make_asr_config,
    normalize_audio,
    transcribe_aliyun_asr,
    transcribe_faster_whisper,
    transcribe_openai_whisper,
    transcribe_whisper_cpp,
    verify_asr_result,
)
from hevi.voicepro_asr.schemas import (
    ASRConfig,
    ASRProvider,
    ASRResult,
    SentenceSegment,
    WordTimestamp,
    make_asr_config,
)

# ── ASR 技能：完整识别流程 ─────────────────────────────


async def skill_transcribe(
    audio_path: str,
    provider: ASRProvider | str = ASRProvider.FASTER_WHISPER,
    model: str = "large-v2",
    language: str = "zh",
    config: ASRConfig | None = None,
) -> ASRResult:
    """ASR 完整识别技能：预处理 → 识别 → 验证。

    根据 provider 自动选择后端。
    """
    if config is None:
        config = make_asr_config(provider, model, language)

    # 1. 音频归一化
    normalized_path = str(Path(audio_path).with_suffix(".wav"))
    normalize_audio(audio_path, normalized_path)

    # 2. 根据 provider 选择后端
    if isinstance(provider, str):
        provider = ASRProvider(provider)

    if provider == ASRProvider.FASTER_WHISPER:
        result = await transcribe_faster_whisper(normalized_path, config)
    elif provider == ASRProvider.WHISPER_CPP:
        result = await transcribe_whisper_cpp(normalized_path, config)
    elif provider == ASRProvider.ALIYUN_ASR:
        result = await transcribe_aliyun_asr(normalized_path, config)
    elif provider == ASRProvider.OPEN_AI_WHISPER:
        result = await transcribe_openai_whisper(normalized_path, config)
    else:
        raise ValueError(f"不支持的 ASR 提供商: {provider}")

    return result


# ── 验证技能 ──────────────────────────────────────────

def skill_verify(
    result: ASRResult,
    expected_text: str | None = None,
    max_cer: float = 0.05,
) -> dict[str, Any]:
    """验证 ASR 结果技能。"""
    return verify_asr_result(result, expected_text, max_cer)


# ── 批量识别技能 ──────────────────────────────────────

async def skill_batch_transcribe(
    audio_paths: list[str],
    provider: ASRProvider | str = ASRProvider.FASTER_WHISPER,
    model: str = "large-v2",
    language: str = "zh",
) -> list[ASRResult]:
    """批量音频识别技能。"""
    results = []
    for path in audio_paths:
        result = await skill_transcribe(path, provider, model, language)
        results.append(result)
    return results


# ── 导出 ───────────────────────────────────────────────

__all__ = [
    "make_asr_config",
    "skill_batch_transcribe",
    "skill_transcribe",
    "skill_verify",
    "verify_asr_result",
]
