"""Measured word-level alignment via local faster-whisper ASR (free, CPU).

Free alternative to the ElevenLabs forced-alignment provider in
``hevi.audio.forced_alignment``: the audio is transcribed locally with
faster-whisper (``word_timestamps=True``), then the ASR character stream is
sequence-matched onto the *known* transcript — the transcript supplies the
text, the ASR supplies the times. The result is ASR-measured, not
forced-aligned; callers label it ``alignment_source="whisper_asr_local"``
with ``is_estimated=False`` (measured, but honestly a different method).

Validated 2026-10-20 against the ElevenLabs ground truth of the storyfilm
pilot (LuxTTS narration, 44.04 s, 245 non-punctuation characters):
small — median |start deviation| 60 ms, P90 120 ms, max 460 ms;
large-v3-turbo — median 60 ms, P90 100 ms, max 360 ms. Shot cutting works
at second scale, so this tier is a drop-in replacement for that use.

Model resolution order: ``HEVI_WHISPER_ALIGN_MODEL`` env, then the local
``/home/soffy/models/faster-whisper-large-v3-turbo`` directory when present
(the same model the ingest line uses), then ``"small"`` (downloaded by
faster-whisper on first use). No network or paid API is involved at
alignment time.
"""

from __future__ import annotations

import asyncio
import logging
import os
from difflib import SequenceMatcher
from pathlib import Path

from hevi.audio.tts_alignment import _WORD_RE, AlignmentUnavailable, WordTiming, _to_ms

logger = logging.getLogger(__name__)

_LOCAL_TURBO_MODEL = Path("/home/soffy/models/faster-whisper-large-v3-turbo")

# (text, start_seconds, end_seconds) as produced by faster-whisper words.
AsrWord = tuple[str, float, float]

_MODEL_CACHE: dict[str, object] = {}


def _resolve_model_name(model: str | None) -> str:
    if model:
        return model
    env_model = os.getenv("HEVI_WHISPER_ALIGN_MODEL", "").strip()
    if env_model:
        return env_model
    if _LOCAL_TURBO_MODEL.is_dir():
        return str(_LOCAL_TURBO_MODEL)
    return "small"


def _transcribe_words(
    audio_path: Path, *, model: str | None = None, language: str = "zh"
) -> list[AsrWord]:
    """Run faster-whisper once and return its word stream (blocking, CPU)."""
    from faster_whisper import WhisperModel

    model_name = _resolve_model_name(model)
    instance = _MODEL_CACHE.get(model_name)
    if instance is None:
        instance = WhisperModel(model_name, device="cpu", compute_type="int8")
        _MODEL_CACHE[model_name] = instance
    segments, _info = instance.transcribe(  # type: ignore[attr-defined]
        str(audio_path), language=language, word_timestamps=True, beam_size=5
    )
    words: list[AsrWord] = []
    for segment in segments:
        for word in segment.words or []:
            text = str(word.word)
            if text.strip():
                words.append((text, float(word.start), float(word.end)))
    return words


def _token_spans(text: str) -> list[tuple[str, int, int]]:
    """Split ``text`` into output tokens with char spans.

    Latin/digit runs follow ``_WORD_RE`` (same tokens as the other alignment
    providers); every other non-whitespace character (CJK chars, punctuation)
    is its own token, mirroring the ElevenLabs provider's output shape.
    Whitespace is dropped, as in ``forced_align_words``.
    """
    spans: list[tuple[str, int, int]] = [
        (match.group(0), match.start(), match.end()) for match in _WORD_RE.finditer(text)
    ]
    covered: set[int] = set()
    for _token_text, start, end in spans:
        covered.update(range(start, end))
    for idx, char in enumerate(text):
        if idx not in covered and not char.isspace():
            spans.append((char, idx, idx + 1))
    spans.sort(key=lambda span: span[1])
    return spans


def match_asr_words_to_text(asr_words: list[AsrWord], text: str) -> tuple[WordTiming, ...]:
    """Project ASR word times onto the known transcript's tokens.

    Pure function (no model, no I/O) so the matching contract is testable
    offline. The transcript's characters are the output skeleton; ASR times
    are anchored onto them via sequence matching, with ASR-recognition
    substitutions spread across the ASR span and missing characters filled
    by interpolation between neighbours.
    """
    if not asr_words:
        raise AlignmentUnavailable("whisper ASR returned no words to align")
    if not text or not text.strip():
        raise AlignmentUnavailable("whisper alignment requires a non-empty transcript")

    token_spans = _token_spans(text)
    # Reference characters: every char that belongs to an output token, plus
    # each token's first/last character positions for regrouping.
    ref_chars: list[str] = []
    token_char_bounds: list[tuple[int, int]] = []
    for _token_text, start, end in token_spans:
        first = len(ref_chars)
        ref_chars.extend(text[idx] for idx in range(start, end))
        token_char_bounds.append((first, len(ref_chars) - 1))
    if not ref_chars:
        raise AlignmentUnavailable("whisper alignment transcript has no alignable characters")

    # ASR character stream: each ASR word's span is spread evenly over its
    # non-whitespace characters.
    asr_chars: list[tuple[str, float, float]] = []
    for word_text, word_start, word_end in asr_words:
        chars = [char for char in word_text if not char.isspace()]
        if not chars:
            continue
        step = max(0.0, word_end - word_start) / len(chars)
        for offset, char in enumerate(chars):
            asr_chars.append((char, word_start + step * offset, word_start + step * (offset + 1)))
    if not asr_chars:
        raise AlignmentUnavailable("whisper ASR words contain no alignable characters")

    matcher = SequenceMatcher(
        None, [char for char, _, _ in asr_chars], ref_chars, autojunk=False
    )
    char_times: list[tuple[float, float] | None] = [None] * len(ref_chars)
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op == "equal":
            for k in range(i2 - i1):
                char_times[j1 + k] = (asr_chars[i1 + k][1], asr_chars[i1 + k][2])
        elif op == "replace" and i2 > i1 and j2 > j1:
            span_start = asr_chars[i1][1]
            span_end = asr_chars[i2 - 1][2]
            step = max(0.0, span_end - span_start) / (j2 - j1)
            for k in range(j2 - j1):
                char_times[j1 + k] = (
                    span_start + step * k,
                    span_start + step * (k + 1),
                )
        # "insert" (extra ASR chars) and "delete" (missing ref chars) leave
        # holes that the interpolation pass below fills.

    anchored = [idx for idx, value in enumerate(char_times) if value is not None]
    if not anchored:
        raise AlignmentUnavailable(
            "whisper ASR transcript does not match the expected text at all"
        )
    for idx in range(len(char_times)):
        if char_times[idx] is not None:
            continue
        prev = max((a for a in anchored if a < idx), default=None)
        nxt = min((a for a in anchored if a > idx), default=None)
        if prev is not None and nxt is not None:
            prev_end = char_times[prev][1]  # type: ignore[index]
            nxt_start = char_times[nxt][0]  # type: ignore[index]
            frac = (idx - prev) / (nxt - prev)
            start = prev_end + (nxt_start - prev_end) * frac
            char_times[idx] = (start, start + 0.05)
        elif prev is not None:
            prev_end = char_times[prev][1]  # type: ignore[index]
            char_times[idx] = (prev_end, prev_end + 0.05)
        else:
            nxt_start = char_times[nxt][0]  # type: ignore[index]
            char_times[idx] = (max(0.0, nxt_start - 0.05), nxt_start)

    # Enforce monotonic starts and positive durations.
    timed_chars: list[tuple[float, float]] = []
    cursor = 0.0
    for value in char_times:
        assert value is not None
        start = max(cursor, value[0])
        end = max(value[1], start + 0.01)
        timed_chars.append((start, end))
        cursor = start

    words: list[WordTiming] = []
    for (token_text, _start, _end), (first_char, last_char) in zip(
        token_spans, token_char_bounds, strict=True
    ):
        start_s = timed_chars[first_char][0]
        end_s = timed_chars[last_char][1]
        words.append(
            WordTiming(text=token_text, start_ms=_to_ms(start_s), end_ms=_to_ms(end_s))
        )
    return tuple(words)


async def whisper_align_words(
    *,
    audio_path: Path,
    text: str,
    model: str | None = None,
    language: str = "zh",
) -> tuple[tuple[WordTiming, ...], None]:
    """Return ASR-measured word timings for ``text`` spoken in ``audio_path``.

    Mirrors ``forced_align_words``' contract; the cost slot is ``None``
    because local CPU inference has no per-call charge.
    """
    if not audio_path.is_file():
        raise AlignmentUnavailable(f"whisper alignment audio not found: {audio_path}")
    if not text or not text.strip():
        raise AlignmentUnavailable("whisper alignment requires a non-empty transcript")

    asr_words = await asyncio.to_thread(
        _transcribe_words, audio_path, model=model, language=language
    )
    words = match_asr_words_to_text(asr_words, text)
    if not words:
        raise AlignmentUnavailable("whisper alignment produced no word timings")
    logger.info(
        "whisper ASR alignment measured %d words for %s (model=%s)",
        len(words),
        audio_path.name,
        _resolve_model_name(model),
    )
    return words, None
