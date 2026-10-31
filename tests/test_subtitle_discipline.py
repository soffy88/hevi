"""Tests for edit.subtitle_discipline: breaks, glossary, freshness, zone."""

from __future__ import annotations

from pathlib import Path

import pytest

import hevi.capabilities as caps
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.subtitle_discipline import (
    apply_glossary,
    break_lines,
    validate_events,
)

GLOSSARY = {"PixStag": ["pixstag", "Pixstag"]}


def _ev(text: str, start: float = 0.0, end: float = 2.0) -> dict:
    return {"start_sec": start, "end_sec": end, "text": text}


def test_breath_break_packs_phrases_within_15(tmp_path: Path) -> None:
    broken = break_lines("春天来了，花开了，鸟儿在唱歌")
    assert broken["lines"] == ["春天来了，花开了，鸟儿在唱歌"]
    assert broken["forced_splits"] == []
    assert all(len(line) <= 15 for line in broken["lines"])


def test_single_overlong_phrase_is_flagged_not_silently_split(tmp_path: Path) -> None:
    broken = break_lines("这是一个很长很长的句子需要断句处理才行")
    assert broken["forced_splits"] != []
    report = validate_events(
        [_ev("这是一个很长很长的句子需要断句处理才行")],
        transcript_source="post_edit_retranscription",
        orientation="horizontal",
    )
    assert any(f["kind"] == "phrase_split_forced" for f in report["failures"])


def test_glossary_replaces_and_gate_flags_variant(tmp_path: Path) -> None:
    clean, replaced = apply_glossary("用 pixstag 出片", GLOSSARY)
    assert clean == "用 PixStag 出片"
    assert replaced == ["pixstag"]
    report = validate_events(
        [_ev("用 pixstag 出片")],
        glossary=GLOSSARY,
        transcript_source="post_edit_retranscription",
        orientation="horizontal",
    )
    assert any(f["kind"] == "glossary_variant" for f in report["failures"])
    good = validate_events(
        [_ev("用 PixStag 出片")],
        glossary=GLOSSARY,
        transcript_source="post_edit_retranscription",
        orientation="horizontal",
    )
    assert good["verdict"] == "pass"


def test_stale_timeline_and_safe_zone_fail(tmp_path: Path) -> None:
    stale = validate_events(
        [_ev("春天来了，花开了")],
        transcript_source="pre_edit_timeline",
        orientation="horizontal",
    )
    assert any(f["kind"] == "stale_timeline" for f in stale["failures"])
    low = validate_events(
        [_ev("春天来了，花开了")],
        transcript_source="post_edit_retranscription",
        orientation="vertical",
        subtitle_bottom_fraction=0.92,
    )
    assert any(f["kind"] == "vertical_safe_zone" for f in low["failures"])
    ok = validate_events(
        [_ev("春天来了，花开了")],
        transcript_source="post_edit_retranscription",
        orientation="vertical",
        subtitle_bottom_fraction=0.70,
    )
    assert ok["verdict"] == "pass"


def test_emoji_banned_and_overlap_raises(tmp_path: Path) -> None:
    report = validate_events(
        [_ev("你好 \U0001f600")],
        transcript_source="post_edit_retranscription",
        orientation="horizontal",
    )
    assert any(f["kind"] == "emoji_in_caption" for f in report["failures"])
    with pytest.raises(CapabilityError):
        validate_events(
            [_ev("第一句", 0.0, 2.0), _ev("第二句", 1.0, 3.0)],
            orientation="horizontal",
        )


def test_registry_gate(tmp_path: Path) -> None:
    cap = caps.get("edit.subtitle_discipline")
    result = cap.render_safe(
        {"events": [_ev("春天来了，花开了")],
         "transcript_source": "post_edit_retranscription",
         "orientation": "horizontal"},
        tmp_path / "out", duration=0.0, aspect="16:9", seed=1,
    )
    assert result.qa["verdict"] == "pass"


def test_edited_without_fresh_transcript_is_stale_timeline(tmp_path: Path) -> None:
    missing = validate_events(
        [_ev("春天来了，花开了")], edited=True, orientation="horizontal",
    )
    assert any(f["kind"] == "stale_timeline" for f in missing["failures"])
    assert missing["verdict"] == "fail"
    stale = validate_events(
        [_ev("春天来了，花开了")], edited=True,
        transcript_source="pre_edit_timeline", orientation="horizontal",
    )
    assert any(f["kind"] == "stale_timeline" for f in stale["failures"])
    fresh = validate_events(
        [_ev("春天来了，花开了")], edited=True,
        transcript_source="post_edit_retranscription", orientation="horizontal",
    )
    assert fresh["verdict"] == "pass"
    undeclared = validate_events(
        [_ev("春天来了，花开了")], orientation="horizontal",
    )
    assert not any(f["kind"] == "stale_timeline" for f in undeclared["failures"])


def test_vo_asr_mismatch_fails_and_match_passes(tmp_path: Path) -> None:
    bad = validate_events(
        [_ev("玉兰开了")], transcript_source="post_edit_retranscription",
        orientation="horizontal", asr_text="完全不相干的旁白。",
    )
    assert any(f["kind"] == "vo_asr_mismatch" for f in bad["failures"])
    good = validate_events(
        [_ev("玉兰开了")], transcript_source="post_edit_retranscription",
        orientation="horizontal", asr_text="玉兰开了，春天来了。",
    )
    assert good["verdict"] == "pass"


def test_vo_word_timings_outside_window_fail_alignment(tmp_path: Path) -> None:
    in_window = validate_events(
        [_ev("玉兰开了", 0.0, 2.0)],
        transcript_source="post_edit_retranscription", orientation="horizontal",
        vo_word_timings=[{"text": "玉兰开了", "start_ms": 100, "end_ms": 900}],
    )
    assert in_window["verdict"] == "pass"
    out_of_window = validate_events(
        [_ev("玉兰开了", 0.0, 2.0)],
        transcript_source="post_edit_retranscription", orientation="horizontal",
        vo_word_timings=[{"text": "玉兰开了", "start_ms": 99000, "end_ms": 99900}],
    )
    assert any(f["kind"] == "vo_alignment_mismatch"
               for f in out_of_window["failures"])
