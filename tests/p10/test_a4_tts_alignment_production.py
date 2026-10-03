"""A4 production: TTS writes an alignment sidecar without changing the return contract."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from hevi.audio.edge_tts_custom import _alignment_from_result, synthesize_with_voice_control
from hevi.audio.tts_alignment import (
    AudioAlignment,
    WordTiming,
    dialogue_end_ms,
    load_alignment_sidecar,
    write_alignment_sidecar,
)

SIDECAR_SUFFIX = ".wav.alignment.json"


def test_a4_alignment_from_result_uses_last_word_end():
    result = {"audio_path": Path("/tmp/x.mp3"),
              "words": [{"text": "a", "start": 0.1, "end": 0.3},
                        {"text": "b", "start": 0.35, "end": 0.8}]}
    align = _alignment_from_result(result, 0)
    assert align is not None
    assert align.duration_ms == 800 == dialogue_end_ms(align)
    assert _alignment_from_result({"words": []}, 0) is None


def test_a4_sidecar_roundtrip(tmp_path):
    audio = tmp_path / "clip.wav"
    audio.write_bytes(b"x")
    align = AudioAlignment("clip", 900, (WordTiming("hi", 100, 400),),
                           tuple())
    path = write_alignment_sidecar(audio, align)
    assert path.name.endswith(SIDECAR_SUFFIX)
    back = load_alignment_sidecar(audio)
    assert back is not None and back.words[0].end_ms == 400
    assert load_alignment_sidecar(tmp_path / "none.wav") is None


async def test_a4_production_path_writes_sidecar(tmp_path):
    """Real edge-tts. Skips (not fails) when the endpoint is unreachable."""
    script = [
        SimpleNamespace(text="The black hole bends light.", unit_id="scene1.line001",
                        voice="en_female_standard"),
        SimpleNamespace(text="It was never a hole.", unit_id="scene1.line002",
                        voice="en_female_standard"),
    ]
    out = tmp_path / "voice.wav"
    try:
        result = await synthesize_with_voice_control(
            script=script, output_path=out, voice="en_female_standard")
    except Exception as exc:  # 网络/限流:记为不可评估,不伪造
        pytest.skip(f"edge-tts unreachable: {exc}")
    assert isinstance(result, Path) and result == out  # 契约不变
    align = load_alignment_sidecar(result)
    assert align is not None and align.words
    assert [w.start_ms for w in align.words] == sorted(w.start_ms for w in align.words)
    assert [p.phrase_id for p in align.phrases] == ["scene1.line001", "scene1.line002"]
    # 第二句的词必须晚于第一句末词:证明偏移是 film 级而非段内
    first = align.phrases[0].end_ms
    assert align.words[-1].start_ms >= first - 1