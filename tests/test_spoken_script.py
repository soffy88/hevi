"""Tests for script.spoken_script_gate: per-sentence issues, no score."""

from __future__ import annotations

import pytest

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.spoken_script import check_script


def _rules(report: dict, index: int) -> list[str]:
    return [i["rule"] for i in report["sentences"][index]["issues"]]


def test_plain_spoken_script_passes() -> None:
    report = check_script("今天我们聊一个办法。先看一个例子，再动手试一次。")
    assert report["verdict"] == "pass"
    assert report["issue_count"] == 0
    assert all(s["speakable"] for s in report["sentences"])


def test_long_sentence_is_flagged_with_a_rewrite() -> None:
    report = check_script(
        "这是一个非常非常长的句子它一直不停地说下去而且完全没有"
        "停下来的意思让人一口气根本念不完。")
    assert report["verdict"] == "fail"
    assert "long_sentence" in _rules(report, 0)
    issue = report["sentences"][0]["issues"][0]
    assert "Split" in issue["suggestion"]


def test_written_connective_gets_spoken_replacement() -> None:
    report = check_script("然而这个办法需要每天练习。")
    assert "written_connective" in _rules(report, 0)
    issue = report["sentences"][0]["issues"][0]
    assert "可是" in issue["suggestion"]


def test_parallel_list_is_flagged_for_breaking_up() -> None:
    report = check_script("它快、它稳、它强、它便宜。")
    assert "parallel_list" in _rules(report, 0)


def test_unpronounceable_punctuation_is_flagged() -> None:
    report = check_script("打开《新手手册》看第一章。")
    assert "unpronounceable_punctuation" in _rules(report, 0)


def test_fullwidth_square_brackets_are_flagged() -> None:
    bracketed = "看" + chr(0x3010) + "重点" + chr(0x3011) + "这一段。"
    report = check_script(bracketed)
    assert "unpronounceable_punctuation" in _rules(report, 0)


def test_stock_phrase_is_flagged_for_deletion() -> None:
    report = check_script("众所周知，这个办法很有效。")
    assert "stock_phrase" in _rules(report, 0)


def test_vague_adjective_needs_number_example_or_action() -> None:
    report = check_script("这个办法非常好，没有具体数字。")
    assert "vague_adjective" in _rules(report, 0)
    issue = report["sentences"][0]["issues"][0]
    assert "具体数字" in issue["suggestion"] or "number" in issue["suggestion"]


def test_each_problem_sentence_lists_its_own_fix() -> None:
    report = check_script(
        "然而这个办法需要每天练习。这个办法非常好，没有具体数字。")
    assert report["sentences_checked"] == 2
    assert report["sentences"][0]["issues"]
    assert report["sentences"][1]["issues"]
    for sentence in report["sentences"]:
        for issue in sentence["issues"]:
            assert issue["suggestion"]


def test_empty_script_is_refused() -> None:
    with pytest.raises(CapabilityError):
        check_script("   ")
