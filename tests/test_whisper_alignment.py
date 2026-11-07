"""Offline contract tests for the local faster-whisper alignment provider.

No model is loaded: the ASR word stream is faked and only the
sequence-matching / data-structure contract is exercised.
"""

import wave
from pathlib import Path

import pytest

from hevi.audio import tts_alignment, whisper_alignment
from hevi.audio.tts_alignment import AlignmentUnavailable, WordTiming


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


def test_match_projects_asr_times_onto_text_chars_and_punctuation() -> None:
    asr_words = [
        ("小雨", 0.10, 0.30),
        ("在", 0.30, 0.42),
        ("雨夜", 0.42, 0.70),
        ("中行", 0.70, 0.96),
        ("。", 0.96, 1.00),
    ]
    words = whisper_alignment.match_asr_words_to_text(asr_words, "小雨在雨夜中行。")
    assert words[0] == WordTiming("小", 100, 200)
    assert words[1] == WordTiming("雨", 200, 300)
    assert words[-1] == WordTiming("。", 960, 1000)
    assert "".join(word.text for word in words) == "小雨在雨夜中行。"
    assert all(word.end_ms > word.start_ms for word in words)
    starts = [word.start_ms for word in words]
    assert starts == sorted(starts)


def test_match_tolerates_asr_substitution_and_missing_char() -> None:
    # 家 is misrecognized as 加 (replace) and 了 is missing entirely; difflib
    # folds both into one replace block, so the ASR span is shared by 家/了.
    asr_words = [("小猫", 0.0, 0.4), ("回加", 0.4, 0.8)]
    words = whisper_alignment.match_asr_words_to_text(asr_words, "小猫回家了")
    assert [word.text for word in words] == ["小", "猫", "回", "家", "了"]
    assert words[3] == WordTiming("家", 600, 700)
    assert words[4] == WordTiming("了", 700, 800)
    assert all(word.end_ms > word.start_ms for word in words)


def test_match_groups_latin_words_and_drops_spaces() -> None:
    asr_words = [("hello", 0.0, 0.5), (" world", 0.6, 1.1)]
    words = whisper_alignment.match_asr_words_to_text(asr_words, "hello world")
    assert words == (WordTiming("hello", 0, 500), WordTiming("world", 600, 1100))


def test_match_rejects_empty_inputs() -> None:
    with pytest.raises(AlignmentUnavailable):
        whisper_alignment.match_asr_words_to_text([], "小猫回家了")
    with pytest.raises(AlignmentUnavailable):
        whisper_alignment.match_asr_words_to_text([("小猫", 0.0, 0.4)], "  ")


@pytest.mark.asyncio
async def test_whisper_align_words_returns_timings_with_no_cost(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    audio = tmp_path / "voice.wav"
    _write_wav(audio)

    def fake_transcribe(audio_path: Path, *, model=None, language="zh"):
        assert audio_path == audio
        return [("小雨", 0.10, 0.30), ("回家", 0.30, 0.62)]

    monkeypatch.setattr(whisper_alignment, "_transcribe_words", fake_transcribe)
    words, cost = await whisper_alignment.whisper_align_words(
        audio_path=audio, text="小雨回家"
    )
    assert cost is None
    assert words[0] == WordTiming("小", 100, 200)
    assert words[-1] == WordTiming("家", 460, 620)
    assert "".join(word.text for word in words) == "小雨回家"


@pytest.mark.asyncio
async def test_whisper_align_words_missing_audio_raises(tmp_path: Path) -> None:
    with pytest.raises(AlignmentUnavailable):
        await whisper_alignment.whisper_align_words(
            audio_path=tmp_path / "nope.wav", text="小雨回家"
        )


@pytest.mark.asyncio
async def test_synthesize_with_alignment_whisper_local_mode(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("HEVI_TTS_ALIGNMENT_PROVIDER", "whisper_local")
    audio = tmp_path / "voice.wav"

    async def fake_synthesis(*, text: str, voice: str, output_path: Path) -> str:
        _write_wav(output_path, seconds=3.0)
        return "lux_tts"

    async def fake_whisper_align(*, audio_path: Path, text: str):
        assert audio_path == audio
        return (WordTiming("小", 100, 200), WordTiming("雨", 200, 320)), None

    monkeypatch.setattr(tts_alignment, "_synthesize_lux_audio", fake_synthesis)
    monkeypatch.setattr(
        whisper_alignment, "whisper_align_words", fake_whisper_align
    )
    monkeypatch.setattr(tts_alignment, "probe_duration_ms", lambda _path: 3000)

    path, result = await tts_alignment.synthesize_with_alignment(
        text="小雨回家", voice="soffy", audio_id="story:cue1", output_path=audio
    )

    assert path == audio and audio.is_file()
    assert result.tts_provider == "lux_tts"
    assert result.alignment_source == "whisper_asr_local"
    assert result.is_estimated is False
    assert result.words == (WordTiming("小", 100, 200), WordTiming("雨", 200, 320))
