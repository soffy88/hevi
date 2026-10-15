"""Regression tests for page clocks after independent caption alignment."""

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
    assert timeline["pages"][1]["last_drawing_end"] == 27.6
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
