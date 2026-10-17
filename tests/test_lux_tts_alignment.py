"""Offline contract tests for the LuxTTS-first alignment wrapper."""

import wave
from pathlib import Path

import pytest

from hevi.audio import tts_alignment
from hevi.audio.tts_alignment import WordTiming


def _write_wav(path: Path, seconds: float = 1.0) -> None:
    import math
    import struct

    path.parent.mkdir(parents=True, exist_ok=True)
    rate = 48000
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(rate)
        samples = int(rate * seconds)
        output.writeframes(
            b"".join(
                struct.pack("<h", int(1000 * math.sin(2 * math.pi * 440 * i / rate)))
                for i in range(samples)
            )
        )


@pytest.mark.asyncio
async def test_lux_tts_alignment_defaults_to_shared_lux_router_and_marks_estimates(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("HEVI_TTS_ALIGNMENT_PROVIDER", raising=False)
    seen: dict[str, object] = {}
    audio = tmp_path / "voice.wav"

    async def fake_synthesis(*, text: str, voice: str, output_path: Path) -> str:
        seen.update(text=text, voice=voice, output_path=output_path)
        _write_wav(output_path, seconds=3.0)
        return "lux_tts"

    monkeypatch.setattr(tts_alignment, "_synthesize_lux_audio", fake_synthesis)
    monkeypatch.setattr(tts_alignment, "probe_duration_ms", lambda _path: 3000)

    path, result = await tts_alignment.synthesize_with_alignment(
        text="小兔子你好呀。", voice="soffy", audio_id="kids:cue1", output_path=audio
    )

    assert path == audio and audio.is_file()
    assert seen["text"] == "小兔子你好呀。"
    assert seen["voice"] == "soffy"
    assert result.tts_provider == "lux_tts"
    assert result.alignment_source == "lux_tts_duration_weighted_estimate"
    assert result.is_estimated is True
    assert result.duration_ms == 3000
    assert result.words and all(word.end_ms <= result.duration_ms for word in result.words)


@pytest.mark.asyncio
async def test_lux_alignment_records_actual_fallback_provider(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("HEVI_TTS_ALIGNMENT_PROVIDER", raising=False)

    async def fake_fallback(*, text: str, voice: str, output_path: Path) -> str:
        _write_wav(output_path, seconds=2.0)
        return "piper"

    monkeypatch.setattr(tts_alignment, "_synthesize_lux_audio", fake_fallback)
    monkeypatch.setattr(tts_alignment, "probe_duration_ms", lambda _path: 2000)
    _, result = await tts_alignment.synthesize_with_alignment(
        text="Hello little bunny.", voice="auto", output_path=tmp_path / "fallback.wav"
    )

    assert result.tts_provider == "piper"
    assert result.alignment_source == "piper_duration_weighted_estimate"
    assert result.is_estimated is True


@pytest.mark.asyncio
async def test_explicit_edge_alignment_preserves_native_boundary_identity(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("HEVI_TTS_ALIGNMENT_PROVIDER", "edge_tts")
    audio = tmp_path / "edge.wav"
    _write_wav(audio, seconds=1.0)

    async def fake_edge(*, text: str, voice: str, output_path: Path | None):
        return audio, (WordTiming("hello", 120, 430),), "edge_tts_word_boundary"

    monkeypatch.setattr(tts_alignment, "_synthesize_edge_with_word_boundaries", fake_edge)
    monkeypatch.setattr(tts_alignment, "probe_duration_ms", lambda _path: 1000)
    _, result = await tts_alignment.synthesize_with_alignment(
        text="hello", voice="en-US-AriaNeural", output_path=audio
    )

    assert result.tts_provider == "edge_tts"
    assert result.alignment_source == "edge_tts_word_boundary"
    assert result.is_estimated is False
    assert result.words == (WordTiming("hello", 120, 430),)


@pytest.mark.asyncio
async def test_alignment_lux_mode_uses_lux_first_route_even_if_formal_style_is_overridden(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from hevi.audio import audio_router

    monkeypatch.setenv("HEVI_TTS_FORMAL_PROVIDER", "voicebox")
    audio = tmp_path / "router.wav"
    seen: dict[str, object] = {}

    async def fake_lux_router(**kwargs: object) -> dict[str, object]:
        seen.update(kwargs)
        _write_wav(audio, seconds=1.5)
        return {
            "path": audio,
            "requested_provider": "lux_tts",
            "actual_provider": "lux_tts",
            "substituted": False,
        }

    monkeypatch.setattr(audio_router, "_synthesize_luxtts_with_fallback", fake_lux_router)
    actual = await tts_alignment._synthesize_lux_audio(
        text="小兔子你好呀。", voice="soffy", output_path=audio
    )

    assert actual == "lux_tts"
    assert seen["requested_provider"] == "lux_tts"
    assert seen["remote_voice"] == "soffy"
    assert seen["text"] == "小兔子你好呀。"
