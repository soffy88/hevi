"""Tests for research.reference_teardown: evidence only, gaps as gaps."""

from __future__ import annotations

import pytest

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.reference_teardown import (
    ORIGINALITY_DECLARATION,
    fetch_reference,
    review_title_candidate,
    structure_transcript,
    teardown_reference,
)

SOURCE = (
    "开场先问你一个问题：为什么每天练还是弹不好？"
    "很多人练琴的痛点是手指总是不听使唤，练得多错得多。"
    "其实关键是每天只练十分钟慢速音阶，坚持两周就有变化。"
    "下一期我们讲左手怎么放松，你想先看哪一段？留言告诉我。"
)


def test_four_questions_answered_from_quoted_evidence() -> None:
    report = teardown_reference(SOURCE)
    questions = report["questions"]
    assert questions["hook"]["evidence"].startswith("开场先问你")
    assert "痛点" in questions["pain_point"]["evidence"]
    assert "十分钟" in questions["information_gain"]["evidence"]
    assert questions["closing_hook"]["evidence"].startswith("留言告诉我")
    assert questions["closing_hook"]["is_hook"] is True


def test_missing_evidence_is_reported_as_a_gap_not_invented() -> None:
    report = teardown_reference("今天天气很好。我们去散步吧。")
    assert report["questions"]["pain_point"]["found"] is False
    assert report["questions"]["pain_point"]["evidence"] is None
    assert "not found" in report["questions"]["pain_point"]["note"]
    assert report["questions"]["information_gain"]["found"] is False


def test_every_report_carries_the_originality_declaration() -> None:
    report = teardown_reference(SOURCE)
    assert "Teardown only" in report["originality_declaration"]
    assert "original" in report["originality_declaration"]
    assert ORIGINALITY_DECLARATION in report["originality_declaration"]


def test_risky_title_is_flagged_and_clean_title_passes() -> None:
    risky = review_title_candidate("30天保证弹好", SOURCE)
    assert risky["verdict"] == "risky"
    assert len(risky["risks"]) >= 2
    clean = review_title_candidate("每天十分钟慢速音阶", SOURCE)
    assert clean["verdict"] == "ok"
    assert clean["risks"] == []


def test_overlong_title_is_flagged() -> None:
    review = review_title_candidate("这是一个非常非常非常长的标题候选超过二十字了", SOURCE)
    assert any("overlong" in r or "cut off" in r for r in review["risks"])


def test_fetch_without_backend_lists_the_gap() -> None:
    result = fetch_reference("https://example.com/video")
    assert result["ok"] is False
    assert result["content"] is None
    assert result["analysis"] is None
    assert result["missing_backends"]


def test_fetch_failure_lists_the_gap_without_fabrication() -> None:
    def _boom(url: str) -> str:
        raise RuntimeError("network down")

    result = fetch_reference("https://example.com/video", fetcher=_boom)
    assert result["ok"] is False
    assert result["content"] is None


def test_fetch_success_returns_content_untouched() -> None:
    result = fetch_reference(
        "https://example.com/video", fetcher=lambda url: SOURCE)
    assert result["ok"] is True
    assert result["content"] == SOURCE


def test_transcript_structures_hook_body_closing() -> None:
    transcript = (
        "[00:05] 大家好，今天聊练琴\n"
        "[00:30] 先讲手指放松\n"
        "没有时间戳的一句\n"
        "[01:00] 下期见"
    )
    structured = structure_transcript(transcript)
    assert structured["sections"]["hook"]["timestamp"] == "00:05"
    assert structured["sections"]["closing"]["text"] == "下期见"
    assert len(structured["sections"]["body"]) == 2
    assert structured["entries"][2]["timestamp"] is None


def test_empty_source_is_refused() -> None:
    with pytest.raises(CapabilityError):
        teardown_reference("   ")
