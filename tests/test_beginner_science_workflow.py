"""Tests for pipeline.beginner_science_workflow (self-authored fixtures)."""

from __future__ import annotations

import json

import pytest

from hevi.capabilities.beginner_science_workflow import (
    build_narration_segments,
    check_motion_chart,
    check_music_alignment,
    check_pause_marks,
    check_roll_pattern,
    check_template_use,
    gate_full_production,
    gate_sample_first,
    list_templates,
    record_style_analysis,
    regenerate_row,
    validate_seven_column_table,
)
from hevi.capabilities.code_studio_workflow import build_beat_grid
from hevi.capabilities.registry import get as registry_get


def _row(**overrides):
    row = {
        "id": "r1",
        "start_sec": 0.0,
        "end_sec": 5.0,
        "timing_basis": "measured",
        "narration": "这是一句科普口播。",
        "emotion": "平静",
        "picture": "一张示意图",
        "motion": "数字从零增长到一百",
        "source": "某公开科普资料",
        "material": ["code/shot_01.py"],
        "roll": "B",
    }
    row.update(overrides)
    return row


def _table(tmp_path, **row_overrides):
    (tmp_path / "code").mkdir(exist_ok=True)
    (tmp_path / "code" / "shot_01.py").write_text("x = 1\n", encoding="utf-8")
    return {"rows": [_row(**row_overrides)]}


def test_valid_table_passes(tmp_path):
    report = validate_seven_column_table(_table(tmp_path), project_root=tmp_path)
    assert report["ok"] is True
    assert report["timing_basis"] == "measured"
    assert report["broadcast_blocked"] is False
    assert report["material_status"] == "checked"


def test_mixed_timing_basis_fails(tmp_path):
    table = _table(tmp_path)
    table["rows"].append(
        _row(id="r2", start_sec=5.0, end_sec=10.0, timing_basis="estimated")
    )
    report = validate_seven_column_table(table, project_root=tmp_path)
    assert report["ok"] is False
    assert any("timing_basis" in p for p in report["problems"])


def test_missing_source_marks_unverified_and_blocks(tmp_path):
    table = _table(tmp_path, source="")
    report = validate_seven_column_table(table, project_root=tmp_path)
    assert report["ok"] is False
    assert report["unverified_rows"] == [{"row_id": "r1", "reason": "no information source"}]
    assert report["broadcast_blocked"] is True


def test_fictional_material_fails(tmp_path):
    table = _table(tmp_path, material=["code/does_not_exist.py"])
    report = validate_seven_column_table(table, project_root=tmp_path)
    assert report["ok"] is False
    assert report["missing_materials"]
    assert any("does_not_exist" in p for p in report["problems"])


def test_material_without_project_root_is_unchecked(tmp_path):
    report = validate_seven_column_table(_table(tmp_path), project_root=None)
    assert report["ok"] is False
    assert report["material_status"] == "unchecked"


def test_two_sentences_in_one_row_fails(tmp_path):
    table = _table(tmp_path, narration="第一句。第二句。")
    report = validate_seven_column_table(table, project_root=tmp_path)
    assert report["ok"] is False
    assert any("more than one sentence" in p for p in report["problems"])


def test_pause_marks_out_of_range_warn(tmp_path):
    warnings = check_pause_marks(
        [{"kind": "intra_sentence", "seconds": 0.5}], "一句口播。"
    )
    assert warnings
    warnings = check_pause_marks(
        [{"kind": "intra_sentence", "seconds": 0.15},
         {"kind": "between_sentences", "seconds": 0.35}],
        "一句口播。",
    )
    assert warnings == []
    warnings = check_pause_marks([], "一句[pause=0.9]口播。")
    assert warnings


def test_mixed_emotion_in_one_row_fails(tmp_path):
    table = _table(tmp_path, emotion="平静转激昂")
    report = validate_seven_column_table(table, project_root=tmp_path)
    assert report["ok"] is False
    assert any("emotion" in p for p in report["problems"])


def _make_material(tmp_path):
    (tmp_path / "code").mkdir(exist_ok=True)
    (tmp_path / "code" / "shot_01.py").write_text("x = 1\n", encoding="utf-8")


def test_narration_segments_split_on_emotion_and_size(tmp_path):
    _make_material(tmp_path)
    rows = [
        _row(id="a", start_sec=0.0, end_sec=5.0, emotion="平静"),
        _row(id="b", start_sec=5.0, end_sec=10.0, emotion="平静"),
        _row(id="c", start_sec=10.0, end_sec=15.0, emotion="平静"),
        _row(id="d", start_sec=15.0, end_sec=20.0, emotion="激昂"),
    ]
    result = build_narration_segments({"rows": rows}, project_root=tmp_path)
    assert result["ok"] is True
    assert result["tts_status"] == "not_connected"
    assert [s["row_ids"] for s in result["segments"]] == [["a", "b", "c"], ["d"]]
    assert all(s["single_row_replaceable"] for s in result["segments"])


def test_regenerate_row_only_replaces_one_row(tmp_path):
    _make_material(tmp_path)
    rows = [
        _row(id="a", start_sec=0.0, end_sec=5.0, narration="第一句。"),
        _row(id="b", start_sec=5.0, end_sec=10.0, narration="第二句。"),
    ]
    result = regenerate_row(
        {"rows": rows}, "b", new_narration="第二句改后。", project_root=tmp_path
    )
    assert result["ok"] is True
    assert result["replaced_row_id"] == "b"
    assert result["unchanged_row_ids"] == ["a"]
    assert "第二句改后" in result["segments"][0]["text"]


def test_sample_gate_refuses_without_strict_confirmation(tmp_path):
    table = _table(tmp_path)
    for confirmed in (None, "true", 1):
        report = gate_sample_first(table, confirmed=confirmed, project_root=tmp_path)
        assert report["allowed"] is False
    report = gate_sample_first(table, confirmed=True, project_root=tmp_path)
    assert report["allowed"] is True
    assert report["sample_checks"]["picture_audio_alignment"] == "requires_human_confirmation"


def test_full_gate_refuses_without_sample_confirmation(tmp_path):
    report = gate_full_production(
        _table(tmp_path), sample_confirmed=False, project_root=tmp_path
    )
    assert report["allowed"] is False
    report = gate_full_production(
        _table(tmp_path), sample_confirmed=True, project_root=tmp_path
    )
    assert report["allowed"] is True


def test_roll_pattern_flags_long_b_run():
    rows = [_row(id=f"r{i}", roll="B") for i in range(5)]
    report = check_roll_pattern({"rows": rows})
    assert report["needs_transition"] is True
    assert len(report["transition_prompts"]) == 2
    report = check_roll_pattern({"rows": rows}, max_consecutive_b=5)
    assert report["needs_transition"] is False


def test_template_registry_reports_unconnected_as_reference_only():
    templates = list_templates()
    by_name = {t["name"]: t for t in templates}
    assert by_name["lemo-opuscar"]["status"] == "integrated"
    assert by_name["lemo-opuscar"]["verified_count"] == 59
    assert by_name["handraw-style"]["status"] == "integrated"
    assert by_name["mg-styles-15"]["status"] == "reference_only"
    assert by_name["mg-styles-15"]["hevi_capability"] is None
    assert by_name["vox-director"]["status"] == "reference_only"
    assert by_name["sweety-handdraw-video"]["status"] == "reference_only"


def test_template_use_without_changes_warns():
    report = check_template_use("lemo-opuscar")
    assert report["ok"] is True
    assert any("without recorded changes" in w for w in report["warnings"])
    report = check_template_use(
        "lemo-opuscar", customized=True, changes=["recoloured", "new transition"]
    )
    assert report["warnings"] == []
    report = check_template_use("mg-styles-15", customized=True)
    assert any("reference_only" in w for w in report["warnings"])


def test_style_analysis_refuses_copied_material():
    report = record_style_analysis("some creator", analysis_notes="learned pacing")
    assert report["ok"] is True
    assert report["record"]["method_only"] is True
    report = record_style_analysis(
        "some creator", analysis_notes="x", copied_text="their prompt text"
    )
    assert report["ok"] is False


def test_music_alignment_rejects_mid_sentence_and_off_beat():
    grid = build_beat_grid(120, duration_sec=10.0, mode="music_first")
    report = check_music_alignment(
        [{"kind": "mid_sentence", "time_sec": 1.0}], grid
    )
    assert report["ok"] is False
    assert any("inside a sentence" in p for p in report["problems"])
    report = check_music_alignment(
        [{"kind": "section_change", "time_sec": 0.5}], grid
    )
    assert report["ok"] is True
    assert report["beat_basis"] == "planned_not_measured"
    report = check_music_alignment(
        [{"kind": "section_change", "time_sec": 0.3}], grid
    )
    assert report["ok"] is False


def test_motion_chart_reuse():
    chart = {
        "thesis": {
            "visual_metaphor": "a counter",
            "from_state": "zero",
            "to_state": "one hundred",
            "claim": "numbers carry the point",
        },
        "beats": [
            {
                "start_sec": 0.0,
                "end_sec": 5.0,
                "action": "count up",
                "mover": "digits",
                "state_change": "0 to 100",
                "camera": "static",
                "change_kind": "grow",
                "text": "count",
                "asset": "digits",
            }
        ],
    }
    report = check_motion_chart(chart)
    assert "chart_report" in report
    assert report["chart_report"]["capability"] == "video.motion_beat_chart"


def test_capability_registered():
    assert registry_get("pipeline.beginner_science_workflow") is not None


def test_render_report_is_json(tmp_path):
    from hevi.capabilities.beginner_science_workflow import _render

    result = _render(
        {"action": "templates"},
        tmp_path,
        duration=0.0,
        aspect="16:9",
        seed=1,
    )
    payload = json.loads((tmp_path / "beginner_science_workflow_report.json").read_text(encoding="utf-8"))
    assert payload["templates"]
    assert result.sha256
