"""OpenAI-compatible audio façade for the local speech platform."""

from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from hevi.audio.speech_platform import get_engine
from hevi.ingest.video_transcript import TranscriptError, fetch_transcript
from hevi.production.artifacts import Artifact, ArtifactManifest

AUDIO_FORMATS = {
    "wav": ("audio/wav", ".wav"),
    "mp3": ("audio/mpeg", ".mp3"),
    "opus": ("audio/ogg", ".opus"),
    "aac": ("audio/aac", ".aac"),
    "flac": ("audio/flac", ".flac"),
    "pcm": ("audio/pcm", ".pcm"),
}


def _validate_tts_engine(engine_id: str) -> None:
    engine = get_engine(engine_id)
    if engine is None or engine.kind != "tts":
        raise ValueError(f"unknown TTS engine: {engine_id}")
    if not engine.available:
        raise RuntimeError(f"TTS engine unavailable: {engine_id}; setup={engine.setup or 'n/a'}")


async def synthesize_audio_file(
    *,
    text: str,
    engine: str,
    voice: str = "",
    language: str = "",
    response_format: str = "wav",
    speed: float = 1.0,
    instructions: str = "",
    reference_audio: str = "",
    reference_text: str = "",
    voice_design: str = "",
    output_dir: str | Path = "output/voice-platform",
) -> dict[str, Any]:
    """Run an existing HEVI provider and return an auditable local artifact."""

    if not text.strip():
        raise ValueError("input text cannot be empty")
    fmt = response_format.lower().strip()
    if fmt not in AUDIO_FORMATS:
        raise ValueError(f"unsupported response_format: {response_format}")
    _validate_tts_engine(engine)

    from hevi.audio.task_adapter import _synthesize_with_engine

    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    wav_path = root / f"speech-{uuid.uuid4().hex}.wav"
    line = SimpleNamespace(text=text, voice=voice or None, emotion=instructions or None)
    config = {
        "engine": engine,
        "voice": voice,
        "language": language or "zh",
        "speed": speed,
        "instruct": instructions,
        "reference_audio": reference_audio,
        "reference_text": reference_text,
        "voice_design": voice_design,
    }
    await _synthesize_with_engine(
        engine,
        line=line,
        output_path=wav_path,
        config=config,
        emotion=instructions or None,
    )
    if not wav_path.is_file() or wav_path.stat().st_size == 0:
        raise RuntimeError("TTS provider returned no local audio artifact")

    output_path = wav_path
    if fmt != "wav":
        output_path = root / f"{wav_path.stem}.{AUDIO_FORMATS[fmt][1].lstrip('.') }"
        await _convert_audio(wav_path, output_path, fmt)
    artifact = Artifact.from_path(
        output_path,
        kind="audio",
        media_type=AUDIO_FORMATS[fmt][0],
        primary=True,
        logical_role="speech",
        metadata={"engine": engine, "voice": voice, "language": language or "zh"},
    )
    manifest = ArtifactManifest(artifacts=[artifact])
    return {
        "path": str(output_path),
        "media_type": AUDIO_FORMATS[fmt][0],
        "format": fmt,
        "engine": engine,
        "voice": voice,
        "manifest": manifest.model_dump(mode="json"),
    }


async def _convert_audio(source: Path, output: Path, fmt: str) -> None:
    from obase.ffmpeg import run as ffmpeg_run

    args = ["-y", "-i", str(source)]
    if fmt == "pcm":
        args.extend(["-f", "s16le", "-acodec", "pcm_s16le"])
    args.append(str(output))
    await ffmpeg_run(args=args, expected_output=output)


def transcribe_audio_file(
    *,
    source: str | Path,
    language: str | None = None,
    response_format: str = "verbose_json",
    asr_engine: str = "faster_whisper",
) -> dict[str, Any]:
    """Normalize HEVI's local ASR segments to OpenAI-compatible shapes."""

    engine = get_engine(asr_engine)
    if engine is None or engine.kind != "asr":
        raise ValueError(f"unknown ASR engine: {asr_engine}")
    if not engine.available:
        raise RuntimeError(f"ASR engine unavailable: {asr_engine}; setup={engine.setup or 'n/a'}")
    try:
        segments = fetch_transcript(source, whisper_fallback=True, language=language)
    except TranscriptError:
        raise
    text = " ".join(item.text for item in segments).strip()
    normalized = [
        {
            "id": index,
            "start": item.start,
            "end": item.end,
            "text": item.text,
            "speaker": item.speaker or None,
            "words": [
                {"word": word.word, "start": word.start, "end": word.end}
                for word in item.words
            ],
        }
        for index, item in enumerate(segments)
    ]
    if response_format in {"text", "json"}:
        return {"text": text, "format": "text"}
    if response_format == "srt":
        return {"text": _to_srt(segments), "format": "srt"}
    if response_format == "vtt":
        return {"text": _to_vtt(segments), "format": "vtt"}
    return {
        "text": text,
        "language": language or "auto",
        "segments": normalized,
        "format": "verbose_json",
    }


def _clock(seconds: float, *, comma: bool = False) -> str:
    total_ms = max(0, round(seconds * 1000))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    separator = "," if comma else "."
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{separator}{millis:03d}"


def _to_srt(segments: list[Any]) -> str:
    return "\n\n".join(
        f"{index}\n{_clock(seg.start, comma=True)} --> {_clock(seg.end, comma=True)}\n{seg.text}"
        for index, seg in enumerate(segments, start=1)
    )


def _to_vtt(segments: list[Any]) -> str:
    body = "\n\n".join(
        f"{_clock(seg.start)} --> {_clock(seg.end)}\n{seg.text}" for seg in segments
    )
    return f"WEBVTT\n\n{body}" if body else "WEBVTT\n"


__all__ = [
    "AUDIO_FORMATS",
    "synthesize_audio_file",
    "transcribe_audio_file",
]
