"""G0.2-B TTS alignment artifacts: coverage, duration, revision isolation."""

import pytest

from hevi.audio.tts_alignment import (
    AlignmentUnavailable,
    alignment_to_json,
    synthesize_with_alignment,
)

VOICE = "en-US-AriaNeural"

# ~100 words body (SPEC T1 requires at least 95% coverage).
TEXT_100 = (
    "The black hole bends light and time around it. Matter falls inward past the point "
    "of no return where gravity wins every contest. From far away we watch the disk glow "
    "as gas heats to millions of degrees. Time itself slows near the edge and clocks tick "
    "at different rates for different watchers. Nothing escapes once the horizon is crossed, "
    "not even light. Yet the shadow it casts can be seen across the dark. A ring of fire "
    "marks the boundary between known and unknown. This is where our story begins tonight."
)


@pytest.mark.asyncio
async def test_t1_word_coverage(tmp_path):
    audio_path, alignment = await synthesize_with_alignment(
        text=TEXT_100, voice=VOICE, audio_id="tts:spike100", output_path=tmp_path / "spike100.mp3"
    )
    assert audio_path.exists() and audio_path.stat().st_size > 0
    expected = len(TEXT_100.split())
    coverage = len(alignment.words) / expected
    assert coverage >= 0.95, f"coverage {coverage:.2f} < 0.95"
    assert all(isinstance(w.start_ms, int) and isinstance(w.end_ms, int) for w in alignment.words)
    assert all(w.end_ms > w.start_ms for w in alignment.words)
    assert [w.start_ms for w in alignment.words] == sorted(w.start_ms for w in alignment.words)
    payload = alignment_to_json(alignment)
    assert '"token": "black"' in payload or '"token":"black"' in payload or "black" in payload
    # LuxTTS doesn't return native word timings; estimates must never be represented as forced alignment.
    assert alignment.is_estimated is True
    assert alignment.alignment_source == f"{alignment.tts_provider}_duration_weighted_estimate"
    assert '"is_estimated": true' in payload
    assert alignment.tts_provider in {"lux_tts", "cosyvoice", "piper"}


@pytest.mark.asyncio
async def test_t2_duration_match(tmp_path):
    # Audio may contain trailing silence; it must not be truncated and it must be bounded.
    _, alignment = await synthesize_with_alignment(
        text="The black hole bends light.", voice=VOICE,
        audio_id="tts:spike-short", output_path=tmp_path / "short.mp3",
    )
    assert alignment.words, "expected word timings, got none"
    gap = alignment.duration_ms - alignment.words[-1].end_ms
    assert gap >= 0, "audio truncated speech"
    assert gap <= 2000, f"trailing silence {gap}ms exceeds bound"


@pytest.mark.asyncio
async def test_t3_revision_mapping_no_cross_pollution(tmp_path):
    _, old = await synthesize_with_alignment(
        text="The black hole bends light.", voice=VOICE,
        audio_id="tts:scene1.line001#r1", output_path=tmp_path / "r1.mp3",
    )
    _, new = await synthesize_with_alignment(
        text="The black hole bends spacetime.", voice=VOICE,
        audio_id="tts:scene1.line001#r2", output_path=tmp_path / "r2.mp3",
    )
    assert old.audio_id != new.audio_id
    assert [w.text for w in old.words] != [w.text for w in new.words]


@pytest.mark.asyncio
async def test_reverse_empty_text_is_fail_loud():
    with pytest.raises(AlignmentUnavailable):
        await synthesize_with_alignment(text="   ", voice=VOICE, audio_id="tts:empty")
