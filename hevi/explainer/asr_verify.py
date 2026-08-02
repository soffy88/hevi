"""Whisper/ASR verification boundary for explainer narration.

The primitive is optional at runtime because the current oprim release does
not ship the named ``whisper_asr_verify`` export yet.  When enabled, a failed
text match raises a structured error so the caller can regenerate the segment
instead of silently shipping a bad subtitle track.
"""

from __future__ import annotations

import inspect
import os
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from hevi.audio.asr_verify import (
    character_error_rate as normalized_character_error_rate,
)
from hevi.audio.asr_verify import (
    chunk_word_timestamps_for_mobile,
    normalize_text_for_asr,
)

__all__ = [
    "AsrVerificationError",
    "asr_verification_enabled",
    "character_error_rate",
    "chunk_word_timestamps_for_mobile",
    "normalize_text_for_asr",
    "verify_audio",
]


class AsrVerificationError(RuntimeError):
    pass


def character_error_rate(expected: str, actual: str) -> float:
    return normalized_character_error_rate(expected, actual)


async def verify_audio(
    text: str,
    audio_path: Path,
    *,
    asr: Callable[[Path], Awaitable[str] | str] | Any | None = None,
    max_cer: float = 0.02,
    retries: int = 2,
) -> dict[str, Any]:
    """Transcribe and verify one segment, retrying the injected ASR call."""
    if asr is None:
        try:
            from oprim import whisper_asr_verify

            asr = whisper_asr_verify
        except ImportError as exc:
            raise AsrVerificationError(
                "Whisper ASR 校验能力不可用，请升级 oprim 或关闭 ASR 校验"
            ) from exc
    last: dict[str, Any] = {}
    for attempt in range(1, retries + 2):
        result = asr(audio_path)
        if inspect.isawaitable(result):
            result = await result
        transcript = result.get("text", "") if isinstance(result, dict) else str(result)
        cer = character_error_rate(text, transcript)
        last = {"attempt": attempt, "transcript": transcript, "cer": cer}
        if cer <= max_cer:
            return {**last, "passed": True}
    raise AsrVerificationError(
        f"ASR 校验未通过: CER={last.get('cer', 1.0):.3f} > {max_cer:.3f}"
    )


def asr_verification_enabled() -> bool:
    return os.environ.get("HEVI_EXPLAINER_ASR_VERIFY", "0").lower() in {"1", "true", "yes"}
