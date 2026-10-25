"""Tests for hevi.capabilities.narration_srt.

All fixtures are invented here for testing only; no real plot or
character from any production is reused.
"""

from __future__ import annotations

import re

import pytest

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.narration_srt import build_narration, build_srt


def _shots():
    # Invented test fixtures: three unrelated test shots.
    return [
        {
            "shot_id": "S01",
            "duration": 2.5,
            "dialogue": "Test line one.",
            "narration": "Test narration one.",
        },
        {
            "shot_id": "S02",
            "duration": 3,
            "dialogue": "Test line two.",
            "narration": "Test narration two.",
        },
        {
            "shot_id": "S03",
            "duration": 1.5,
            "dialogue": "Test line three.",
            "narration": "Test narration three.",
        },
    ]


def _parse_srt(text):
    blocks = [b for b in text.strip().split("\n\n") if b.strip()]
    parsed = []
    for block in blocks:
        lines = block.split("\n")
        number = int(lines[0])
        start, end = lines[1].split(" --> ")
        parsed.append((number, start, end, "\n".join(lines[2:])))
    return parsed


def test_timeline_accumulates_and_butt_joins():
    result = build_narration(_shots())
    narration = result["narration"]
    assert [entry["shot_id"] for entry in narration] == ["S01", "S02", "S03"]
    assert narration[0]["start_sec"] == 0
    assert narration[0]["end_sec"] == 2.5
    assert narration[1]["start_sec"] == 2.5
    assert narration[1]["end_sec"] == 5.5
    assert narration[2]["start_sec"] == 5.5
    assert narration[2]["end_sec"] == 7.0
    # Seamless: each end equals the next start, total is the last end.
    for prev, nxt in zip(narration, narration[1:]):
        assert abs(prev["end_sec"] - nxt["start_sec"]) <= 1e-9
    assert narration[0]["start_sec"] == 0
    assert narration[-1]["end_sec"] == 7.0
    assert all(entry["missing"] is False for entry in narration)
    assert narration[1]["text"] == "Test narration two."


def test_timeline_float_durations():
    shots = [
        {"shot_id": "A", "duration": 0.5, "narration": "Half second."},
        {"shot_id": "B", "duration": 1.25, "narration": "One and a quarter."},
    ]
    narration = build_narration(shots)["narration"]
    assert narration[0]["start_sec"] == 0
    assert narration[0]["end_sec"] == 0.5
    assert narration[1]["start_sec"] == 0.5
    assert narration[1]["end_sec"] == 1.75


def test_srt_format_numbers_timestamps_and_text():
    parsed = _parse_srt(build_srt(_shots()))
    # Two cues per shot: dialogue then narration.
    assert len(parsed) == 6
    assert [cue[0] for cue in parsed] == [1, 2, 3, 4, 5, 6]
    stamp = re.compile(r"^\d{2}:\d{2}:\d{2},\d{3}$")
    for _, start, end, _ in parsed:
        assert stamp.match(start) and stamp.match(end)
    # Shot 1 spans 0-2.5s: dialogue first half, narration second half.
    assert parsed[0] == (1, "00:00:00,000", "00:00:01,250", "Test line one.")
    assert parsed[1] == (
        2,
        "00:00:01,250",
        "00:00:02,500",
        "Test narration one.",
    )
    # Shot 2 spans 2.5-5.5s.
    assert parsed[2][1] == "00:00:02,500"
    assert parsed[3][2] == "00:00:05,500"
    assert parsed[2][3] == "Test line two."
    assert parsed[3][3] == "Test narration two."


def test_srt_timestamp_flooring():
    shots = [{"shot_id": "X", "duration": 1.2349, "dialogue": "Floor check."}]
    parsed = _parse_srt(build_srt(shots))
    assert len(parsed) == 1
    # 1.2349s floors to 1234ms, never rounds up to 1235ms.
    assert parsed[0][2] == "00:00:01,234"


def test_srt_switches():
    # Dialogue only: one cue per shot, whole shot each.
    parsed = _parse_srt(build_srt(_shots(), include_narration=False))
    assert len(parsed) == 3
    assert [cue[3] for cue in parsed] == [
        "Test line one.",
        "Test line two.",
        "Test line three.",
    ]
    assert parsed[0][1] == "00:00:00,000"
    assert parsed[0][2] == "00:00:02,500"
    # Narration only: one cue per shot, whole shot each.
    parsed = _parse_srt(build_srt(_shots(), include_dialogue=False))
    assert len(parsed) == 3
    assert [cue[3] for cue in parsed] == [
        "Test narration one.",
        "Test narration two.",
        "Test narration three.",
    ]
    assert parsed[1][1] == "00:00:02,500"
    assert parsed[1][2] == "00:00:05,500"
    # Both on: two cues per shot.
    parsed = _parse_srt(build_srt(_shots()))
    assert len(parsed) == 6


def test_missing_narration_flagged_and_no_empty_cue():
    shots = [
        {"shot_id": "S01", "duration": 2, "dialogue": "Spoken.", "narration": ""},
        {"shot_id": "S02", "duration": 2, "dialogue": "Spoken two."},
    ]
    narration = build_narration(shots)["narration"]
    assert narration[0] == {
        "shot_id": "S01",
        "text": "",
        "start_sec": 0.0,
        "end_sec": 2.0,
        "missing": True,
    }
    assert narration[1]["missing"] is True
    assert narration[1]["text"] == ""
    # SRT invents nothing: only the two dialogue cues appear, and
    # with a single kind present each takes its whole shot.
    parsed = _parse_srt(build_srt(shots))
    assert len(parsed) == 2
    assert parsed[0] == (1, "00:00:00,000", "00:00:02,000", "Spoken.")
    assert parsed[1] == (2, "00:00:02,000", "00:00:04,000", "Spoken two.")


def test_missing_dialogue_only_narration_cue():
    shots = [{"shot_id": "S01", "duration": 4, "narration": "Voice only."}]
    parsed = _parse_srt(build_srt(shots))
    assert parsed == [(1, "00:00:00,000", "00:00:04,000", "Voice only.")]


@pytest.mark.parametrize(
    "bad_shots",
    [
        [],
        [{"duration": 2, "narration": "No id."}],
        [{"shot_id": "", "duration": 2, "narration": "Empty id."}],
        [{"shot_id": "S01", "narration": "No duration."}],
        [{"shot_id": "S01", "duration": 0, "narration": "Zero."}],
        [{"shot_id": "S01", "duration": -1, "narration": "Negative."}],
        [{"shot_id": "S01", "duration": "two", "narration": "Not a number."}],
        [{"shot_id": "S01", "duration": None, "narration": "None duration."}],
        [{"shot_id": "S01", "duration": True, "narration": "Bool is not a number."}],
    ],
)
def test_invalid_shots_raise(bad_shots):
    with pytest.raises(CapabilityError):
        build_narration(bad_shots)
    with pytest.raises(CapabilityError):
        build_srt(bad_shots)


def test_both_switches_off_raises():
    with pytest.raises(CapabilityError):
        build_srt(_shots(), include_dialogue=False, include_narration=False)


def test_blank_lines_folded_without_breaking_blocks():
    shots = [
        {
            "shot_id": "S01",
            "duration": 4,
            "dialogue": "First line.\n\nSecond line.",
            "narration": "Voice.\n\n\nMore voice.",
        }
    ]
    text = build_srt(shots)
    parsed = _parse_srt(text)
    assert len(parsed) == 2
    assert parsed[0][3] == "First line. Second line."
    assert parsed[1][3] == "Voice. More voice."
    # No empty line inside a block: re-splitting on blank lines
    # still yields exactly the two cue blocks.
    assert len([b for b in text.strip().split("\n\n") if b.strip()]) == 2


def test_multiline_cue_text_preserved():
    shots = [
        {
            "shot_id": "S01",
            "duration": 4,
            "dialogue": "Line one.\nLine two.",
        }
    ]
    parsed = _parse_srt(build_srt(shots))
    assert parsed[0][3] == "Line one.\nLine two."


def test_duration_sec_fallback_matches_edit_assemble_spelling():
    shots = [{"shot_id": "S01", "duration_sec": 3, "narration": "Fallback."}]
    narration = build_narration(shots)["narration"]
    assert narration[0]["end_sec"] == 3.0
