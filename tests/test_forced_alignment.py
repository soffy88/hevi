"""Offline contract tests for the ElevenLabs forced-alignment provider (via Monid)."""

import json
from pathlib import Path

import pytest

from hevi.audio import forced_alignment, tts_alignment
from hevi.audio import monid_client
from hevi.audio.tts_alignment import WordTiming


def _fake_words_payload() -> dict:
    return {
        "words": [
            {"text": "黑洞", "start": 0.24, "end": 0.61, "loss": 0.69},
            {"text": " ", "start": 0.61, "end": 0.66, "loss": 0.72},
            {"text": "形成", "start": 0.66, "end": 0.92, "loss": 0.71},
        ],
        "billed_seconds": 1,
    }


def _write_wav(path: Path) -> None:
    import math
    import struct
    import wave

    path.parent.mkdir(parents=True, exist_ok=True)
    rate = 48000
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(rate)
        samples = rate
        output.writeframes(
            b"".join(
                struct.pack("<h", int(1000 * math.sin(2 * math.pi * 440 * i / rate)))
                for i in range(samples)
            )
        )


@pytest.mark.asyncio
async def test_forced_align_words_drops_space_tokens_and_uses_ms(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    audio = tmp_path / "voice.wav"
    _write_wav(audio)
    seen: dict[str, object] = {}

    async def fake_sfs(path: Path, *, sfs_path: str, ttl: str = "1d") -> str:
        seen["sfs_path"] = sfs_path
        return "https://example.test/audio.wav"

    async def fake_run(provider: str, endpoint: str, **kwargs):
        seen.update(provider=provider, endpoint=endpoint, body=kwargs.get("body"))
        return _fake_words_payload(), 0.0012

    monkeypatch.setattr(monid_client, "sfs_upload_file", fake_sfs)
    monkeypatch.setattr(monid_client, "run_endpoint", fake_run)

    words, cost = await forced_alignment.forced_align_words(
        audio_path=audio, text="黑洞 形成"
    )
    assert cost == 0.0012
    assert seen["provider"] == "elevenlabs"
    assert seen["endpoint"] == "/v1/forced-alignment"
    body = seen["body"]
    assert body["audio_url"] == "https://example.test/audio.wav"
    assert body["text"] == "黑洞 形成"
    assert isinstance(words[0], WordTiming)
    assert [w.text for w in words] == ["黑洞", "形成"]
    assert words[0].start_ms == 240 and words[0].end_ms == 610
    assert words[1].start_ms == 660 and words[1].end_ms == 920


@pytest.mark.asyncio
async def test_forced_align_words_rejects_empty_transcript(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    audio = tmp_path / "voice.wav"
    _write_wav(audio)
    with pytest.raises(tts_alignment.AlignmentUnavailable):
        await forced_alignment.forced_align_words(audio_path=audio, text="   ")


@pytest.mark.asyncio
async def test_forced_align_words_rejects_oversize_audio(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    audio = tmp_path / "big.wav"
    audio.parent.mkdir(parents=True, exist_ok=True)
    with open(audio, "wb") as f:
        f.truncate(21 * 1024 * 1024)
    with pytest.raises(tts_alignment.AlignmentUnavailable):
        await forced_alignment.forced_align_words(audio_path=audio, text="hi")


@pytest.mark.asyncio
async def test_synthesize_with_alignment_forced_marks_measured(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("HEVI_TTS_ALIGNMENT_PROVIDER", "elevenlabs_forced")
    audio = tmp_path / "voice.wav"
    _write_wav(audio)

    async def fake_synthesis(*, text: str, voice: str, output_path: Path) -> str:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        _write_wav(output_path)
        return "lux_tts"

    async def fake_align(*, audio_path: Path, text: str, **kwargs):
        assert audio_path.is_file()
        return (WordTiming("黑洞", 240, 610),), 0.0012

    monkeypatch.setattr(tts_alignment, "_synthesize_lux_audio", fake_synthesis)
    monkeypatch.setattr(forced_alignment, "forced_align_words", fake_align)
    monkeypatch.setattr(tts_alignment, "probe_duration_ms", lambda _path: 1000)

    path, result = await tts_alignment.synthesize_with_alignment(
        text="黑洞", voice="soffy", audio_id="poc:cue1", output_path=audio
    )
    assert path == audio
    assert result.is_estimated is False
    assert result.alignment_source == "elevenlabs_forced_alignment"
    assert result.tts_provider == "lux_tts"
    assert [w.text for w in result.words] == ["黑洞"]
