"""Regression tests for page clocks after independent caption alignment."""

import pytest

from hevi.layer4_legacy.handdraw.scripts.independent_caption_alignment import (
    _reconcile_page_boundaries,
)


def test_independent_caption_retime_moves_page_cut_to_real_speech_gap() -> None:
    timeline = {
        "pages": [
            {
                "start": 1.0,
                "end": 15.0,
                "speech_start": 1.0,
                "speech_end": 14.8,
                "last_drawing_end": 13.7,
                "events": [
                    {"caption": True, "start": 12.0, "end": 14.5, "hide": 14.5},
                    {"start": 13.0, "end": 14.8, "hide": 14.8},
                ],
            },
            {
                "start": 15.0,
                "end": 29.0,
                "speech_start": 15.0,
                "speech_end": 28.8,
                "last_drawing_end": 28.0,
                "events": [
                    {"caption": True, "start": 14.7, "end": 17.2, "hide": 17.2},
                    {"start": 15.0, "end": 18.0, "hide": 18.0},
                ],
            },
            {
                "start": 29.0,
                "end": 44.0,
                "speech_start": 29.0,
                "speech_end": 43.8,
                "last_drawing_end": 42.9,
                "events": [
                    {"caption": True, "start": 28.0, "end": 31.0, "hide": 31.0},
                    {"start": 29.0, "end": 32.0, "hide": 32.0},
                ],
            },
        ],
    }

    report = _reconcile_page_boundaries(timeline)

    assert timeline["pages"][0]["end"] == 14.6
    assert timeline["pages"][1]["start"] == 14.6
    assert timeline["pages"][1]["end"] == 22.6
    assert timeline["pages"][2]["start"] == 22.6
    # Caption timestamps remain anchored to audio; artwork events move with page.
    assert timeline["pages"][1]["events"][0]["start"] == 14.7
    assert timeline["pages"][1]["events"][1]["start"] == 14.6
    assert timeline["pages"][1]["speech_end"] == 17.2
    # The drawing clock is compressed so the last stroke still finishes 0.45s
    # before the measured end of speech (17.2 - 0.45 = 16.75).
    assert timeline["pages"][1]["last_drawing_end"] == 16.75
    assert timeline["pages"][1]["last_drawing_end"] == pytest.approx(17.2 - 0.45)
    assert len(report) == 3
    for page in timeline["pages"]:
        for event in page["events"]:
            if event.get("caption"):
                assert page["start"] <= event["start"] < event["hide"] <= page["end"]


def test_caption_word_start_moves_out_of_leading_silence(tmp_path) -> None:
    import array
    import wave

    from hevi.layer4_legacy.handdraw.scripts.independent_caption_alignment import (
        _adjust_word_starts_for_silence,
    )

    audio = tmp_path / 'silence-then-speech.wav'
    rate = 16_000
    samples = array.array('h', [0] * int(rate * 0.30))
    samples.extend([5000] * int(rate * 0.50))
    with wave.open(str(audio), 'wb') as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(rate)
        target.writeframes(samples.tobytes())
    words = [{'text': '小朋友', 'start': 0.0, 'end': 0.6}]

    adjusted = _adjust_word_starts_for_silence(words, audio)

    assert adjusted == 1
    assert words[0]['start'] == 0.30
    assert words[0]['end'] == 0.6


def test_independent_audit_uses_mp4_audio_to_remove_silent_onset(tmp_path, monkeypatch) -> None:
    import array
    from pathlib import Path
    from subprocess import CompletedProcess
    from unittest.mock import patch

    from audit.handdraw.verify_r4.independent_asr_audit import (
        adjust_words_for_audio_silence,
    )

    samples = array.array('h', [0] * int(16_000 * 0.30))
    samples.extend([5000] * int(16_000 * 0.50))
    video = Path(tmp_path / 'fixture.mp4')
    words = [{'text': '小', 'start': 0.0, 'end': 0.6}]
    result = CompletedProcess(args=['ffmpeg'], returncode=0, stdout=samples.tobytes(), stderr=b'')
    with patch('audit.handdraw.verify_r4.independent_asr_audit.subprocess.run', return_value=result):
        adjusted = adjust_words_for_audio_silence(words, video)

    assert adjusted == 1
    assert words[0]['start'] == 0.30


def test_word_timestamp_spanning_internal_silence_uses_last_audible_cluster(tmp_path) -> None:
    import array
    import wave

    from hevi.layer4_legacy.handdraw.scripts.independent_caption_alignment import (
        _adjust_word_starts_for_silence,
    )

    audio = tmp_path / 'word-with-internal-pause.wav'
    rate = 16_000
    samples = array.array('h', [0] * int(rate * 0.30))
    samples.extend([5000] * int(rate * 0.25))
    samples.extend([0] * int(rate * 0.35))
    samples.extend([5000] * int(rate * 0.20))
    with wave.open(str(audio), 'wb') as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(rate)
        target.writeframes(samples.tobytes())
    words = [{'text': '请', 'start': 0.30, 'end': 1.10}]

    adjusted = _adjust_word_starts_for_silence(words, audio)

    assert adjusted == 1
    assert words[0]['start'] == 0.90


def test_independent_audit_corrects_word_span_with_internal_silence(tmp_path) -> None:
    import array
    from pathlib import Path
    from subprocess import CompletedProcess
    from unittest.mock import patch

    from audit.handdraw.verify_r4.independent_asr_audit import (
        adjust_words_for_audio_silence,
    )

    samples = array.array('h', [0] * int(16_000 * 0.30))
    samples.extend([5000] * int(16_000 * 0.25))
    samples.extend([0] * int(16_000 * 0.35))
    samples.extend([5000] * int(16_000 * 0.20))
    video = Path(tmp_path / 'fixture-internal-pause.mp4')
    words = [{'text': '请', 'start': 0.30, 'end': 1.10}]
    result = CompletedProcess(args=['ffmpeg'], returncode=0, stdout=samples.tobytes(), stderr=b'')
    with patch('audit.handdraw.verify_r4.independent_asr_audit.subprocess.run', return_value=result):
        adjusted = adjust_words_for_audio_silence(words, video)

    assert adjusted == 1
    assert words[0]['start'] == 0.90


def test_final_caption_reading_hold_is_clamped_to_media_end() -> None:
    """R5 regression: a late ASR onset must not push the last cue past the film.

    The final interaction cue keeps its original beat span even when independent
    word timestamps move its onset later. Without the clamp the reading hold ran
    past the end of the narration and the subtitle contract rejected the page.
    """
    from hevi.layer4_legacy.handdraw.scripts.independent_caption_alignment import (
        _clamp_final_cue_hold,
    )

    planned = [
        {"start": 1.0, "end": 3.2},
        {"start": 3.4, "end": 7.7},
        # Independent ASR moved the final onset to 63.38s but the original beat
        # span kept a 2.662s hold, so it ended at 66.042s in a 65.913s film.
        {"start": 63.38, "end": 66.042},
    ]

    removed = _clamp_final_cue_hold(planned, media_end=65.913)

    assert removed == round(66.042 - 65.913, 6)
    assert planned[-1]["start"] == 63.38
    assert planned[-1]["end"] == 65.913
    assert planned[-1]["start"] + 0.20 < planned[-1]["end"]


def test_final_cue_hold_inside_media_is_left_untouched() -> None:
    from hevi.layer4_legacy.handdraw.scripts.independent_caption_alignment import (
        _clamp_final_cue_hold,
    )

    planned = [
        {"start": 1.0, "end": 3.2},
        {"start": 53.10, "end": 57.715},
    ]

    assert _clamp_final_cue_hold(planned, media_end=57.988) == 0.0
    assert planned[-1]["end"] == 57.715


def test_final_cue_hold_is_failing_closed_when_no_room_remains() -> None:

    from hevi.layer4_legacy.handdraw.scripts.independent_caption_alignment import (
        _clamp_final_cue_hold,
    )

    planned = [{"start": 65.90, "end": 66.042}]

    with pytest.raises(RuntimeError, match="final caption cannot fit"):
        _clamp_final_cue_hold(planned, media_end=65.913)


def _write_lead_in_then_syllable(path, *, blip_frames, syllable_start, syllable_frames=13):
    """Synthesise a WAV with a short lead-in burst and then a real syllable."""
    import array
    import wave

    rate = 16_000
    total_samples = int(50.0 * rate)
    pcm = [0] * total_samples

    def frames(start_s, count):
        start_idx = int(start_s * rate)
        for index in range(start_idx, start_idx + count * 320):
            if index < len(pcm):
                pcm[index] = 1

    frames(40.12, blip_frames)
    frames(syllable_start, syllable_frames)

    samples = array.array("h", [4000 if flag else 0 for flag in pcm])
    with wave.open(str(path), "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(rate)
        target.writeframes(samples.tobytes())
    return rate, 320


def test_short_lead_in_burst_does_not_anchor_the_caption_onset(tmp_path) -> None:
    """R5 regression: Piper lead-in bursts must not fix the subtitle too early.

    On the 9:16 gratitude run the caption "请你和身边的大人一起练习" was placed at
    40.12s, while the audible syllable starts at 40.44s (rms 0.033 vs 0.007).
    The 20 ms gap is far below the observer's tolerance and the independent ASR
    therefore measured a 0.3s early cue.
    """
    from hevi.layer4_legacy.handdraw.scripts.independent_caption_alignment import (
        _adjust_word_starts_for_silence,
    )

    audio = tmp_path / "lead-in.wav"
    rate, _frame = _write_lead_in_then_syllable(audio, blip_frames=2, syllable_start=40.44)
    words = [{"text": "请", "start": 40.12, "end": 40.70}]

    adjusted = _adjust_word_starts_for_silence(words, audio)

    assert adjusted == 1
    assert words[0]["start"] == pytest.approx(40.44, abs=rate / 320 + 1e-6)


def test_genuine_syllable_onset_is_preserved(tmp_path) -> None:
    """A real sustained syllable must not be pushed later by the new branch."""
    import array
    import wave

    from hevi.layer4_legacy.handdraw.scripts.independent_caption_alignment import (
        _adjust_word_starts_for_silence,
    )

    rate = 16_000
    frame = 320
    audio = tmp_path / "single-syllable.wav"
    samples = array.array("h", [0] * int(3.0 * rate))
    for index in range(int(1.00 * rate), int(1.60 * rate)):
        samples[index] = 4000
    with wave.open(str(audio), "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(rate)
        target.writeframes(samples.tobytes())

    words = [{"text": "谢谢", "start": 1.00, "end": 1.60}]

    assert _adjust_word_starts_for_silence(words, audio) == 0
    assert words[0]["start"] == 1.00
    assert frame > 0
