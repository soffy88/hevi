"""Tests for the commentary-LONG line: five-segment long template,
YouTube long board, and long Jianying draft plan (all plan only).

Run: .venv/bin/python -m pytest tests/test_commentary_long.py -q
"""

import copy

import pytest

from hevi.capabilities import get as get_capability
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.five_segment_long import build_template, tts_slot
from hevi.capabilities.youtube_long_board import (
    build_long_board,
    build_long_draft_plan,
    estimate_shots,
)


def _text(n):
    return "读" * n


def _spec(**overrides):
    segments = [
        {"index": 1, "name": "现场还原", "duration_sec": 330, "narration": _text(1595), "image_count": 41},
        {"index": 2, "name": "困局代入", "duration_sec": 330, "narration": _text(1595), "image_count": 41,
         "decision_pause_sec": 3.0, "question_subtitle": "如果是你，你会怎么答？"},
        {"index": 3, "name": "古人怎么做", "duration_sec": 420, "narration": _text(2030), "image_count": 53,
         "delivery": "commentary"},
        {"index": 4, "name": "对照抽理", "duration_sec": 330, "narration": _text(1595), "image_count": 41},
        {"index": 5, "name": "鉴今升华", "duration_sec": 390, "narration": _text(1885), "image_count": 49,
         "modern_terms": ["今天"]},
    ]
    spec = {"title": "少年立志", "topic": "王阳明少年立志", "segments": segments,
            "total_duration_sec": 1800}
    for key, value in overrides.items():
        if key.startswith("seg"):
            segments[int(key[3]) - 1].update(value)
        else:
            spec[key] = value
    return spec


def test_long_template_valid():
    result = build_template(_spec())
    assert result["total_duration_sec"] == 1800
    assert result["total_narration_chars"] == 8700
    assert result["total_image_count"] == 225
    assert result["format_label"] == "解说长片"
    assert "不是演绎真片" in result["disclaimer"]
    assert result["segments"][2]["delivery"] == "commentary"
    assert result["segments"][1]["question_subtitle"] == "如果是你，你会怎么答？"
    assert result["segments"][1]["speaking_sec"] == 327.0


def test_long_template_total_outside_range():
    with pytest.raises(CapabilityError):
        build_template(_spec(seg1={"duration_sec": 100}))
    with pytest.raises(CapabilityError):
        build_template(_spec(seg3={"narration": _text(100)}))


def test_long_template_wrong_order_and_modern():
    with pytest.raises(CapabilityError):
        build_template(_spec(seg1={"name": "困局代入"}))
    with pytest.raises(CapabilityError):
        build_template(_spec(seg1={"narration": _text(1595) + "手机"}))
    # segment 5 may carry modern terms; segment 1 may not
    result = build_template(_spec())
    assert result["segments"][4]["modern_terms"] == ["今天"]


def test_long_template_pause_question_live_action():
    with pytest.raises(CapabilityError):
        build_template(_spec(seg2={"decision_pause_sec": 30.0}))
    with pytest.raises(CapabilityError):
        build_template(_spec(seg2={"question_subtitle": "你觉得呢？"}))
    with pytest.raises(CapabilityError):
        build_template(_spec(seg3={"delivery": "live_action"}))
    with pytest.raises(CapabilityError):
        build_template(_spec(seg3={"is_live_action": True}))


def test_long_template_tts_slots():
    assert tts_slot(None)["status"] == "not_requested"
    assert tts_slot("luxtts_notebook")["status"] == "deferred_to_production_run"
    with pytest.raises(CapabilityError):
        tts_slot("doubao")
    with pytest.raises(CapabilityError):
        tts_slot("elevenlabs")


def _board():
    sections = [
        {"segment": 1, "section_title": "现场还原", "start_sec": 0, "end_sec": 330,
         "summary": "京师入冬清晨塾馆", "research_fields": {"dynasty": "明代"}},
        {"segment": 2, "section_title": "困局代入", "start_sec": 330, "end_sec": 660,
         "summary": "众答登第与守仁的停顿", "research_fields": {"exam_system": "research_pending"}},
        {"segment": 3, "section_title": "古人怎么做", "start_sec": 660, "end_sec": 1080,
         "summary": "守仁答做圣贤", "research_fields": {}},
        {"segment": 4, "section_title": "对照抽理", "start_sec": 1080, "end_sec": 1410,
         "summary": "记住与明白", "research_fields": {}},
        {"segment": 5, "section_title": "鉴今升华", "start_sec": 1410, "end_sec": 1800,
         "summary": "今天也一样", "research_fields": {}},
    ]
    return {"title": "少年立志", "total_duration_sec": 1800, "sections": sections}


def test_long_board_valid_and_chapters():
    result = build_long_board(_board())
    assert result["width"] == 1920 and result["height"] == 1080 and result["fps"] == 30
    assert result["shot_estimate_round"] == 225
    assert result["chapters"][0] == {"start": "0:00", "start_sec": 0, "title": "第1段"}
    assert [c["start"] for c in result["chapters"]] == ["0:00", "5:30", "11:00", "18:00", "23:30"]
    assert result["research_pending"] == ["section 1 research_pending: exam_system"]
    assert result["media_status"] == "plan_only_no_images_no_audio"


def test_long_board_gap_overlap_first_not_zero():
    bad = _board()
    bad["sections"][1]["start_sec"] = 400
    with pytest.raises(CapabilityError):
        build_long_board(bad)
    bad = _board()
    bad["sections"][0]["start_sec"] = 10
    with pytest.raises(CapabilityError):
        build_long_board(bad)
    assert estimate_shots(1800) == 225
    assert estimate_shots(1500) == 188
    with pytest.raises(CapabilityError):
        build_long_board({"title": "x", "total_duration_sec": 100, "sections": []})


def test_long_draft_plan_valid():
    plan = {"title": "少年立志", "shots": [
        {"duration_sec": 8, "image": "pending_no_image", "caption": "京师入冬清晨"},
        {"duration_sec": 8, "image": "pending_no_image", "caption": "塾馆"},
    ]}
    result = build_long_draft_plan(plan)
    assert result["width"] == 1920 and result["fps"] == 30
    assert result["tracks"] == ["video", "narration", "subtitle"]
    assert result["draft_file"] is None
    assert result["shots"][0]["push_pull"]["to"] == 1.08
    assert result["shots"][0]["punch_in"]["scale_delta"] == 0.04
    assert result["shots"][0]["punch_out"]["scale_delta"] == 0.02
    assert result["total_duration_sec"] == 16


def test_long_draft_plan_gap():
    with pytest.raises(CapabilityError):
        build_long_draft_plan({"title": "x", "shots": [{"duration_sec": 8, "start_sec": 5}]})


def test_long_capabilities_registered():
    assert get_capability("story.five_segment_long") is not None
    assert get_capability("story.youtube_long_board") is not None
    assert get_capability("edit.jianying_draft_long_plan") is not None
    # Short line must still be registered and untouched.
    assert get_capability("story.five_segment_short") is not None
    assert get_capability("story.audio_first_board") is not None
    assert get_capability("edit.jianying_draft_plan") is not None
