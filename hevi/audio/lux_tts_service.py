"""HTTP client for the dedicated LuxTTS service used by Hevi narration/dialogue.

The model stays on the LuxTTS host. This module sends one sentence at a time to
``POST /tts`` and joins the returned 48 kHz mono WAV files with short silences.
Transient response files are kept under this worktree's ``.tmp`` directory.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import time
import uuid
import wave
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_TEMP_ROOT = _PROJECT_ROOT / ".tmp"
_DEFAULT_URL = "http://100.119.113.90:8795"
_ALLOWED_VOICES = {"auto", "soffy", "en_male"}
_SENTENCE_BOUNDARY = re.compile(r"(?<=[。！？!?…])\s*|(?<=\.)\s+(?=\S)|\r?\n+")


def _base_url() -> str:
    value = os.getenv("HEVI_LUXTTS_URL", _DEFAULT_URL).strip().rstrip("/")
    if not value.startswith(("http://", "https://")):
        raise ValueError("HEVI_LUXTTS_URL must be an http(s) URL")
    return value


def _get_health_payload() -> dict[str, Any]:
    response = httpx.get(
        f"{_base_url()}/health",
        timeout=httpx.Timeout(5.0, connect=3.0),
        trust_env=False,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        raise RuntimeError(f"LuxTTS health response is not ready: {payload!r}")
    return payload


def lux_tts_available() -> bool:
    """Return true only when the configured HTTP service reports healthy."""
    try:
        _get_health_payload()
        return True
    except Exception as exc:
        # Do not re-validate the URL while handling a URL-validation error. A bad
        # HEVI_LUXTTS_URL must be treated like an unavailable service so callers
        # can reliably take their configured fallback path.
        logger.warning("LuxTTS HTTP health unavailable: %s", exc)
        return False


def split_sentences(text: str) -> list[str]:
    """Split Chinese and English narration on sentence punctuation, preserving it."""
    source = text.strip()
    if not source:
        return []
    return [part.strip() for part in _SENTENCE_BOUNDARY.split(source) if part.strip()]


async def _post_sentence(
    sentence: str, *, voice: str, speed: float, steps: int
) -> tuple[bytes, dict[str, Any]]:
    """Make up to three serial HTTP attempts (initial request plus two retries)."""
    last_error: Exception | None = None
    payload = {"text": sentence, "voice": voice, "speed": speed, "steps": steps}
    for attempt in range(3):
        started = time.monotonic()
        try:
            # 120 s read timeout covers first-call model warm-up; never overlap requests.
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(120.0, connect=5.0, write=15.0, pool=5.0),
                trust_env=False,
            ) as client:
                response = await client.post(f"{_base_url()}/tts", json=payload)
            response.raise_for_status()
            content = response.content
            if len(content) < 44 or not content.startswith(b"RIFF") or b"WAVE" not in content[:16]:
                raise RuntimeError("LuxTTS /tts returned a non-WAV or empty response")
            headers = response.headers
            actual_voice = headers.get("X-Voice", "").strip().lower()
            expected_voice = voice
            if voice == "auto":
                expected_voice = (
                    "soffy"
                    if re.search(r"[\u4e00-\u9fff]", sentence)
                    else "en_male"
                )
            if actual_voice != expected_voice:
                raise RuntimeError(
                    "LuxTTS /tts returned unexpected X-Voice="
                    f"{actual_voice!r}; expected {expected_voice!r}"
                )
            elapsed = time.monotonic() - started
            meta = {
                "voice": actual_voice,
                "gen_seconds": _float_header(headers.get("X-Gen-Seconds"), elapsed),
                "api_audio_seconds": _float_header(headers.get("X-Audio-Seconds"), 0.0),
                "http_attempts": attempt + 1,
            }
            return content, meta
        except Exception as exc:
            last_error = exc
            logger.warning(
                "LuxTTS /tts failed (attempt %d/3): %s", attempt + 1, exc
            )
            if attempt < 2:
                await asyncio.sleep(0.25 * (attempt + 1))
    raise RuntimeError(f"LuxTTS /tts failed after 3 attempts: {last_error}") from last_error


def _float_header(value: str | None, default: float) -> float:
    try:
        parsed = float(value or "")
        return parsed if parsed >= 0 else default
    except (TypeError, ValueError):
        return default


def _normalise_wav(source: Path, temp_dir: Path, index: int, sample_rate: int) -> Path:
    """Normalise non-contract audio into mono, 16-bit PCM at the pipeline rate."""
    try:
        with wave.open(str(source), "rb") as wav:
            params = wav.getparams()
            if (
                params.nchannels == 1
                and params.sampwidth == 2
                and params.framerate == sample_rate
                and params.comptype == "NONE"
            ):
                return source
    except (wave.Error, EOFError):
        pass

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError(
            f"LuxTTS WAV does not match {sample_rate} Hz mono PCM and ffmpeg is unavailable"
        )
    target = temp_dir / f"sentence-{index:03d}-normalised.wav"
    result = subprocess.run(
        [ffmpeg, "-y", "-v", "error", "-i", str(source), "-ar", str(sample_rate),
         "-ac", "1", "-c:a", "pcm_s16le", str(target)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 or not target.is_file() or target.stat().st_size < 44:
        raise RuntimeError(f"ffmpeg could not normalise LuxTTS WAV: {result.stderr[-1000:]}")
    return target


async def synth_with_luxtts(
    text: str,
    output_path: Path,
    *,
    voice: str | None = None,
    speed: float = 1.0,
    steps: int = 4,
    sample_rate: int = 48000,
    gap_ms: int = 150,
    metadata_path: Path | None = None,
) -> Path:
    """Synthesize text through LuxTTS HTTP, joining sentence WAVs with 150 ms gaps.

    ``voice=auto`` delegates Chinese/English voice selection to the service. A
    caller may supply ``metadata_path`` to persist per-sentence voice and timing.
    """
    sentences = split_sentences(text)
    if not sentences:
        raise ValueError("LuxTTS synthesis text must not be empty")
    if sample_rate <= 0 or gap_ms < 0 or steps <= 0 or speed <= 0:
        raise ValueError("sample_rate/steps/speed must be positive and gap_ms non-negative")
    selected_voice = (voice or os.getenv("HEVI_LUXTTS_VOICE", "auto")).strip().lower()
    if selected_voice not in _ALLOWED_VOICES:
        raise ValueError(f"Unsupported LuxTTS voice {selected_voice!r}; use auto, soffy or en_male")

    # Fail early before creating a partial artifact. Calls remain strictly serial.
    health = await asyncio.to_thread(_get_health_payload)
    service_voices = {
        str(item).strip().lower()
        for item in health.get("voices", [])
        if isinstance(item, str) and item.strip()
    }
    required_voices = {"soffy", "en_male"} if selected_voice == "auto" else {selected_voice}
    missing_voices = required_voices - service_voices
    if missing_voices:
        raise RuntimeError(
            "LuxTTS service is missing required voice(s): "
            f"{sorted(missing_voices)}; reported voices: {sorted(service_voices)}"
        )

    _TEMP_ROOT.mkdir(parents=True, exist_ok=True)
    temp_dir = _TEMP_ROOT / f"lux_tts_{uuid.uuid4().hex}"
    temp_dir.mkdir(parents=True, exist_ok=False)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    sentence_rows: list[dict[str, Any]] = []
    normalised_paths: list[Path] = []
    cursor = 0.0
    total_generation = 0.0
    for index, sentence in enumerate(sentences, start=1):
        audio_bytes, server_meta = await _post_sentence(
            sentence, voice=selected_voice, speed=float(speed), steps=int(steps)
        )
        raw_path = temp_dir / f"sentence-{index:03d}.wav"
        raw_path.write_bytes(audio_bytes)
        normalised = _normalise_wav(raw_path, temp_dir, index, sample_rate)
        normalised_paths.append(normalised)
        with wave.open(str(normalised), "rb") as wav:
            frame_count = wav.getnframes()
        duration = frame_count / sample_rate
        sentence_rows.append({
            "index": index,
            "text": sentence,
            "voice_requested": selected_voice,
            "voice": server_meta["voice"],
            "duration_seconds": round(duration, 4),
            "api_audio_seconds": round(float(server_meta["api_audio_seconds"] or duration), 4),
            "gen_seconds": round(float(server_meta["gen_seconds"]), 4),
            "http_attempts": server_meta["http_attempts"],
            "start_seconds": round(cursor, 4),
            "temp_wav": str(normalised),
        })
        cursor += duration
        total_generation += float(server_meta["gen_seconds"])
        if index < len(sentences):
            cursor += gap_ms / 1000.0

    silence = b"\x00\x00" * round(sample_rate * gap_ms / 1000.0)
    with wave.open(str(output_path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        for index, wav_path in enumerate(normalised_paths):
            with wave.open(str(wav_path), "rb") as source:
                if (source.getnchannels(), source.getsampwidth(), source.getframerate()) != (1, 2, sample_rate):
                    raise RuntimeError(f"Normalised LuxTTS audio has unexpected WAV parameters: {wav_path}")
                output.writeframes(source.readframes(source.getnframes()))
            if index < len(normalised_paths) - 1:
                output.writeframes(silence)

    actual_duration = cursor
    metadata = {
        "provider": "luxtts_http",
        "endpoint": f"{_base_url()}/tts",
        "voice_requested": selected_voice,
        "sample_rate": sample_rate,
        "channels": 1,
        "sample_width_bytes": 2,
        "sentence_gap_ms": gap_ms,
        "sentence_count": len(sentence_rows),
        "duration_seconds": round(actual_duration, 4),
        "total_gen_seconds": round(total_generation, 4),
        "output_path": str(output_path),
        "sentences": sentence_rows,
    }
    if metadata_path is not None:
        metadata_path = Path(metadata_path)
        metadata_path.parent.mkdir(parents=True, exist_ok=True)
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output_path


async def synth_with_luxvoice(
    text: str,
    output_path: Path,
    *,
    reference_audio: str | Path | None = None,
    speed: float = 1.0,
    **kwargs: Any,
) -> Path:
    """Backward-compatible alias; the HTTP service chooses the configured voice.

    The remote contract does not accept per-request reference audio. Its ``auto``
    voice uses the already-configured service voices (Chinese=soffy, English=en_male).
    """
    if reference_audio:
        logger.info("LuxTTS HTTP uses its configured named voice; per-request reference_audio is ignored")
    return await synth_with_luxtts(text, output_path, speed=speed, **kwargs)


__all__ = ["lux_tts_available", "split_sentences", "synth_with_luxtts", "synth_with_luxvoice"]
