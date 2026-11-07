"""Offline tests for the hand-painted animation planning capabilities.

Covers the six ``animation.*`` capabilities registered by
``hevi.capabilities.handpaint_anim`` (clean-room method intake, no
upstream code or assets): guide-rule checking (pass / pending /
fail), the pure-function time/camera model (determinism, easing,
out-of-range failure), timeline continuity (overlap, undeclared gap,
declared gap, duplicate id), brush-wipe validation, render-check
plans with and without real frames, and the 11-second tuantuan demo.
No network, no paid calls, CPU only.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

import hevi.capabilities as caps
from hevi.capabilities.handpaint_anim import (
    build_demo_spec,
    build_render_check,
    check_guide,
    sample_state,
    validate_brush_wipe,
    validate_timeline,
)
from hevi.capabilities.registry import CapabilityError

NAMES = [
    "animation.guide_check",
    "animation.time_camera",
    "animation.timeline",
    "animation.brush_wipe",
    "animation.render_check",
    "animation.tuantuan_demo",
]


def _shot(sid, start, end, **kw):
    shot = {
        "shot_id": sid, "start_sec": start, "end_sec": end,
        "duration_sec": end - start, "event": f"{sid} happens",
        "motion": ["camera_hold"], "has_text": False, "text_elements": [],
    }
    shot.update(kw)
    return shot


def _plan(**kw):
    plan = {
        "medium": "handpaint_brush",
        "total_duration_sec": 8.0,
        "vision": {"description": "a painted scene", "vision_first": True},
        "shots": [_shot("s1", 0.0, 4.0), _shot("s2", 4.0, 8.0)],
        "transitions": [{"from_shot": "s1", "to_shot": "s2", "type": "brush_wipe",
                         "reason": "scene changes"}],
    }
    plan.update(kw)
    return plan


def _render(name, params, tmp_path):
    cap = caps.get(name)
    return cap.render(params, tmp_path, duration=0.0, aspect="16:9", seed=7)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_all_six_registered():
    for name in NAMES:
        assert caps.contains(name), name


def test_registration_idempotent():
    import hevi.capabilities.handpaint_anim as mod

    assert mod.register_handpaint_anim_capabilities_once() == []


# ---------------------------------------------------------------------------
# Guide check
# ---------------------------------------------------------------------------

def test_guide_pass():
    result = check_guide(_plan())
    assert result["verdict"] == "pass"
    assert all(r["status"] == "pass" for r in result["rules"])
    assert [r["id"] for r in result["rules"]] == [
        "medium_unified", "no_text", "every_shot_has_event", "audience_time",
        "picture_alive", "transition_motivated", "vision_before_code",
    ]


def test_guide_missing_evidence_is_pending_not_pass():
    plan = _plan()
    del plan["vision"]
    plan["shots"][0].pop("motion")
    result = check_guide(plan)
    by_id = {r["id"]: r["status"] for r in result["rules"]}
    assert by_id["vision_before_code"] == "pending"
    assert by_id["picture_alive"] == "pending"
    assert result["verdict"] == "pending"


def test_guide_text_violation_fails():
    plan = _plan()
    plan["shots"][1]["has_text"] = True
    plan["shots"][1]["text_elements"] = ["title card"]
    assert check_guide(plan)["verdict"] == "fail"


def test_guide_missing_transition_fails():
    plan = _plan(transitions=[])
    by_id = {r["id"]: r["status"] for r in check_guide(plan)["rules"]}
    assert by_id["transition_motivated"] == "fail"


def test_guide_unmotivated_transition_fails():
    plan = _plan(transitions=[{"from_shot": "s1", "to_shot": "s2", "type": "brush_wipe"}])
    assert check_guide(plan)["verdict"] == "fail"


def test_guide_empty_event_fails():
    plan = _plan()
    plan["shots"][0]["event"] = "   "
    assert check_guide(plan)["verdict"] == "fail"


def test_guide_total_mismatch_fails():
    plan = _plan(total_duration_sec=99.0)
    assert check_guide(plan)["verdict"] == "fail"


def test_guide_capability_roundtrip(tmp_path):
    out = _render("animation.guide_check", {"plan": _plan()}, tmp_path)
    report = json.loads((tmp_path / "guide_check.json").read_text(encoding="utf-8"))
    assert report["verdict"] == "pass"
    assert out.qa["report_json"].endswith("guide_check.json")


# ---------------------------------------------------------------------------
# Time/camera model
# ---------------------------------------------------------------------------

_SPEC = {
    "duration_sec": 4.0, "easing": "ease_in_out",
    "camera": {"from": {"x": 0.0, "y": 0.0, "zoom": 1.0},
               "to": {"x": 0.5, "y": 0.25, "zoom": 1.5}},
    "character": {"from": {"x": 0.2, "y": 0.5, "scale": 1.0},
                  "to": {"x": 0.8, "y": 0.5, "scale": 1.0}},
    "boil": {"seed": 7, "amplitude_px": 2.0, "fps": 12},
}


def test_sample_endpoints_and_determinism():
    start = sample_state(0.0, _SPEC)
    end = sample_state(4.0, _SPEC)
    assert start["camera"] == {"x": 0.0, "y": 0.0, "zoom": 1.0}
    assert end["camera"] == {"x": 0.5, "y": 0.25, "zoom": 1.5}
    assert end["character"]["x"] == 0.8
    assert sample_state(1.25, _SPEC) == sample_state(1.25, _SPEC)
    assert sample_state(1.25, _SPEC)["boil"]["frame"] == 15


def test_sample_boil_jitter_bounded_and_seeded():
    a = sample_state(1.0, _SPEC)["boil"]
    b = sample_state(1.0, {**_SPEC, "boil": {"seed": 8, "amplitude_px": 2.0, "fps": 12}})["boil"]
    assert abs(a["jitter_x_px"]) <= 2.0 and abs(a["jitter_y_px"]) <= 2.0
    assert (a["jitter_x_px"], a["jitter_y_px"]) != (b["jitter_x_px"], b["jitter_y_px"])


def test_sample_out_of_range_and_bad_easing_fail():
    with pytest.raises(CapabilityError):
        sample_state(4.5, _SPEC)
    with pytest.raises(CapabilityError):
        sample_state(-0.1, _SPEC)
    with pytest.raises(CapabilityError):
        sample_state(1.0, {**_SPEC, "easing": "bounce"})


def test_time_camera_capability(tmp_path):
    out = _render("animation.time_camera", {"spec": _SPEC, "times": [0.0, 4.0]}, tmp_path)
    payload = json.loads((tmp_path / "time_camera.json").read_text(encoding="utf-8"))
    assert len(payload["states"]) == 2
    assert payload["states"][1]["eased_progress"] == 1.0


# ---------------------------------------------------------------------------
# Timeline
# ---------------------------------------------------------------------------

def test_timeline_valid_and_loops():
    plan = {"shots": [
        _shot("s1", 0.0, 4.0, loop_count=2),
        _shot("s2", 4.0, 8.0, transition={"type": "brush_wipe", "duration_sec": 0.5}),
    ]}
    result = validate_timeline(plan)
    assert result["total_duration_sec"] == 8.0
    assert result["shot_count"] == 2


def test_timeline_overlap_fails():
    with pytest.raises(CapabilityError):
        validate_timeline({"shots": [_shot("s1", 0.0, 5.0), _shot("s2", 4.0, 8.0)]})


def test_timeline_undeclared_gap_fails():
    with pytest.raises(CapabilityError):
        validate_timeline({"shots": [_shot("s1", 0.0, 4.0), _shot("s2", 5.0, 8.0)]})


def test_timeline_declared_gap_passes():
    result = validate_timeline({"shots": [_shot("s1", 0.0, 4.0), _shot("s2", 5.0, 8.0)],
                                "gaps": [{"start_sec": 4.0, "end_sec": 5.0, "reason": "held beat"}]})
    assert result["total_duration_sec"] == 8.0


def test_timeline_duplicate_id_and_bad_loop_fail():
    with pytest.raises(CapabilityError):
        validate_timeline({"shots": [_shot("s1", 0.0, 4.0), _shot("s1", 4.0, 8.0)]})
    with pytest.raises(CapabilityError):
        validate_timeline({"shots": [_shot("s1", 0.0, 4.0, loop_count=0)]})


def test_timeline_capability(tmp_path):
    out = _render("animation.timeline", {"plan": {"shots": [_shot("s1", 0.0, 4.0)]}},
                  tmp_path)
    assert out.qa["total_duration_sec"] == 4.0


# ---------------------------------------------------------------------------
# Brush wipe
# ---------------------------------------------------------------------------

def test_brush_wipe_plan():
    plan = validate_brush_wipe({
        "direction": "left_to_right", "duration_sec": 0.6,
        "brush": {"stroke_width_px": 24, "roughness": 0.5, "seed": 7},
        "from_shot": "s1", "to_shot": "s2", "reason": "turn aside",
    })
    assert plan["phases"][-1]["coverage"] == 1.0
    assert len(plan["render_steps"]) == 3


@pytest.mark.parametrize("bad", [
    {"direction": "sideways", "duration_sec": 0.6},
    {"direction": "left_to_right", "duration_sec": 0.1},
    {"direction": "left_to_right", "duration_sec": 5.0},
    {"direction": "left_to_right", "duration_sec": 0.6,
     "brush": {"roughness": 1.5}},
])
def test_brush_wipe_invalid_fails(bad):
    with pytest.raises(CapabilityError):
        validate_brush_wipe(bad)


def test_brush_wipe_capability(tmp_path):
    _render("animation.brush_wipe",
            {"spec": {"direction": "top_to_bottom", "duration_sec": 1.0}}, tmp_path)
    assert (tmp_path / "brush_wipe_plan.json").is_file()


# ---------------------------------------------------------------------------
# Render check
# ---------------------------------------------------------------------------

def test_render_check_plan_only_no_fake_image(tmp_path):
    plan, files = build_render_check(
        [{"shot_id": "s1", "start_sec": 0.0, "end_sec": 4.0},
         {"shot_id": "s2", "start_sec": 4.0, "end_sec": 8.0}],
        crop_at={"x": 0.5, "y": 0.5, "size_px": 320, "label": "face"},
    )
    assert files is None
    assert plan["has_frames"] is False
    assert plan["contact_sheet"][0]["first"]["frame_index"] is None
    assert plan["contact_sheet"][1]["mid"]["time_sec"] == 6.0
    assert plan["crop_at"]["per_shot_mid"][0]["frame_index"] is None
    out = _render("animation.render_check",
                  {"shots": [{"shot_id": "s1", "start_sec": 0.0, "end_sec": 4.0}]}, tmp_path)
    assert not (tmp_path / "contact_sheet.png").exists()
    assert out.png is None


def test_render_check_real_frames_build_sheet(tmp_path):
    frames = tmp_path / "frames"
    frames.mkdir()
    for i in range(8):
        Image.new("RGB", (64, 36), (i * 30 % 256, 100, 50)).save(frames / f"f{i:03d}.png")
    out = _render("animation.render_check",
                  {"shots": [{"shot_id": "s1", "start_sec": 0.0, "end_sec": 4.0},
                             {"shot_id": "s2", "start_sec": 4.0, "end_sec": 8.0}],
                   "frames_dir": str(frames)}, tmp_path)
    sheet = tmp_path / "contact_sheet.png"
    assert sheet.is_file()
    assert out.png == str(sheet)
    with Image.open(sheet) as img:
        assert img.size == (3 * 320, 2 * (180 + 18))
    payload = json.loads((tmp_path / "render_check.json").read_text(encoding="utf-8"))
    assert payload["frame_count"] == 8
    assert payload["contact_sheet"][0]["first"]["frame_index"] == 0


def test_render_check_bad_frames_dir_fails(tmp_path):
    with pytest.raises(CapabilityError):
        _render("animation.render_check",
                {"shots": [{"shot_id": "s1", "start_sec": 0.0, "end_sec": 4.0}],
                 "frames_dir": str(tmp_path / "nope")}, tmp_path)


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------

def test_demo_spec_11s_three_shots_passes():
    plan = build_demo_spec()
    assert plan["total_duration_sec"] == 11.0
    assert len(plan["shots"]) == 3
    assert [s["emotion"] for s in plan["shots"]] == ["happy", "thinking", "surprised"]
    assert [s["view"] for s in plan["shots"]] == ["front", "three_quarter", "front"]
    assert all(s["character"] == "tuantuan" for s in plan["shots"])
    assert check_guide(plan)["verdict"] == "pass"
    assert validate_timeline(plan)["total_duration_sec"] == 11.0
    assert len(plan["transitions"]) == 2


def test_demo_capability(tmp_path):
    out = _render("animation.tuantuan_demo", {"seed": 7}, tmp_path)
    payload = json.loads((tmp_path / "tuantuan_demo.json").read_text(encoding="utf-8"))
    assert payload["guide_check"]["verdict"] == "pass"
    assert payload["timeline"]["shot_count"] == 3
    assert out.qa["guide_verdict"] == "pass"
