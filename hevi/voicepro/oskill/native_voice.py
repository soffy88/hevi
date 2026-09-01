"""HEVI-native low-resource voice skill.

The skill composes the public voice atoms into a local, model-independent
runtime.  It uses the operating system speech synthesizer as the final vocal
renderer, while HEVI owns conditioning, reference analysis, chunking, batch
execution and stream semantics.  This keeps the capability usable without
installing Pocket TTS or VoxCPM.
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import tempfile
import wave
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hevi.voicepro.oprim import (
    VoiceConditioning,
    normalize_voice_text,
    probe_reference_audio,
    resolve_voice_conditioning,
    split_voice_text,
)


@dataclass(frozen=True)
class NativeVoiceResult:
    path: Path
    duration_s: float
    sample_rate: int
    conditioning: VoiceConditioning
    backend: str = "hevi-native"

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "duration_s": round(self.duration_s, 3),
            "sample_rate": self.sample_rate,
            "backend": self.backend,
            "conditioning": {
                "language": self.conditioning.language,
                "voice": self.conditioning.voice,
                "speed_wpm": self.conditioning.speed_wpm,
                "pitch": self.conditioning.pitch,
                "reference_features": self.conditioning.reference_features or {},
            },
        }


@dataclass(frozen=True)
class NativeAudioChunk:
    index: int
    pcm_s16le: bytes
    sample_rate: int
    final: bool


def native_voice_available() -> bool:
    """Return whether HEVI's local speech runtime is executable."""

    return bool(shutil.which("espeak-ng") or shutil.which("espeak"))


def _renderer() -> str:
    executable = shutil.which("espeak-ng") or shutil.which("espeak")
    if not executable:
        raise RuntimeError(
            "HEVI native voice runtime unavailable; provide espeak-ng/espeak on PATH"
        )
    return executable


def _read_wav_info(path: Path) -> tuple[int, int, bytes]:
    try:
        with wave.open(str(path), "rb") as stream:
            rate = stream.getframerate()
            frames = stream.getnframes()
            channels = stream.getnchannels()
            width = stream.getsampwidth()
            payload = stream.readframes(frames)
    except (wave.Error, EOFError) as exc:
        raise RuntimeError(f"HEVI native renderer returned invalid WAV: {path}") from exc
    if not payload or rate <= 0 or channels <= 0 or width != 2:
        raise RuntimeError("HEVI native renderer returned empty or unsupported audio")
    if channels != 1:
        raise RuntimeError("HEVI native renderer returned non-mono audio")
    return rate, frames, payload


def synthesize_native_voice_sync(
    text: str,
    output_path: str | Path,
    *,
    voice: str = "",
    language: str = "",
    reference_audio: str | Path | None = None,
    voice_design: str = "",
    speed: float = 1.0,
) -> NativeVoiceResult:
    """Render one local utterance and return verified audio metadata."""

    normalized = normalize_voice_text(text)
    if not normalized:
        raise ValueError("native voice text cannot be empty")
    reference_features = (
        probe_reference_audio(reference_audio) if reference_audio else None
    )
    conditioning = resolve_voice_conditioning(
        voice=voice,
        language=language,
        voice_design=voice_design,
        reference_features=reference_features,
        speed=speed,
    )
    destination = Path(output_path).expanduser()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="hevi_native_voice_") as temp_dir:
        rendered = Path(temp_dir) / "rendered.wav"
        command = [
            _renderer(),
            "-v",
            conditioning.language,
            "-s",
            str(conditioning.speed_wpm),
            "-p",
            str(conditioning.pitch),
            "-a",
            str(conditioning.amplitude),
            "-w",
            str(rendered),
            normalized,
        ]
        completed = subprocess.run(
            command,
            capture_output=True,
            check=False,
            timeout=90,
        )
        if completed.returncode != 0:
            detail = completed.stderr.decode(errors="replace").strip()[:400]
            raise RuntimeError(f"HEVI native voice renderer failed: {detail}")
        rate, frames, _ = _read_wav_info(rendered)
        shutil.copyfile(rendered, destination)
    if not destination.is_file() or destination.stat().st_size == 0:
        raise RuntimeError("HEVI native voice renderer produced no artifact")
    return NativeVoiceResult(
        path=destination,
        duration_s=frames / rate,
        sample_rate=rate,
        conditioning=conditioning,
    )


async def synthesize_native_voice(
    text: str,
    output_path: str | Path,
    *,
    voice: str = "",
    language: str = "",
    reference_audio: str | Path | None = None,
    voice_design: str = "",
    speed: float = 1.0,
) -> NativeVoiceResult:
    """Async boundary for local native synthesis."""

    return await asyncio.to_thread(
        synthesize_native_voice_sync,
        text,
        output_path,
        voice=voice,
        language=language,
        reference_audio=reference_audio,
        voice_design=voice_design,
        speed=speed,
    )


async def stream_native_voice(
    text: str,
    *,
    voice: str = "",
    language: str = "",
    reference_audio: str | Path | None = None,
    voice_design: str = "",
    speed: float = 1.0,
    chunk_chars: int = 180,
) -> AsyncIterator[NativeAudioChunk]:
    """Yield verified PCM chunks as each sentence-sized utterance completes."""

    chunks = split_voice_text(text, max_chars=chunk_chars)
    if not chunks:
        raise ValueError("native voice text cannot be empty")
    with tempfile.TemporaryDirectory(prefix="hevi_native_stream_") as temp_dir:
        for index, chunk in enumerate(chunks):
            result = await synthesize_native_voice(
                chunk,
                Path(temp_dir) / f"chunk-{index:04d}.wav",
                voice=voice,
                language=language,
                reference_audio=reference_audio,
                voice_design=voice_design,
                speed=speed,
            )
            rate, _, pcm = _read_wav_info(result.path)
            yield NativeAudioChunk(
                index=index,
                pcm_s16le=pcm,
                sample_rate=rate,
                final=index == len(chunks) - 1,
            )


async def synthesize_native_batch(
    texts: list[str],
    output_dir: str | Path,
    *,
    voice: str = "",
    language: str = "",
    reference_audio: str | Path | None = None,
    voice_design: str = "",
    speed: float = 1.0,
) -> list[NativeVoiceResult]:
    """Synthesize a deterministic ordered batch for dubbing/audiobook jobs."""

    root = Path(output_dir).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    results: list[NativeVoiceResult] = []
    for index, text in enumerate(texts):
        results.append(
            await synthesize_native_voice(
                text,
                root / f"native-{index:04d}.wav",
                voice=voice,
                language=language,
                reference_audio=reference_audio,
                voice_design=voice_design,
                speed=speed,
            )
        )
    return results


__all__ = [
    "NativeAudioChunk",
    "NativeVoiceResult",
    "native_voice_available",
    "stream_native_voice",
    "synthesize_native_batch",
    "synthesize_native_voice",
    "synthesize_native_voice_sync",
]
