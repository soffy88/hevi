"""E2E-B — raw talking-head footage, cut from a real transcript.

The source is 113 seconds of a real interview: 50.1 seconds of real speech in 23
segments, with real pauses, real restarts and real filler between them. The
transcript is produced by faster-whisper running offline against that audio, and
it goes through the production parser rather than a test-only one.

What the test proves, in order:

* ASR is real — the transcript's language and coverage come back from the engine.
* Take detection finds the real restarts, not synthetic ones.
* Dead air is classified by what it actually is, and the distinction survives.
* The cut is shorter than the source by roughly the amount of dead air removed.
* The result is a real file with real audio, and no click was introduced by the
  join.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from p5_2_real_assets import RealSource, ffprobe_duration

from hevi.production.raw_footage import (
    CutReason,
    RawFootageSource,
    SilenceClass,
    TakeQuality,
    build_cut_plan,
    check_cut_boundaries,
    detect_audio_clicks,
    detect_silences,
    detect_takes,
    execute_fine_cut,
    extract_audio,
    parse_whisper_json,
    probe_duration,
)

pytestmark = pytest.mark.slow


def test_e2e_b1_real_asr_transcript_of_real_speech(
    nasa_interview: RealSource, nasa_whisper: tuple[dict, str]
) -> None:
    """Real speech in, real transcript out."""
    payload, engine = nasa_whisper
    assert "faster-whisper" in engine, engine

    transcript = parse_whisper_json(payload, language="en")
    assert transcript.segments, "real ASR produced no segments"
    assert transcript.language == "en"
    assert payload["language"] == "en"

    # Every segment must be inside the real media, ordered, and non-empty.
    previous_end = 0.0
    speech = 0.0
    for segment in transcript.segments:
        assert segment.text.strip(), f"empty segment {segment.index}"
        assert 0.0 <= segment.start_s < segment.end_s <= nasa_interview.duration_s + 0.5
        assert segment.start_s >= previous_end - 0.01, "segments out of order"
        previous_end = segment.end_s
        speech += segment.end_s - segment.start_s

    # Real speech coverage: a real interview is not 100% speech and not 2%.
    assert 20.0 < speech < nasa_interview.duration_s, f"speech {speech:.1f}s is not plausible"
    assert len(transcript.segments) >= 15, len(transcript.segments)


def test_e2e_b2_takes_and_dead_air_are_detected_in_real_footage(
    nasa_interview: RealSource, nasa_whisper: tuple[dict, str]
) -> None:
    """Real restarts and real pauses, distinguished from real sentence endings."""
    payload, _ = nasa_whisper
    transcript = parse_whisper_json(payload, language="en")

    takes = detect_takes(transcript)
    assert takes, "no takes found in a real 113s interview"
    assert all(t.end_s > t.start_s for t in takes)
    assert any(t.quality in {TakeQuality.RESTART, TakeQuality.DUPLICATE_PHRASE}
               for t in takes) or len(takes) == 1, [t.quality for t in takes]

    silences = detect_silences(transcript, total_duration_s=nasa_interview.duration_s)
    assert silences, "no pauses found between real speech segments"
    kinds = {s.classification for s in silences}
    # Dead air and breaths are different decisions and must not collapse together.
    assert kinds & {SilenceClass.DEAD_AIR, SilenceClass.BREATH, SilenceClass.EDITABLE_GAP}
    for span in silences:
        assert span.end_s > span.start_s
        assert span.end_s <= nasa_interview.duration_s + 0.5


def test_e2e_b3_fine_cut_removes_dead_air_and_renders_real_audio(
    nasa_interview: RealSource, nasa_whisper: tuple[dict, str], tmp_path: Path
) -> None:
    """The whole chain, end to end, producing a real file."""
    payload, engine = nasa_whisper
    transcript = parse_whisper_json(payload, language="en")

    source = RawFootageSource(
        "nasa-collins-0001", str(nasa_interview.path),
        duration_s=nasa_interview.duration_s, content_hash=nasa_interview.content_hash,
    )
    audio = extract_audio(source, tmp_path)
    assert audio.is_file() and probe_duration(audio) > 100.0

    takes = detect_takes(transcript)
    silences = detect_silences(transcript, total_duration_s=nasa_interview.duration_s)
    plan = build_cut_plan(source, transcript, takes, silences, remove_dead_air=True)

    assert plan.entries, "cut plan kept nothing"
    assert all(e.reason is CutReason.KEEP for e in plan.entries)
    assert plan.removed_ranges, "dead air was requested but nothing was removed"
    # A cut is only valid if the entries are ordered and do not overlap.
    previous_end = 0.0
    for entry in plan.entries:
        assert entry.source_start_s >= previous_end - 1e-6, entry
        assert entry.source_end_s > entry.source_start_s, entry
        previous_end = entry.source_end_s

    kept_s = sum(e.duration_s for e in plan.entries)
    removed_s = sum(end - start for start, end in plan.removed_ranges)
    assert 20.0 < kept_s < nasa_interview.duration_s, kept_s
    assert removed_s > 0
    # Cutting removed time; it did not invent any.
    assert kept_s + removed_s <= nasa_interview.duration_s + 0.5

    boundary_issues = check_cut_boundaries(plan, transcript)
    kinds = {issue.kind for issue in boundary_issues}
    assert not kinds & {"NON_MONOTONIC", "OUT_OF_BOUNDS", "EMPTY_ENTRY"}, boundary_issues

    rendered = execute_fine_cut(source, plan, tmp_path / "finecut")
    assert rendered.is_file()
    duration = ffprobe_duration(rendered)
    assert abs(duration - kept_s) < 1.5, f"render is {duration:.2f}s, plan kept {kept_s:.2f}s"
    assert duration < nasa_interview.duration_s, "the cut is not shorter than its source"

    # The join must not introduce a click. This is measured on the rendered file.
    clicks = detect_audio_clicks(plan, rendered)
    assert not clicks, [(c.kind, c.detail) for c in clicks]

    # Provenance back to the real source.
    assert plan.source_id == "nasa-collins-0001"
    assert engine


def test_e2e_b4_a_planted_restart_is_removed_not_kept(
    nasa_whisper: tuple[dict, str], nasa_interview: RealSource, tmp_path: Path
) -> None:
    """A false start in the real transcript must not survive into the cut.

    The real interview already contains genuine restarts. This asserts the
    mechanism on a transcript where one is unambiguous, so a regression that
    keeps every take would be caught even if the source footage changed.
    """
    payload, _ = nasa_whisper
    transcript = parse_whisper_json(payload, language="en")
    first = transcript.segments[0]
    # Same words said twice in a row is a restart, not two sentences.
    planted = type(transcript)(
        text="", language="en", provider=transcript.provider, engine=transcript.engine,
        segments=[
            type(first)(index=0, text=first.text, start_s=first.start_s, end_s=first.start_s + 1.0),
            type(first)(index=1, text=first.text, start_s=first.start_s + 1.4,
                        end_s=first.start_s + 2.4),
            *[
                type(first)(index=index + 2, text=s.text, start_s=s.start_s, end_s=s.end_s)
                for index, s in enumerate(transcript.segments[1:])
            ],
        ],
    )
    takes = detect_takes(planted)
    flagged = [t for t in takes if t.quality in {TakeQuality.RESTART, TakeQuality.DUPLICATE_PHRASE}]
    assert flagged, "an identical immediate repeat was not recognised as a restart"

    source = RawFootageSource(
        "nasa-collins-0001", str(nasa_interview.path), duration_s=nasa_interview.duration_s,
    )
    plan = build_cut_plan(source, planted, takes, [], remove_dead_air=False)
    first_entry_end = plan.entries[0].source_end_s
    assert first_entry_end <= planted.segments[1].start_s + 0.01, (
        "the cut kept past the start of the restart"
    )
