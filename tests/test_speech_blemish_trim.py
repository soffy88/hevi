"""Tests for edit.speech_blemish_trim: live recordings only, never TTS."""

from __future__ import annotations

import pytest

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.speech_blemish_trim import plan_trim


def _word(word: str, start: float, end: float) -> dict:
    return {"word": word, "start_sec": start, "end_sec": end}


def test_filler_and_repetition_are_cut_with_keep_intervals() -> None:
    words = [
        _word("你好", 0.0, 0.4),
        _word("嗯", 0.5, 0.9),
        _word("开始", 1.0, 1.5),
        _word("开始", 1.6, 2.0),
        _word("动手", 2.1, 2.6),
    ]
    plan = plan_trim(words, source_kind="live_recording")
    assert plan["kept_words"] == ["你好", "开始", "动手"]
    assert plan["kept_intervals"] == [
        {"start_sec": 0.0, "end_sec": 0.4},
        {"start_sec": 1.0, "end_sec": 1.5},
        {"start_sec": 2.1, "end_sec": 2.6},
    ]
    decisions = {tuple(s["words"]): s["decision"] for s in plan["segments"]}
    assert decisions[("嗯",)] == "approved"


def test_provisional_captions_are_retimed_past_cuts() -> None:
    words = [
        _word("你好", 0.0, 0.4),
        _word("嗯", 0.5, 0.9),
        _word("动手", 1.0, 1.5),
    ]
    plan = plan_trim(words, source_kind="live_recording")
    captions = plan["provisional_captions_from_kept_words"]
    assert [c["word"] for c in captions] == ["你好", "动手"]
    assert captions[1]["start_sec"] == pytest.approx(0.6)
    assert "NOT a post-trim retranscription" in plan["retranscription_note"]
    assert any("fresh transcription" in step for step in plan["post_trim_steps"])


def test_edge_candidate_is_blocked_by_keep_before_after_guard() -> None:
    words = [
        _word("嗯", 0.0, 0.4),
        _word("你好", 0.5, 1.0),
        _word("再见", 1.1, 1.6),
    ]
    plan = plan_trim(words, source_kind="live_recording")
    assert plan["segments"][0]["decision"] == "blocked"
    assert plan["segments"][0]["risk"] == "high"
    assert "keep-before" in plan["segments"][0]["block_reason"]
    assert plan["kept_words"] == ["嗯", "你好", "再见"]


def test_review_checklist_covers_every_candidate() -> None:
    words = [
        _word("你好", 0.0, 0.4),
        _word("呃", 0.5, 0.9),
        _word("动手", 1.0, 1.5),
    ]
    plan = plan_trim(words, source_kind="live_recording")
    assert len(plan["review_checklist"]) == 1
    assert plan["review_checklist"][0]["decision"] == "approved"
    assert plan["review_checklist"][0]["checks"]


def test_tts_track_is_refused_not_fake_trimmed() -> None:
    words = [_word("你好", 0.0, 0.4), _word("嗯", 0.5, 0.9),
             _word("动手", 1.0, 1.5)]
    with pytest.raises(CapabilityError, match="TTS"):
        plan_trim(words, source_kind="tts")


def test_non_live_source_is_refused() -> None:
    words = [_word("你好", 0.0, 0.4), _word("动手", 0.5, 1.0)]
    with pytest.raises(CapabilityError, match="live_recording"):
        plan_trim(words, source_kind="unknown")


def test_malformed_word_entries_are_refused() -> None:
    with pytest.raises(CapabilityError):
        plan_trim([{"word": "你好", "start_sec": 1.0, "end_sec": 0.5}],
                  source_kind="live_recording")
