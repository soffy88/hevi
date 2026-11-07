"""Measured word-level alignment via ElevenLabs forced alignment (through Monid).

Fills the gap in ``hevi.audio.tts_alignment``: LuxTTS only returns sentence-level
timings, so word timestamps were duration-weighted *estimates*. This provider
aligns a known transcript to its audio and returns *measured* millisecond
word boundaries (word-level {text, start, end} plus a per-word loss).

Access goes through Monid (provider ``elevenlabs``, endpoint
``/v1/forced-alignment``, $0.22 per hour of audio, prorated per second), which
needs ``MONID_API_KEY`` in the environment. The audio must be reachable via a
public HTTPS URL, so local files are uploaded to Monid sfs first (free storage,
signed URLs, cleaned up by the caller when needed).
"""

from __future__ import annotations

import logging
import math
from pathlib import Path

from hevi.audio import monid_client
from hevi.audio.tts_alignment import AlignmentUnavailable, WordTiming, _to_ms

logger = logging.getLogger(__name__)

_MAX_AUDIO_BYTES = 20 * 1024 * 1024  # endpoint limit: 20MB


async def forced_align_words(
    *,
    audio_path: Path,
    text: str,
    sfs_path: str | None = None,
    timeout_s: float = 300.0,
    expected_minutes: float = 1.0,
) -> tuple[tuple[WordTiming, ...], float | None]:
    """Return measured word timings for ``text`` spoken in ``audio_path``.

    Whitespace-only tokens from the provider are dropped; punctuation stays
    attached to its word, matching the provider output format.
    """
    if not audio_path.is_file():
        raise AlignmentUnavailable(f"forced alignment audio not found: {audio_path}")
    if audio_path.stat().st_size > _MAX_AUDIO_BYTES:
        raise AlignmentUnavailable(
            f"forced alignment audio exceeds 20MB limit: {audio_path.stat().st_size} bytes"
        )
    if not text or not text.strip():
        raise AlignmentUnavailable("forced alignment requires a non-empty transcript")

    upload_path = sfs_path or f"hevi-tts-align/{audio_path.name}"
    audio_url = await monid_client.sfs_upload_file(audio_path, sfs_path=upload_path)

    # The admission hold in Monid is sized by expected_duration_minutes; it is
    # a hint only — settlement bills the actual aligned duration. 60s covers
    # typical single-cue narrations; pass larger values for long audio.
    duration_minutes = max(1, math.ceil(expected_minutes))
    output, cost = await monid_client.run_endpoint(
        "elevenlabs",
        "/v1/forced-alignment",
        body={
            "audio_url": audio_url,
            "text": text,
            "expected_duration_minutes": duration_minutes,
        },
        timeout_s=timeout_s,
    )

    raw_words = output.get("words")
    if not isinstance(raw_words, list):
        raise AlignmentUnavailable(f"forced alignment returned no words: {str(output)[:300]}")

    words = tuple(
        WordTiming(
            text=str(w.get("text", "")),
            start_ms=_to_ms(float(w.get("start", 0.0))),
            end_ms=_to_ms(float(w.get("end", 0.0))),
        )
        for w in raw_words
        if isinstance(w, dict) and str(w.get("text", "")).strip()
    )
    if not words:
        raise AlignmentUnavailable("forced alignment returned only empty tokens")
    logger.info(
        "forced alignment measured %d words for %s (cost=%s)",
        len(words),
        audio_path.name,
        cost,
    )
    return words, cost
