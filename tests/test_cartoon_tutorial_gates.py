"""Tests for the 3D cartoon tutorial P0 gates (clean-room, method only)."""

from __future__ import annotations

import pytest

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.feedback_discipline import check_feedback
from hevi.capabilities.project_style_sheet import (
    check_render_readiness,
    validate_style_sheet,
)
from hevi.capabilities.voice_first_gate import check_voice_first


def _sheet(**overrides):
    sheet = {
        "schema_version": 1,
        "sheet_id": "toon-a",
        "version": 3,
        "proportions": {"head_height_ratio": 0.5},
        "outline": {"stroke_width_px": 6},
        "palette": {"colors": ["#111111", "#EEEEEE"]},
        "lighting": {"key_light_intensity": 1.2},
        "material": {"roughness": 0.6},
        "motion": {"walk_cycle_sec": 0.8, "arm_swing_deg": 30},
    }
    sheet.update(overrides)
    return sheet


def _voice_plan(**overrides):
    plan = {
        "total_duration_sec": 4.0,
        "shots": [
            {"id": "s1", "start_sec": 0.0, "end_sec": 2.0, "audio_segment_id": "a1"},
            {"id": "s2", "start_sec": 2.0, "end_sec": 4.0, "audio_segment_id": "a1"},
        ],
        "audio_segments": [
            {
                "id": "a1",
                "duration_sec": 4.0,
                "words": [
                    {"word": "hello", "start_sec": 0.0, "end_sec": 1.0},
                    {"word": "world", "start_sec": 1.0, "end_sec": 2.0},
                    {"word": "again", "start_sec": 2.0, "end_sec": 4.0},
                ],
            }
        ],
    }
    plan.update(overrides)
    return plan


# --- qa.feedback_discipline ---


def test_feedback_valid_two_items_lists_frozen():
    report = check_feedback(
        {
            "items": [
                {"at_sec": 2.0, "part": "head", "expected": "head is half the height"},
                {"at_sec": 3.0, "part": "left arm", "expected": "arm swings with the walk"},
            ],
            "scope": ["head", "left arm", "cape", "background"],
        }
    )
    assert report["ok"] is True
    assert report["frozen_items"] == ["cape", "background"]
    assert report["scope_undeclared"] is False


def test_feedback_missing_expected_fails():
    report = check_feedback(
        {"items": [{"at_sec": 2.0, "part": "head"}]}
    )
    assert report["ok"] is False
    assert any("expected" in p for p in report["problems"])


def test_feedback_missing_timestamp_fails():
    report = check_feedback(
        {"items": [{"part": "head", "expected": "head is half the height"}]}
    )
    assert report["ok"] is False
    assert any("timestamp" in p for p in report["problems"])


def test_feedback_missing_part_fails():
    report = check_feedback(
        {"items": [{"at_sec": 2.0, "expected": "head is half the height"}]}
    )
    assert report["ok"] is False
    assert any("part" in p for p in report["problems"])


def test_feedback_frame_counts_as_timestamp():
    report = check_feedback(
        {"items": [{"frame": 60, "part": "head", "expected": "head is half the height"}]}
    )
    assert report["ok"] is True


def test_feedback_three_items_fails():
    report = check_feedback(
        {
            "items": [
                {"at_sec": 1.0, "part": "head", "expected": "bigger"},
                {"at_sec": 2.0, "part": "arm", "expected": "swings"},
                {"at_sec": 3.0, "part": "cape", "expected": "redder"},
            ]
        }
    )
    assert report["ok"] is False
    assert any("exceeds" in p for p in report["problems"])


def test_feedback_not_an_object_raises():
    with pytest.raises(CapabilityError):
        check_feedback("fix it")


# --- pipeline.project_style_sheet ---


def test_style_sheet_valid():
    report = validate_style_sheet(_sheet())
    assert report["ok"] is True
    assert report["colours"] == ["#111111", "#eeeeee"]


def test_style_sheet_missing_proportion_number_fails():
    report = validate_style_sheet(_sheet(proportions={"note": "big head"}))
    assert report["ok"] is False
    assert any("proportions" in p for p in report["problems"])


def test_style_sheet_missing_palette_fails():
    report = validate_style_sheet(_sheet(palette={"colors": ["#111111"]}))
    assert report["ok"] is False
    assert any("palette" in p for p in report["problems"])


def test_style_sheet_prose_lighting_fails():
    report = validate_style_sheet(_sheet(lighting={"feel": "soft"}))
    assert report["ok"] is False
    assert any("lighting" in p for p in report["problems"])


def test_readiness_fresh_sample_passes():
    report = check_render_readiness(
        _sheet(),
        sample_confirmation={"version": 3, "confirmed": True, "sample_duration_sec": 4.0},
    )
    assert report["ok"] is True
    assert report["stale"] is False


def test_readiness_stale_version_fails():
    report = check_render_readiness(
        _sheet(),
        sample_confirmation={"version": 2, "confirmed": True, "sample_duration_sec": 4.0},
    )
    assert report["ok"] is False
    assert report["stale"] is True
    assert any("stale" in p for p in report["problems"])


def test_readiness_missing_confirmation_fails():
    report = check_render_readiness(_sheet(), sample_confirmation=None)
    assert report["ok"] is False


def test_readiness_string_true_is_not_confirmation():
    report = check_render_readiness(
        _sheet(),
        sample_confirmation={"version": 3, "confirmed": "true", "sample_duration_sec": 4.0},
    )
    assert report["ok"] is False


def test_readiness_long_sample_fails():
    report = check_render_readiness(
        _sheet(),
        sample_confirmation={"version": 3, "confirmed": True, "sample_duration_sec": 6.0},
    )
    assert report["ok"] is False


# --- qa.voice_first_gate ---


def test_voice_first_valid_plan_passes_planned_not_measured():
    report = check_voice_first(_voice_plan())
    assert report["ok"] is True
    assert report["alignment_basis"] == "planned_not_measured"
    assert report["measured"] is False
    assert "a1" in report["word_contracts"]


def test_voice_first_no_audio_fails():
    report = check_voice_first({"shots": [{"id": "s1", "end_sec": 2.0, "audio_segment_id": "a1"}], "audio_segments": []})
    assert report["ok"] is False
    assert any("audio_segments" in p for p in report["problems"])


def test_voice_first_shot_without_audio_id_fails():
    plan = _voice_plan(shots=[{"id": "s1", "start_sec": 0.0, "end_sec": 4.0}])
    report = check_voice_first(plan)
    assert report["ok"] is False
    assert any("audio_segment_id" in p for p in report["problems"])


def test_voice_first_segment_without_word_timing_fails():
    plan = _voice_plan(
        audio_segments=[{"id": "a1", "duration_sec": 4.0}],
    )
    report = check_voice_first(plan)
    assert report["ok"] is False
    assert any("word-level" in p for p in report["problems"])


def test_voice_first_overlapping_words_fail():
    plan = _voice_plan(
        audio_segments=[
            {
                "id": "a1",
                "duration_sec": 4.0,
                "words": [
                    {"word": "hello", "start_sec": 0.0, "end_sec": 2.0},
                    {"word": "world", "start_sec": 1.0, "end_sec": 3.0},
                ],
            }
        ],
    )
    report = check_voice_first(plan)
    assert report["ok"] is False


def test_voice_first_duration_mismatch_fails():
    plan = _voice_plan(total_duration_sec=9.0)
    report = check_voice_first(plan)
    assert report["ok"] is False
    assert any("duration" in p for p in report["problems"])


def test_voice_first_not_an_object_raises():
    with pytest.raises(CapabilityError):
        check_voice_first(None)


def test_new_capabilities_registered():
    from hevi.capabilities import feedback_discipline as _fd
    from hevi.capabilities import project_style_sheet as _pss
    from hevi.capabilities import voice_first_gate as _vf

    assert _fd.register_feedback_discipline_capabilities_once() == []
    assert _pss.register_project_style_sheet_capabilities_once() == []
    assert _vf.register_voice_first_gate_capabilities_once() == []
