"""TTS audio alignment artifact with LuxTTS as the default synthesis backend.

The LuxTTS HTTP contract returns audio and sentence-level timings, not native
word boundaries. Its alignment output therefore labels duration-weighted word
timings as estimates. Deployments that explicitly set
HEVI_TTS_ALIGNMENT_PROVIDER=edge_tts can request Edge's native word boundaries.
All measured durations and persisted timestamps use integer milliseconds.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import uuid
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

_WORD_RE = re.compile(r"[\u3400-\u9fff]|[^\W_]+(?:['’][^\W_]+)*", re.UNICODE)


@dataclass(frozen=True)
class WordTiming:
    text: str
    start_ms: int
    end_ms: int


@dataclass(frozen=True)
class PhraseTiming:
    phrase_id: str
    start_ms: int
    end_ms: int


@dataclass(frozen=True)
class AudioAlignment:
    audio_id: str
    duration_ms: int
    words: tuple[WordTiming, ...] = field(default_factory=tuple)
    phrases: tuple[PhraseTiming, ...] = field(default_factory=tuple)
    alignment_source: str = "edge_tts_word_boundary"
    is_estimated: bool = False
    tts_provider: str = "edge_tts"


class AlignmentUnavailable(RuntimeError):
    """Provider synthesis/duration probe failed; no placeholder artifact is returned."""


def _to_ms(seconds: float) -> int:
    return round(seconds * 1000)


def _temp_root() -> Path:
    root = Path(__file__).resolve().parents[2] / ".tmp"
    root.mkdir(parents=True, exist_ok=True)
    return root


def probe_duration_ms(audio_path: Path) -> int:
    """Measure actual audio duration with FFmpeg/ffprobe; never infer file length."""
    import tempfile

    root = _temp_root()
    try:
        with tempfile.TemporaryDirectory(prefix="hevi_tts_probe_", dir=root) as td:
            wav = Path(td) / "probe.wav"
            dec = subprocess.run(
                [
                    "ffmpeg", "-v", "error", "-y", "-i", str(audio_path),
                    "-ar", "44100", "-ac", "1", str(wav),
                ],
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
            target = wav if dec.returncode == 0 and wav.exists() else audio_path
            proc = subprocess.run(
                [
                    "ffprobe", "-v", "error", "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1", str(target),
                ],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            if proc.returncode != 0:
                raise RuntimeError((proc.stderr or "ffprobe failed")[-1000:])
            duration = float(proc.stdout.strip())
            if duration <= 0:
                raise RuntimeError("ffprobe returned non-positive audio duration")
            return _to_ms(duration)
    except Exception as exc:
        raise AlignmentUnavailable(f"cannot probe duration of {audio_path}: {exc}") from exc


def _token_weight(token: str) -> int:
    """Rough speech-duration weight used only for explicitly marked estimates."""
    if all("\u3400" <= char <= "\u9fff" for char in token):
        return max(1, len(token))
    vowels = re.findall(r"[aeiouy]+", token.lower())
    return max(1, len(vowels))


def _estimated_word_timings(text: str, duration_ms: int) -> tuple[WordTiming, ...]:
    """Spread text tokens across measured audio duration; output is *not* forced alignment."""
    tokens = [match.group(0) for match in _WORD_RE.finditer(text)]
    if not tokens:
        return ()
    if duration_ms < len(tokens) * 2:
        raise AlignmentUnavailable(
            f"audio is too short for an explicitly estimated token timeline: "
            f"{duration_ms}ms for {len(tokens)} tokens"
        )

    head_pad = min(40, max(0, duration_ms // 30))
    tail_pad = min(120, max(0, duration_ms // 20))
    gap = min(8, max(0, duration_ms // max(1, len(tokens) * 40)))
    available = max(len(tokens), duration_ms - head_pad - tail_pad - gap * (len(tokens) - 1))
    weights = [_token_weight(token) for token in tokens]
    weight_total = sum(weights)
    durations = [max(1, available * weight // weight_total) for weight in weights]
    # Keep rounding drift in the final token so all boundaries stay inside the audio.
    durations[-1] = max(1, available - sum(durations[:-1]))

    cursor = head_pad
    aligned: list[WordTiming] = []
    for token, length in zip(tokens, durations, strict=True):
        end = min(duration_ms, cursor + length)
        if end <= cursor:
            raise AlignmentUnavailable("cannot construct positive-duration token timings")
        aligned.append(WordTiming(token, cursor, end))
        cursor = end + gap
    return tuple(aligned)


async def _synthesize_edge_with_word_boundaries(
    *, text: str, voice: str, output_path: Path | None
) -> tuple[Path, tuple[WordTiming, ...], str]:
    from oprim import edge_tts_word_boundary

    result = await edge_tts_word_boundary(text, voice, output_path=output_path)
    audio_path = Path(result["audio_path"])
    words = tuple(
        WordTiming(str(word["text"]), _to_ms(float(word["start"])), _to_ms(float(word["end"])))
        for word in result.get("words", [])
    )
    return audio_path, words, "edge_tts_word_boundary"


async def _synthesize_lux_audio(*, text: str, voice: str, output_path: Path) -> str:
    """Synthesize through the shared LuxTTS-first fallback router, independent of formal style overrides."""
    from hevi.audio.audio_router import _synthesize_luxtts_with_fallback

    preferred_voice = voice.strip().lower()
    remote_voice = preferred_voice if preferred_voice in {"auto", "soffy", "en_male"} else "auto"
    result = await _synthesize_luxtts_with_fallback(
        text=text,
        output_path=output_path,
        voice=remote_voice,
        instruct=None,
        requested_provider="lux_tts",
        remote_voice=remote_voice,
    )
    return str(result.get("actual_provider") or result.get("requested_provider") or "unknown")


async def synthesize_with_alignment(
    *,
    text: str,
    voice: str,
    audio_id: str = "",
    output_path: Path | None = None,
) -> tuple[Path, AudioAlignment]:
    """Synthesize audio and persist an alignment object.

    LuxTTS is the default and actual audio source. Since its HTTP endpoint has no
    word-boundary API, LuxTTS word timestamps are explicitly marked estimated.
    Set HEVI_TTS_ALIGNMENT_PROVIDER=edge_tts only to opt into native Edge word
    boundaries. Failure of synthesis or duration probing remains fail-loud.
    """
    if not text or not text.strip():
        raise AlignmentUnavailable("empty text")

    root = _temp_root()
    configured_output = Path(output_path) if output_path is not None else None
    requested_suffix = configured_output.suffix.lower() if configured_output else ".wav"
    if requested_suffix not in {".wav", ".mp3"}:
        raise AlignmentUnavailable(f"unsupported alignment output format: {requested_suffix}")

    if requested_suffix == ".wav":
        synthesis_path = configured_output or (root / f"tts_alignment_{uuid.uuid4().hex}.wav")
    else:
        synthesis_path = root / f"tts_alignment_{uuid.uuid4().hex}.wav"

    provider_mode = os.getenv("HEVI_TTS_ALIGNMENT_PROVIDER", "lux_tts").strip().lower()
    if provider_mode in {"edge", "edge-tts", "edge_tts"}:
        try:
            audio_path, words, alignment_source = await _synthesize_edge_with_word_boundaries(
                text=text,
                voice=voice,
                output_path=configured_output,
            )
            actual_provider = "edge_tts"
        except Exception as exc:
            raise AlignmentUnavailable(f"explicit Edge TTS alignment failed: {exc}") from exc
    elif provider_mode in {"lux", "lux_tts", "luxtts", "auto"}:
        try:
            synthesis_path.parent.mkdir(parents=True, exist_ok=True)
            actual_provider = await _synthesize_lux_audio(
                text=text, voice=voice, output_path=synthesis_path
            )
            if not synthesis_path.is_file() or synthesis_path.stat().st_size <= 0:
                raise RuntimeError("TTS router returned without a non-empty audio artifact")
            if requested_suffix == ".mp3":
                assert configured_output is not None
                configured_output.parent.mkdir(parents=True, exist_ok=True)
                proc = subprocess.run(
                    [
                        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                        "-i", str(synthesis_path), "-ar", "48000", "-ac", "1",
                        "-codec:a", "libmp3lame", "-q:a", "3", str(configured_output),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=180,
                    check=False,
                )
                if proc.returncode != 0 or not configured_output.is_file() or configured_output.stat().st_size <= 0:
                    raise RuntimeError(f"cannot encode LuxTTS output as MP3: {(proc.stderr or '')[-1000:]}")
                audio_path = configured_output
            else:
                audio_path = synthesis_path
            duration_ms = probe_duration_ms(audio_path)
            words = _estimated_word_timings(text, duration_ms)
            alignment_source = f"{actual_provider}_duration_weighted_estimate"
            logger.warning(
                "LuxTTS audio has no native word timestamps; returning explicitly marked "
                "duration-weighted estimates for audio_id=%s",
                audio_id or audio_path.stem,
            )
        except Exception as exc:
            raise AlignmentUnavailable(f"LuxTTS synthesis/alignment failed: {exc}") from exc
    else:
        raise AlignmentUnavailable(
            f"unsupported HEVI_TTS_ALIGNMENT_PROVIDER={provider_mode!r}; "
            "choose lux_tts or edge_tts"
        )

    duration_ms = probe_duration_ms(audio_path)
    aid = audio_id or audio_path.stem
    if words:
        phrase_start = words[0].start_ms
        phrase_end = words[-1].end_ms
    else:
        phrase_start, phrase_end = 0, duration_ms
    phrase = PhraseTiming(aid, phrase_start, phrase_end)
    alignment = AudioAlignment(
        aid,
        duration_ms,
        words,
        (phrase,),
        alignment_source=alignment_source,
        is_estimated=alignment_source != "edge_tts_word_boundary",
        tts_provider=actual_provider,
    )
    return audio_path, alignment


def alignment_to_json(alignment: AudioAlignment) -> str:
    return json.dumps(
        {
            "audio_id": alignment.audio_id,
            "duration_ms": alignment.duration_ms,
            "words": [
                {"token": word.text, "start_ms": word.start_ms, "end_ms": word.end_ms}
                for word in alignment.words
            ],
            "phrases": [
                {"phrase_id": phrase.phrase_id, "start_ms": phrase.start_ms, "end_ms": phrase.end_ms}
                for phrase in alignment.phrases
            ],
            "alignment_source": alignment.alignment_source,
            "is_estimated": alignment.is_estimated,
            "tts_provider": alignment.tts_provider,
        },
        ensure_ascii=False,
    )


def dialogue_end_ms(alignment: AudioAlignment) -> int:
    """Dialogue End Event = last word end, not total audio duration."""
    return alignment.words[-1].end_ms if alignment.words else alignment.duration_ms


def write_alignment_sidecar(audio_path: Path, alignment: AudioAlignment) -> Path:
    """Write ``<audio>.alignment.json``; a sidecar I/O issue doesn't block audio."""
    sidecar = audio_path.with_suffix(audio_path.suffix + ".alignment.json")
    try:
        sidecar.write_text(alignment_to_json(alignment) + "\n", encoding="utf-8")
    except OSError:
        return sidecar
    return sidecar


def load_alignment_sidecar(audio_path: Path) -> AudioAlignment | None:
    sidecar = audio_path.with_suffix(audio_path.suffix + ".alignment.json")
    if not sidecar.is_file():
        return None
    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    words = tuple(
        WordTiming(str(word["token"]), int(word["start_ms"]), int(word["end_ms"]))
        for word in payload.get("words", [])
    )
    phrases = tuple(
        PhraseTiming(str(phrase["phrase_id"]), int(phrase["start_ms"]), int(phrase["end_ms"]))
        for phrase in payload.get("phrases", [])
    )
    return AudioAlignment(
        str(payload.get("audio_id", "")),
        int(payload.get("duration_ms", 0)),
        words,
        phrases,
        alignment_source=str(payload.get("alignment_source", "edge_tts_word_boundary")),
        is_estimated=bool(payload.get("is_estimated", False)),
        tts_provider=str(payload.get("tts_provider", "edge_tts")),
    )
