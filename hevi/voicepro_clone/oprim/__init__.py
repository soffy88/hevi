"""voicepro_clone oprim：无状态原子，不得引用 oskill/omodul。

CosyVoice 声纹克隆核心原子。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from hevi.voicepro_clone.schemas import (
    CloneConfig,
    CloneMode,
    CloneProvider,
    CloneResult,
    VoiceProfile,
    make_clone_config,
)

# ── 声纹提取 ─────────────────────────────────────

def extract_voiceprint(audio_path: str) -> dict[str, Any]:
    """从音频中提取声纹特征。

    返回声纹特征向量用于后续克隆。
    """
    from hevi.voicepro.oprim import probe_reference_audio

    features = probe_reference_audio(audio_path)
    digest = hashlib.sha256(
        json.dumps(features, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:16]
    return {
        "voiceprint": digest,
        "features": features,
        "quality": _reference_quality(features),
        "language": "zh",
    }


# ── CosyVoice 克隆 ─────────────────────────────────

def preprocess_text_for_cosyvoice(text: str) -> str:
    """预处理文本供 CosyVoice 使用。

    应用 CV3 前缀（如果需要）。
    """
    # CosyVoice 需要特定格式的文本
    # 例如：添加 [laugh] 等情感标记
    return text


def cosyvoice_zero_shot(
    text: str,
    reference_audio: str,
    prompt_text: str = "",
    speed: float = 1.0,
) -> CloneResult:
    """CosyVoice 零样本克隆。

    从 10-15 秒参考音频克隆声音。
    """
    output_path = f"/tmp/cosyvoice_clone_{hashlib.md5(text.encode()).hexdigest()[:8]}.wav"
    _run_cosyvoice(
        text,
        reference_audio,
        output_path,
        prompt_text=prompt_text,
    )
    return CloneResult(
        audio_path=output_path,
        text=text,
        duration_s=_audio_duration(output_path),
        provider=CloneProvider.COSYVOICE,
        mode=CloneMode.ZERO_SHOT,
        reference_audio=reference_audio,
        similarity_score=0.0,
    )


def cosyvoice_cross_lingual(
    text: str,
    reference_audio: str,
    ref_text: str,
    target_language: str = "zh",
    speed: float = 1.0,
) -> CloneResult:
    """CosyVoice 跨语言克隆。"""
    output_path = f"/tmp/cosyvoice_crosslingual_{hashlib.md5(text.encode()).hexdigest()[:8]}.wav"
    _run_cosyvoice(text, reference_audio, output_path, prompt_text=ref_text, language=target_language)
    return CloneResult(
        audio_path=output_path,
        text=text,
        duration_s=_audio_duration(output_path),
        provider=CloneProvider.COSYVOICE,
        mode=CloneMode.CROSS_LINGUAL,
        reference_audio=reference_audio,
        similarity_score=0.0,
    )


def cosyvoice_instruct(
    text: str,
    reference_audio: str,
    instruct_text: str,
    speed: float = 1.0,
) -> CloneResult:
    """CosyVoice 指令式克隆。"""
    output_path = f"/tmp/cosyvoice_instruct_{hashlib.md5(text.encode()).hexdigest()[:8]}.wav"
    _run_cosyvoice(text, reference_audio, output_path, instruct_text=instruct_text)
    return CloneResult(
        audio_path=output_path,
        text=text,
        duration_s=_audio_duration(output_path),
        provider=CloneProvider.COSYVOICE,
        mode=CloneMode.INSTRUCT,
        reference_audio=reference_audio,
        similarity_score=0.0,
    )


# ── F5-TTS 克隆 ──────────────────────────────────

def f5_tts_zero_shot(
    text: str,
    reference_audio: str,
    ref_text: str = "",
    speed: float = 1.0,
) -> CloneResult:
    """F5-TTS 零样本克隆。"""
    output_path = f"/tmp/f5_tts_clone_{hashlib.md5(text.encode()).hexdigest()[:8]}.wav"
    from hevi.audio.f5_tts_service import f5_tts_synthesize

    reference_text = ref_text or os.getenv("F5_TTS_REFERENCE_TEXT", "")
    _run_async(
        f5_tts_synthesize(
            text=text,
            output_path=Path(output_path),
            reference_audio=reference_audio,
            reference_text=reference_text,
        )
    )
    return CloneResult(
        audio_path=output_path,
        text=text,
        duration_s=_audio_duration(output_path),
        provider=CloneProvider.F5_TTS,
        mode=CloneMode.ZERO_SHOT,
        reference_audio=reference_audio,
        similarity_score=0.0,
    )


# ── 声纹合并/融合 ─────────────────────────────────

def merge_voice_clones(
    audio_paths: list[str],
    weights: list[float] | None = None,
) -> str:
    """融合多个克隆音频到一个 (用于多人对话克隆)。"""
    if not audio_paths:
        raise ValueError("audio_paths cannot be empty")
    if not weights:
        weights = [1.0 / len(audio_paths)] * len(audio_paths)
    if len(weights) != len(audio_paths) or any(weight < 0 for weight in weights):
        raise ValueError("weights must match audio_paths and be non-negative")
    sources = [Path(path) for path in audio_paths]
    missing = [str(path) for path in sources if not path.is_file() or path.stat().st_size == 0]
    if missing:
        raise FileNotFoundError(f"voice clone input missing or empty: {', '.join(missing)}")

    output_path = f"/tmp/merged_voice_{hashlib.md5(str(audio_paths).encode()).hexdigest()[:8]}.wav"
    with tempfile.NamedTemporaryFile(prefix="hevi-voice-merge-", suffix=".wav", delete=False) as tmp:
        temporary = Path(tmp.name)
    filter_parts = [f"[{index}:a]volume={weight}[a{index}]" for index, weight in enumerate(weights)]
    filter_parts.append(
        f"{''.join(f'[a{index}]' for index in range(len(sources)))}"
        f"amix=inputs={len(sources)}:duration=longest:normalize=0[out]"
    )
    command = ["ffmpeg", "-y", "-hide_banner"]
    for source in sources:
        command.extend(["-i", str(source)])
    command.extend([
        "-filter_complex", ";".join(filter_parts),
        "-map", "[out]", "-c:a", "pcm_s16le", str(temporary),
    ])
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0 or not temporary.is_file() or temporary.stat().st_size == 0:
        temporary.unlink(missing_ok=True)
        raise RuntimeError(f"voice clone merge failed: {(completed.stderr or '')[-800:]}")
    temporary.replace(output_path)
    return output_path


# ── 克隆验证 ─────────────────────────────────────

def verify_clone_quality(
    source_audio: str,
    cloned_audio: str,
) -> dict[str, Any]:
    """验证克隆音频的质量。

    计算语音相似度、音色保持等指标。
    """
    from hevi.voicepro.oprim import probe_reference_audio

    source = probe_reference_audio(source_audio)
    cloned = probe_reference_audio(cloned_audio)
    pitch_delta = abs(float(source["pitch_hz"]) - float(cloned["pitch_hz"])) / 450.0
    rms_delta = abs(float(source["rms"]) - float(cloned["rms"]))
    score = max(0.0, min(1.0, 1.0 - pitch_delta - rms_delta))
    return {
        "similarity": round(score, 4),
        "quality": "measured",
        "notes": "acoustic similarity only; identity verification requires a speaker-embedding model",
    }


def _run_cosyvoice(
    text: str,
    reference_audio: str,
    output_path: str,
    *,
    prompt_text: str = "",
    language: str = "",
    instruct_text: str = "",
) -> None:
    from hevi.audio.cosyvoice_service import cosyvoice_synthesize

    line = SimpleNamespace(
        text=text,
        voice_ref=reference_audio,
        ref_text=prompt_text,
        instruct_text=instruct_text,
    )
    _run_async(
        cosyvoice_synthesize(
            config={"language": language} if language else None,
            script=[line],
            output_path=Path(output_path),
        )
    )


def _run_async(coroutine: Any) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coroutine)
    if hasattr(coroutine, "close"):
        coroutine.close()
    raise RuntimeError("voice clone sync atom cannot run inside an active event loop")


def _audio_duration(path: str) -> float:
    completed = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", path],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"ffprobe clone output failed: {completed.stderr[-600:]}")
    return float(completed.stdout.strip() or 0.0)


def _reference_quality(features: dict[str, Any]) -> str:
    duration = float(features.get("duration_s") or 0.0)
    rms = float(features.get("rms") or 0.0)
    if duration >= 3 and rms > 0.005:
        return "usable"
    return "insufficient"


# ── 导出 ───────────────────────────────────────────────

__all__ = [
    "CloneConfig",
    "CloneMode",
    "CloneProvider",
    "CloneResult",
    "VoiceProfile",
    "cosyvoice_cross_lingual",
    "cosyvoice_instruct",
    "cosyvoice_zero_shot",
    "extract_voiceprint",
    "f5_tts_zero_shot",
    "make_clone_config",
    "merge_voice_clones",
    "preprocess_text_for_cosyvoice",
    "verify_clone_quality",
]
