"""Offline tests for the lanshu-explainer audio-locked timeline builder."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SKILL_DIR = Path(__file__).resolve().parent.parent / "hevi" / "skills" / "lanshu-explainer"

spec = importlib.util.spec_from_file_location(
    "lanshu_story_audio_lock", SKILL_DIR / "tools" / "story_audio_lock.py"
)
sal = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sal)

CHAPTERS = [
    {"key": "problem", "title": "问题", "lines": ["你好。", "世界！"]},
    {"key": "method", "title": "方法", "lines": ["缓存。"]},
]


def _timings() -> list[dict]:
    out: list[dict] = []
    t = 400
    for text in ["你好。", "世界！", "缓存。"]:
        for ch in text:
            out.append({"word": ch, "start_ms": t, "end_ms": t + 150})
            t += 200
    return out


def _story():
    return sal.story_from_word_timings(
        "KV cache", CHAPTERS, _timings(), voice="hevi tts · soffy",
    )


def test_build_produces_lanshu_story_contract():
    story = _story()
    assert story["title"] == "KV cache"
    assert story["timing"] == "measured"
    assert story["draft"] is False
    assert len(story["lines"]) == 3
    line = story["lines"][0]
    assert line["text"] == "你好。"
    assert line["start"] == 0.4
    assert line["words"][0] == ["你", 0.4]
    assert line["chapter"] == "problem"
    assert [c["key"] for c in story["chapters"]] == ["problem", "method"]
    assert story["duration"] == story["lines"][-1]["end"]


def test_check_audio_lock_passes_on_built_story():
    assert sal.check_audio_lock(_story()) == []


def test_check_audio_lock_detects_out_of_order_words():
    story = _story()
    w = story["lines"][0]["words"]
    w[0], w[1] = w[1], w[0]
    assert any("not in order" in p for p in sal.check_audio_lock(story))


def test_check_audio_lock_detects_duration_mismatch():
    story = _story()
    story["duration"] = story["duration"] + 5
    assert any("duration" in p for p in sal.check_audio_lock(story))


def test_check_audio_lock_rejects_draft():
    story = _story()
    story["draft"] = True
    assert any("draft" in p for p in sal.check_audio_lock(story))


def test_build_rejects_word_count_mismatch():
    timings = _timings()
    timings.pop()
    with pytest.raises(ValueError, match="word_timings"):
        sal.story_from_word_timings("t", CHAPTERS, timings)


def test_build_rejects_text_mismatch():
    timings = _timings()
    timings[1]["word"] = "错"
    with pytest.raises(ValueError, match="do not match line text"):
        sal.story_from_word_timings("t", CHAPTERS, timings)
