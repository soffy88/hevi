"""HEVI-native voice atoms.

These are deliberately small, dependency-light operations.  They capture the
portable capabilities behind lightweight TTS and voice-design systems without
making a third-party Python package part of HEVI's runtime contract.
"""

from __future__ import annotations

import math
import wave
from array import array
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class VoiceConditioning:
    """Resolved controls consumed by the HEVI-native speech skill."""

    language: str
    voice: str
    speed_wpm: int = 170
    pitch: int = 50
    amplitude: int = 100
    sample_rate: int = 22_050
    reference_features: dict[str, Any] | None = None


_LANGUAGE_VOICES = {
    "zh": "zh",
    "zh-cn": "zh",
    "zh-tw": "zh",
    "en": "en-us",
    "en-us": "en-us",
    "en-gb": "en-gb",
    "fr": "fr",
    "de": "de",
    "es": "es",
    "pt": "pt",
    "it": "it",
}

_VOICE_PRESETS: dict[str, tuple[str, int, int]] = {
    # Pocket's catalog names are stable user-facing profiles.  The native
    # runtime keeps the names while resolving them to portable controls.
    "alba": ("en", 170, 53),
    "anna": ("de", 165, 56),
    "azelma": ("fr", 168, 55),
    "estelle": ("fr", 165, 50),
    "juergen": ("de", 155, 38),
    "lola": ("es", 172, 55),
    "rafael": ("pt", 160, 43),
}


def normalize_voice_text(text: str) -> str:
    """Normalize whitespace while preserving punctuation and line semantics."""

    return " ".join(str(text or "").split()).strip()


def split_voice_text(text: str, *, max_chars: int = 180) -> list[str]:
    """Split text at sentence boundaries for low-latency incremental synthesis."""

    normalized = normalize_voice_text(text)
    if not normalized:
        return []
    limit = max(32, int(max_chars))
    chunks: list[str] = []
    current = ""
    for token in normalized.replace("。", "。|").replace("！", "！|").replace("？", "？|").replace(
        ".", ".|"
    ).replace("!", "!|").replace("?", "?|").split("|"):
        token = token.strip()
        if not token:
            continue
        candidate = f"{current} {token}".strip()
        if current and (current[-1] in "。！？.!?" or len(candidate) > limit):
            chunks.append(current)
            current = token
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def probe_reference_audio(audio_path: str | Path) -> dict[str, Any]:
    """Extract non-identifying acoustic controls from a PCM WAV reference.

    The result intentionally contains only aggregate signal statistics.  The
    original path and audio bytes never enter a fingerprint or decision trail.
    """

    path = Path(audio_path).expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"reference audio not found: {path}")
    try:
        with wave.open(str(path), "rb") as stream:
            sample_rate = stream.getframerate()
            channels = stream.getnchannels()
            sample_width = stream.getsampwidth()
            frame_count = stream.getnframes()
            raw = stream.readframes(min(frame_count, sample_rate * 20))
    except (wave.Error, EOFError) as exc:
        raise ValueError("reference audio must be a readable PCM WAV file") from exc

    if not raw or sample_rate <= 0 or channels <= 0:
        raise ValueError("reference audio has no readable samples")
    values: Sequence[int]
    if sample_width == 1:
        values = [sample - 128 for sample in raw]
        scale = 128.0
    elif sample_width == 2:
        values = array("h", raw)
        scale = 32_768.0
    elif sample_width == 4:
        values = array("i", raw)
        scale = 2_147_483_648.0
    else:
        raise ValueError(f"unsupported reference sample width: {sample_width}")

    mono = [float(values[index]) for index in range(0, len(values), channels)]
    if not mono:
        raise ValueError("reference audio has no samples")
    normalized = [sample / scale for sample in mono]
    rms = math.sqrt(sum(sample * sample for sample in normalized) / len(normalized))
    crossings = sum(
        1
        for left, right in pairwise(normalized)
        if (left < 0 <= right) or (left >= 0 > right)
    )
    duration = frame_count / sample_rate
    pitch_hz = max(50.0, min(500.0, crossings * sample_rate / max(1, len(mono) * 2)))
    return {
        "duration_s": round(duration, 3),
        "sample_rate": sample_rate,
        "channels": channels,
        "rms": round(rms, 6),
        "zero_crossing_rate": round(crossings / max(1, len(mono)), 6),
        "pitch_hz": round(pitch_hz, 2),
    }


def resolve_voice_conditioning(
    *,
    voice: str = "",
    language: str = "",
    voice_design: str = "",
    reference_features: dict[str, Any] | None = None,
    speed: float = 1.0,
) -> VoiceConditioning:
    """Turn catalog/reference/design inputs into portable speech controls."""

    voice_key = str(voice or "").strip().lower()
    preset_language, preset_speed, preset_pitch = _VOICE_PRESETS.get(
        voice_key, ("", 170, 50)
    )
    language_key = str(language or preset_language or "en").strip().lower()
    lang = _LANGUAGE_VOICES.get(language_key, _LANGUAGE_VOICES.get(language_key.split("-")[0], "en-us"))
    rate = round(preset_speed * max(0.5, min(2.0, float(speed or 1.0))))
    rate = max(80, min(360, rate))
    pitch = preset_pitch

    if reference_features:
        reference_pitch = float(reference_features.get("pitch_hz") or 180.0)
        pitch = round(50 + 12 * math.log2(max(50.0, min(500.0, reference_pitch)) / 180.0))
        rate = round(rate * (1.0 + min(0.2, float(reference_features.get("rms") or 0.0))))

    design = str(voice_design or "").lower()
    if any(term in design for term in ("deep", "低沉", "成熟", "低音")):
        pitch -= 10
    if any(term in design for term in ("bright", "明亮", "年轻", "高音")):
        pitch += 8
    if any(term in design for term in ("slow", "缓慢", "沉稳", "慢")):
        rate -= 30
    if any(term in design for term in ("fast", "快速", "激昂", "快")):
        rate += 35
    if any(term in design for term in ("whisper", "耳语", "轻声")):
        pitch -= 3

    return VoiceConditioning(
        language=lang,
        voice=voice_key or lang,
        speed_wpm=max(80, min(360, rate)),
        pitch=max(0, min(99, pitch)),
        amplitude=100,
        reference_features=reference_features,
    )


__all__ = [
    "VoiceConditioning",
    "normalize_voice_text",
    "probe_reference_audio",
    "resolve_voice_conditioning",
    "split_voice_text",
]
