"""Tests for pipeline.code_studio_workflow: six gated steps plus orchestration."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from hevi.capabilities.code_studio_workflow import (
    build_beat_grid,
    build_contact_sheet,
    check_beat_alignment,
    check_eye_landing,
    check_motion_weight,
    check_no_hard_crop,
    classify_shot_feasibility,
    code_render_tier_status,
    confirm_style_note,
    finalize_project_folder,
    frame_state,
    manim_status,
    render_single_frame,
    rerender_segments,
    resume_project,
    review_contact_sheet,
    run_workflow_step,
    sample_layouts,
    triage_top3,
    validate_brief,
    validate_shot_table,
    validate_style_note,
    workflow_status,
)
from hevi.capabilities.errors import CapabilityError

# ---------------------------------------------------------------- fixtures


def _brief(**overrides):
    brief = {
        "title": "Demo",
        "memory_point": "One line people remember.",
        "platform": {"aspect": "9:16", "duration_sec": 30},
        "real_assets": [
            {"kind": "logo", "ref": "assets/logo.png"},
            {"kind": "interface_screenshot", "ref": "assets/ui.png"},
            {"kind": "data", "ref": "assets/data.json"},
            {"kind": "music", "ref": "assets/music.mp3"},
        ],
        "requires_real_assets": ["logo", "interface_screenshot", "data"],
        "unwanted": ["stock footage"],
        "red_lines": "界面数据一律用真的，缺了停下问，不准自画自编。",
        "deliverables": ["film.mp4", "cover.png"],
        "facts": ["The city opened its first line in 1990."],
        "creative_freedom": ["Order of the three eras may change."],
    }
    brief.update(overrides)
    return brief


def _style_note(**overrides):
    note = {
        "colors": ["#101418", "#F5F2EA"],
        "description": "Dark blue-grey ground, paper-white titles.",
        "typography": {"title_px": 72, "body_px": 28},
        "first_glance": "The big year number, centre left.",
        "avg_shot_change_sec": 3.0,
        "motion": "干脆",
        "texture": "颗粒",
        "originality_declaration": "学感觉不照搬人物 Logo 文案，一切素材自写。",
    }
    note.update(overrides)
    return note


def _shot_table():
    return [
        {"id": "s1", "start_sec": 0, "end_sec": 5,
         "start_frame": "Year number fills the frame.",
         "end_frame": "Map line appears.",
         "reason": "Sets the era before any claim is made.",
         "narration": {"text": "1990.", "start_sec": 0, "end_sec": 5}},
        {"id": "s2", "start_sec": 5, "end_sec": 10,
         "start_frame": "Map line appears.",
         "end_frame": "First station opens.",
         "reason": "Shows the first line opening.",
         "narration": "The first line opens."},
    ]


def _layout():
    return sample_layouts()["16:9"]


# ---------------------------------------------------------------- step 1


def test_brief_valid_passes():
    report = validate_brief(_brief())
    assert report["ok"] is True
    assert report["missing_assets"] == []


def test_brief_without_real_material_refuses_to_start():
    report = validate_brief(_brief(real_assets=[]))
    assert report["ok"] is False
    assert any("real_assets" in p for p in report["problems"])


def test_brief_missing_declared_kind_names_the_kind():
    brief = _brief(real_assets=[{"kind": "logo", "ref": "assets/logo.png"}])
    report = validate_brief(brief)
    assert report["ok"] is False
    assert "interface_screenshot" in report["missing_assets"]
    assert any("interface_screenshot" in p for p in report["problems"])


def test_brief_mixed_facts_and_freedom_fails():
    brief = _brief(facts=["Same line."], creative_freedom=["Same line."])
    report = validate_brief(brief)
    assert report["ok"] is False
    assert any("mixed" in p or "identical" in p for p in report["problems"])


def test_brief_missing_red_line_element_fails():
    report = validate_brief(_brief(red_lines="界面数据一律用真的。"))
    assert report["ok"] is False
    assert any("red_lines" in p for p in report["problems"])


# ---------------------------------------------------------------- step 2


def test_style_note_valid_passes():
    assert validate_style_note(_style_note())["ok"] is True


def test_style_note_without_colour_codes_fails():
    note = _style_note(colors=["#101418"])
    report = validate_style_note(note)
    assert report["ok"] is False
    assert any("colors" in p for p in report["problems"])


def test_style_note_vague_wording_fails():
    note = _style_note(description="整体很有高级感，氛围很棒。")
    assert validate_style_note(note)["ok"] is False


def test_style_note_missing_originality_declaration_fails():
    note = _style_note(originality_declaration="参考了几部好片子。")
    assert validate_style_note(note)["ok"] is False


def test_style_note_title_must_exceed_body_size():
    note = _style_note(typography={"title_px": 28, "body_px": 28})
    assert validate_style_note(note)["ok"] is False


def test_confirm_style_note_requires_exact_true():
    report = validate_style_note(_style_note())
    assert confirm_style_note(report, True)["confirmed"] is True
    assert confirm_style_note(report, "true")["confirmed"] is False
    assert confirm_style_note(report, 1)["confirmed"] is False
    assert confirm_style_note(report, None)["confirmed"] is False
    assert confirm_style_note({"ok": False, "problems": ["x"]}, True)["confirmed"] is False


# ---------------------------------------------------------------- step 3


def test_shot_table_valid_passes_with_no_cuttable():
    report = validate_shot_table(_shot_table())
    assert report["ok"] is True
    assert report["cuttable"] == []
    assert report["total_duration_sec"] == 10


def test_shot_table_reasonless_segment_is_cuttable_not_fatal():
    table = _shot_table()
    table[1]["reason"] = ""
    report = validate_shot_table(table)
    assert report["ok"] is True
    assert [c["segment_id"] for c in report["cuttable"]] == ["s2"]


def test_shot_table_vague_reason_is_cuttable():
    table = _shot_table()
    table[0]["reason"] = "好看"
    report = validate_shot_table(table)
    assert report["ok"] is True
    assert [c["segment_id"] for c in report["cuttable"]] == ["s1"]


def test_shot_table_misaligned_narration_fails():
    table = _shot_table()
    table[0]["narration"] = {"text": "1990.", "start_sec": 1, "end_sec": 5}
    assert validate_shot_table(table)["ok"] is False


def test_shot_table_gap_without_intent_fails_and_gap_with_intent_passes():
    table = _shot_table()
    table[1]["start_sec"] = 7
    table[1]["end_sec"] = 12
    assert validate_shot_table(table)["ok"] is False
    table[1]["gap_intent"] = "Black beat before the opening."
    assert validate_shot_table(table)["ok"] is True


def test_shot_table_overlap_fails():
    table = _shot_table()
    table[1]["start_sec"] = 4
    assert validate_shot_table(table)["ok"] is False


# ---------------------------------------------------------------- step 4


def test_beat_grid_is_planned_not_measured():
    grid = build_beat_grid(120, 0.0, 2.0)
    assert grid["beats"] == [0.0, 0.5, 1.0, 1.5, 2.0]
    assert grid["measured_from_audio"] is False
    assert grid["beat_basis"] == "planned_not_measured"


def test_beat_grid_rejects_non_positive_bpm():
    with pytest.raises(CapabilityError, match="bpm"):
        build_beat_grid(0, 0.0, 2.0)


def test_beat_alignment_on_beats_passes_both_modes():
    grid = build_beat_grid(120, 0.0, 4.0)
    events = [{"id": "cut1", "time_sec": 1.0, "kind": "cut"},
              {"id": "sfx1", "time_sec": 2.5, "kind": "sfx"}]
    for mode in ("music_first", "music_last"):
        report = check_beat_alignment(events, grid, tolerance=0.05, mode=mode)
        assert report["ok"] is True
        assert report["mode"] == mode


def test_beat_alignment_off_beat_fails_and_names_event():
    grid = build_beat_grid(120, 0.0, 4.0)
    events = [{"id": "cut1", "time_sec": 1.2, "kind": "cut"}]
    report = check_beat_alignment(events, grid, tolerance=0.05)
    assert report["ok"] is False
    assert report["misaligned"][0]["event_id"] == "cut1"
    assert report["misaligned"][0]["deviation_sec"] == pytest.approx(0.2)


# ---------------------------------------------------------------- step 5


def test_frame_state_deterministic_and_time_dependent():
    layout = _layout()
    first = frame_state(0.5, layout)
    second = frame_state(0.5, layout)
    assert first == second
    assert frame_state(0.0, layout)["elements"][0]["x"] == pytest.approx(120)


def test_frame_state_interpolates_moves():
    layout = _layout()
    layout["elements"][0]["moves"] = [
        {"from_t": 0.0, "to_t": 1.0, "from_x": 0, "to_x": 100,
         "from_opacity": 0, "to_opacity": 1}]
    assert frame_state(0.5, layout)["elements"][0]["x"] == pytest.approx(50)
    assert frame_state(0.5, layout)["elements"][0]["opacity"] == pytest.approx(0.5)
    assert frame_state(2.0, layout)["elements"][0]["x"] == pytest.approx(100)


def test_render_single_frame_deterministic_hash(tmp_path: Path):
    layout = _layout()
    first = render_single_frame(0.5, layout)
    second = render_single_frame(0.5, layout)
    assert first["sha256"] == second["sha256"]
    assert len(first["sha256"]) == 64
    out = tmp_path / "frame.png"
    written = render_single_frame(0.5, layout, out_path=out)
    assert out.is_file()
    assert written["sha256"] == first["sha256"]


def test_rerender_segments_reuses_unchanged_hashes():
    previous = [{"id": "a", "hash": "aaa"}, {"id": "b", "hash": "bbb"}, {"id": "c", "hash": "ccc"}]
    calls = []

    def render_fn(row):
        calls.append(row["id"])
        return {"sha256": "new-" + row["id"]}

    report = rerender_segments(["b"], previous, render_fn)
    assert report["rerendered"] == ["b"]
    assert report["reused"] == ["a", "c"]
    assert calls == ["b"]
    by_id = {row["id"]: row for row in report["segments"]}
    assert by_id["a"]["hash"] == "aaa"
    assert by_id["b"]["hash"] == "new-b"


def test_rerender_unknown_segment_raises():
    with pytest.raises(CapabilityError, match="not in the previous manifest"):
        rerender_segments(["zzz"], [{"id": "a", "hash": "aaa"}], lambda row: "x")


def test_motion_weight_small_fast_large_settle_text_hold():
    moves = [
        {"element_id": "btn", "kind": "button", "duration_sec": 0.2},
        {"element_id": "panel", "kind": "panel", "duration_sec": 0.6, "settle_ms": 120},
        {"element_id": "title", "kind": "text", "duration_sec": 0.4,
         "text": "十二个字十二个字", "hold_sec": 2.0},
    ]
    report = check_motion_weight(moves)
    assert report["ok"] is True
    assert "max(1.0, chars / 8.0)" in report["limits"]["formula"]
    bad = check_motion_weight([
        {"element_id": "btn", "kind": "button", "duration_sec": 0.9},
        {"element_id": "panel", "kind": "panel", "duration_sec": 0.6, "settle_ms": 0},
        {"element_id": "title", "kind": "text", "text": "二十个字的标题文字二十个字", "hold_sec": 0.5},
    ])
    assert bad["ok"] is False
    assert len(bad["problems"]) == 3


def test_eye_landing_missing_target_fails():
    assert check_eye_landing([{"id": "s1", "gaze_target": "year number"}])["ok"] is True
    report = check_eye_landing([{"id": "s1"}, {"id": "s2", "gaze_target": "map"}])
    assert report["ok"] is False
    assert report["missing"] == ["s1"]


def test_no_hard_crop_sample_layouts_pass_and_scaled_copy_fails():
    assert check_no_hard_crop(sample_layouts())["ok"] is True
    base = sample_layouts()["16:9"]
    scaled = {
        "16:9": base,
        "9:16": {"aspect": "9:16", "width": 1080, "height": 1920, "elements": [
            {"id": "title", "kind": "text",
             "x": 120 / 1920 * 1080, "y": 140 / 1080 * 1920,
             "w": 900 / 1920 * 1080, "h": 120 / 1080 * 1920,
             "font_size": 72 / 1080 * 1920, "color": "#F5F2EA", "text": "标题"},
            {"id": "panel", "kind": "panel",
             "x": 120 / 1920 * 1080, "y": 320 / 1080 * 1920,
             "w": 760 / 1920 * 1080, "h": 420 / 1080 * 1920,
             "font_size": 28 / 1080 * 1920, "color": "#2A7FFF", "text": "副标题"},
            {"id": "button", "kind": "button",
             "x": 120 / 1920 * 1080, "y": 800 / 1080 * 1920,
             "w": 200 / 1920 * 1080, "h": 64 / 1080 * 1920,
             "font_size": 28 / 1080 * 1920, "color": "#FFC53D", "text": "开始"},
        ]},
    }
    assert check_no_hard_crop(scaled)["ok"] is False


def test_feasibility_routes_live_action_away_from_code():
    blocked = classify_shot_feasibility({"id": "s1", "kind": "live_action"})
    assert blocked["route"] == "live_or_video_model"
    assert blocked["code_render_ok"] is False
    assert classify_shot_feasibility({"id": "s2", "kind": "code"})["code_render_ok"] is True
    assert classify_shot_feasibility(
        {"id": "s3", "requires": ["complex_human_motion"]})["route"] == "live_or_video_model"


def test_code_render_has_no_vertical_tier():
    status = code_render_tier_status()
    assert status["vertical_tier"] is None
    assert status["gap"] is not None
    assert "uhd_2160p60" in status["tiers"]


def test_manim_is_not_connected_without_injection():
    status = manim_status()
    assert status["connected"] is False
    assert status["status"] == "not_connected"


# ---------------------------------------------------------------- step 6


def _frames():
    return [
        {"t_sec": 0.0, "image": Image.new("RGB", (320, 180), (20, 30, 40))},
        {"t_sec": 5.0, "image": Image.new("RGB", (320, 180), (200, 30, 40))},
        {"t_sec": 9.0, "image": Image.new("RGB", (320, 180), (30, 180, 40))},
    ]


def test_contact_sheet_labels_and_hash(tmp_path: Path):
    sheet = build_contact_sheet(_frames(), out_path=tmp_path / "sheet.png")
    assert sheet["frame_count"] == 3
    assert sheet["times"] == [0.0, 5.0, 9.0]
    assert (tmp_path / "sheet.png").is_file()
    again = build_contact_sheet(_frames())
    assert again["sha256"] == sheet["sha256"]


def test_contact_sheet_empty_raises():
    with pytest.raises(CapabilityError, match="no frames"):
        build_contact_sheet([])


def _review_checks():
    return {
        "phone_projection": {"title_font_size_px": 72, "frame_width_px": 1080,
                             "phone_width_px": 390},
        "real_data": {"brief_assets": [{"ref": "assets/ui.png"}],
                      "used_refs": ["assets/ui.png"]},
        "transition": {"frame_deltas": [0.10, 0.20]},
        "hook": {"hook_declared": "Year number fills the frame.", "first_change_sec": 0.5},
        "cover": {"title_present": True, "title_color": "#FFFFFF", "background_color": "#101418"},
    }


def test_review_contact_sheet_all_five_pass():
    report = review_contact_sheet(_review_checks())
    assert report["ok"] is True
    assert set(report["checks"]) == {"phone_legibility", "real_data", "transition", "hook", "cover"}


def test_review_contact_sheet_fake_data_and_missing_cover_fail():
    checks = _review_checks()
    checks["real_data"] = {"brief_assets": [{"ref": "assets/ui.png"}],
                           "used_refs": ["assets/invented.png"]}
    checks["cover"] = {"title_present": False}
    report = review_contact_sheet(checks)
    assert report["ok"] is False
    assert "real_data" in report["failures"]
    assert "cover" in report["failures"]


def test_review_contact_sheet_unmeasured_transition_is_undetermined_not_pass():
    checks = _review_checks()
    del checks["transition"]
    report = review_contact_sheet(checks)
    assert report["ok"] is False
    assert "transition" in report["undetermined"]


def test_triage_top3_keeps_three_and_defers_rest():
    issues = [
        {"severity": "low", "time_sec": 1, "fix": "f1", "description": "d1"},
        {"severity": "critical", "time_sec": 9, "fix": "f2", "description": "d2"},
        {"severity": "medium", "time_sec": 3, "fix": "f3", "description": "d3"},
        {"severity": "high", "time_sec": 5, "fix": "f4", "description": "d4"},
        {"severity": "high", "time_sec": 2, "fix": "f5", "description": "d5"},
    ]
    report = triage_top3(issues)
    assert [item["description"] for item in report["top3"]] == ["d2", "d5", "d4"]
    assert len(report["deferred"]) == 2
    assert all("time_sec" in item and "fix" in item for item in report["top3"])


def test_finalize_and_resume_folder(tmp_path: Path):
    root = tmp_path / "proj"
    (root / "assets").mkdir(parents=True)
    (root / "assets" / "ui.png").write_bytes(b"x")
    (root / "source").mkdir()
    (root / "source" / "code.py").write_text("x", encoding="utf-8")
    (root / "checks").mkdir()
    (root / "checks" / "review.json").write_text("{}", encoding="utf-8")
    (root / "brief.json").write_text("{}", encoding="utf-8")
    (root / "style_note.json").write_text("{}", encoding="utf-8")
    (root / "shot_table.json").write_text("{}", encoding="utf-8")
    (root / "beat_grid.json").write_text("{}", encoding="utf-8")
    (root / "frame_report.json").write_text("{}", encoding="utf-8")
    report = finalize_project_folder(root)
    assert report["ok"] is False
    assert report["missing"] == ["film"]
    (root / "film.mp4").write_bytes(b"x")
    assert finalize_project_folder(root)["ok"] is True
    resumed = resume_project(root)
    assert resumed["source"] == "folder_inference"
    assert resumed["current_step"] == 1
    assert resumed["completed_steps"] == [1, 2, 3, 4, 5, 6]


# ---------------------------------------------------------------- orchestrator


def _run_all_steps(root: Path):
    first = run_workflow_step(root, 1, {"brief": _brief()}, confirmation=True)
    assert first["status"] == "done", first
    second = run_workflow_step(root, 2, {"style_note": _style_note()}, confirmation=True)
    assert second["status"] == "done", second
    third = run_workflow_step(root, 3, {"shot_table": _shot_table()}, confirmation=True)
    assert third["status"] == "done", third
    fourth = run_workflow_step(
        root, 4,
        {"bpm": 120, "duration_sec": 10, "mode": "music_first",
         "events": [{"id": "c1", "time_sec": 5.0, "kind": "cut"}]},
        confirmation=True)
    assert fourth["status"] == "done", fourth
    fifth = run_workflow_step(
        root, 5,
        {"layouts": sample_layouts(), "t": 0.0,
         "moves": [{"element_id": "btn", "kind": "button", "duration_sec": 0.2}],
         "eye_items": [{"id": "s1", "gaze_target": "year number"}],
         "source_code": "x = 1\n"},
        confirmation=True)
    assert fifth["status"] == "done", fifth
    return fifth


def test_orchestrator_unconfirmed_step_blocks_next(tmp_path: Path):
    root = tmp_path / "proj"
    first = run_workflow_step(root, 1, {"brief": _brief()}, confirmation=False)
    assert first["status"] == "awaiting_confirmation"
    assert first["ok"] is False
    blocked = run_workflow_step(root, 2, {"style_note": _style_note()}, confirmation=True)
    assert blocked["ok"] is False
    assert blocked["blocked_by"] == 1
    assert workflow_status(root)["current_step"] == 1


def test_orchestrator_string_true_is_not_confirmation(tmp_path: Path):
    root = tmp_path / "proj"
    first = run_workflow_step(root, 1, {"brief": _brief()}, confirmation="true")
    assert first["status"] == "awaiting_confirmation"
    assert workflow_status(root)["current_step"] == 1


def test_orchestrator_full_run_and_resume(tmp_path: Path):
    root = tmp_path / "proj"
    _run_all_steps(root)
    (root / "assets").mkdir(parents=True, exist_ok=True)
    (root / "assets" / "ui.png").write_bytes(b"x")
    (root / "film.mp4").write_bytes(b"x")
    sixth = run_workflow_step(
        root, 6,
        {"checks": _review_checks(), "issues": [],
         "frames": _frames()},
        confirmation=True)
    assert sixth["status"] == "done", sixth
    status = workflow_status(root)
    assert status["done_steps"] == [1, 2, 3, 4, 5, 6]
    assert status["current_step"] is None
    resumed = resume_project(root)
    assert resumed["source"] == "manifest"
    assert resumed["completed_steps"] == [1, 2, 3, 4, 5, 6]
    assert resumed["current_step"] is None
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    assert "code_studio_workflow" in manifest
    assert "stages" in manifest
    assert manifest["stages"]["review"]["status"] == "done"


def test_orchestrator_failed_validation_does_not_advance(tmp_path: Path):
    root = tmp_path / "proj"
    first = run_workflow_step(root, 1, {"brief": _brief(real_assets=[])}, confirmation=True)
    assert first["status"] == "failed"
    blocked = run_workflow_step(root, 2, {"style_note": _style_note()}, confirmation=True)
    assert blocked["blocked_by"] == 1


def test_orchestrator_rejects_step_out_of_range(tmp_path: Path):
    with pytest.raises(CapabilityError, match="step must be 1-6"):
        run_workflow_step(tmp_path / "proj", 7, {}, confirmation=True)
