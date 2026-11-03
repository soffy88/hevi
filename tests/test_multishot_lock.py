"""Offline tests for video.multishot_lock.

Covers: reference separation and three-view validation, hard-cut
shot-plan validation, short-shot generate-long-then-trim timecodes,
long-shot splitting, and the continuity ledger (reported, never
auto-rewritten). No network, no paid calls, CPU only.
"""
from __future__ import annotations

import pytest

import hevi.capabilities as caps
from hevi.capabilities.multishot_lock import (
    build_multishot_package,
    build_reference_header,
    check_continuity_ledger,
    validate_shot_plan,
)
from hevi.capabilities.registry import CapabilityError


def _refs(**kw):
    refs = {
        "first_frame": "first_frame.png",
        "subjects": [
            {"name": "girl", "kind": "person",
             "views": {"front": "g_f.png", "side": "g_s.png", "back": "g_b.png"}},
            {"name": "dog", "kind": "animal",
             "views": {"front": "d_f.png", "side": "d_s.png", "back": "d_b.png"}},
        ],
    }
    refs.update(kw)
    return refs


def _shot(sid, start, end, **kw):
    shot = {
        "shot_id": sid, "start_sec": start, "end_sec": end,
        "duration_sec": end - start,
        "scene": f"scene {sid}", "action": f"{sid} does one thing",
        "camera": {"shot_size": "medium", "angle": "front"},
        "characters": ["girl"], "props": ["canvas_bag"],
        "movement_direction": "right",
    }
    shot.update(kw)
    return shot


def _plan(**kw):
    plan = {
        "total_duration_sec": 30.0,
        "aspect": "16:9",
        "references": _refs(),
        "shots": [
            _shot("s1", 0.0, 10.0),
            _shot("s2", 10.0, 20.0, characters=["girl", "dog"]),
            _shot("s3", 20.0, 30.0, characters=["girl", "dog"]),
        ],
        "continuity": {
            "props": [{"name": "canvas_bag", "style": "beige canvas"}],
            "weather": [
                {"shot_id": "s1", "rain": "heavy", "wetness": "damp", "light": "dusk"},
                {"shot_id": "s2", "rain": "moderate", "wetness": "wet", "light": "dusk"},
                {"shot_id": "s3", "rain": "light", "wetness": "soaked", "light": "dusk"},
            ],
            "movement_direction": "right",
        },
    }
    plan.update(kw)
    return plan


def test_registered_and_idempotent():
    assert caps.contains("video.multishot_lock")
    import hevi.capabilities.multishot_lock as mod
    assert mod.register_multishot_lock_capabilities_once() == []


def test_reference_header_separates_jobs():
    header = build_reference_header(_refs())
    assert "Scene, wardrobe and lighting follow the first frame" in header
    assert "use ONLY for face" in header
    assert "Do NOT use its grey background, wardrobe, or three-view layout" in header
    assert "use ONLY for breed, coat colour, markings, build and ear shape" in header
    assert "only the first frame is passed as an image input" in header


def test_missing_first_frame_raises():
    refs = _refs()
    del refs["first_frame"]
    with pytest.raises(CapabilityError):
        build_reference_header(refs)


def test_missing_three_view_raises():
    refs = _refs()
    del refs["subjects"][0]["views"]["back"]
    with pytest.raises(CapabilityError):
        build_reference_header(refs)


def test_missing_subject_raises():
    with pytest.raises(CapabilityError):
        build_reference_header({"first_frame": "f.png", "subjects": []})


def test_duration_sum_mismatch_raises():
    plan = _plan(total_duration_sec=29.0)
    with pytest.raises(CapabilityError):
        validate_shot_plan(plan)


def test_gap_raises():
    plan = _plan()
    plan["shots"][1]["start_sec"] = 11.0
    with pytest.raises(CapabilityError):
        validate_shot_plan(plan)


def test_two_actions_raises():
    plan = _plan()
    plan["shots"][0]["actions"] = ["runs", "waves"]
    with pytest.raises(CapabilityError):
        validate_shot_plan(plan)


def test_non_cut_transition_raises():
    plan = _plan()
    plan["shots"][0]["transition"] = "dissolve"
    with pytest.raises(CapabilityError):
        validate_shot_plan(plan)


def test_missing_camera_angle_raises():
    plan = _plan()
    del plan["shots"][0]["camera"]["angle"]
    with pytest.raises(CapabilityError):
        validate_shot_plan(plan)


def test_short_shots_grouped_then_trimmed():
    plan = _plan(
        total_duration_sec=10.0,
        shots=[_shot("a", 0.0, 3.0), _shot("b", 3.0, 5.0), _shot("c", 5.0, 10.0)],
        continuity={"props": [{"name": "canvas_bag"}]},
    )
    pkg = build_multishot_package(plan)
    segs = pkg["generation_segments"]
    assert segs[0]["shot_ids"] == ["a", "b"]
    assert segs[0]["generation_duration_sec"] == 5.0
    assert segs[0]["strategy"] == "generate_long_then_trim"
    trims = {t["shot_id"]: t for t in pkg["trim_segments"]}
    assert (trims["a"]["in_sec"], trims["a"]["out_sec"]) == (0.0, 3.0)
    assert (trims["b"]["in_sec"], trims["b"]["out_sec"]) == (3.0, 5.0)
    assert segs[1]["strategy"] == "direct"


def test_short_group_under_minimum_is_padded_and_reported():
    plan = _plan(
        total_duration_sec=4.0,
        shots=[_shot("a", 0.0, 2.0), _shot("b", 2.0, 4.0)],
        continuity={"props": [{"name": "canvas_bag"}]},
    )
    pkg = build_multishot_package(plan)
    seg = pkg["generation_segments"][0]
    assert seg["generation_duration_sec"] == 5.0
    assert seg["discard_tail_sec"] == 1.0
    assert seg["strategy"] == "generate_long_then_trim"


def test_long_shot_split_into_equal_chunks():
    plan = _plan(
        total_duration_sec=20.0,
        shots=[_shot("a", 0.0, 20.0)],
        continuity={"props": [{"name": "canvas_bag"}]},
    )
    pkg = build_multishot_package(plan)
    segs = pkg["generation_segments"]
    assert len(segs) == 2
    assert all(s["generation_duration_sec"] == 10.0 for s in segs)
    trims = pkg["trim_segments"]
    assert (trims[0]["timeline_start_sec"], trims[0]["timeline_end_sec"]) == (0.0, 10.0)
    assert (trims[1]["timeline_start_sec"], trims[1]["timeline_end_sec"]) == (10.0, 20.0)


def test_duplicate_prop_fails_ledger_not_rewritten():
    plan = _plan()
    plan["continuity"]["props"] = [{"name": "canvas_bag"}, {"name": "canvas_bag"}]
    pkg = build_multishot_package(plan)
    assert pkg["package_verdict"] == "ledger_fail"
    assert any(v["code"] == "duplicate_prop" for v in pkg["continuity_ledger"]["violations"])


def test_sudden_rain_change_fails():
    plan = _plan()
    plan["continuity"]["weather"][1]["rain"] = "none"
    pkg = build_multishot_package(plan)
    assert pkg["package_verdict"] == "ledger_fail"
    assert any(v["code"] == "sudden_rain_change" for v in pkg["continuity_ledger"]["violations"])


def test_wetness_reversal_fails():
    plan = _plan()
    plan["continuity"]["weather"][2]["wetness"] = "dry"
    pkg = build_multishot_package(plan)
    assert any(v["code"] == "wetness_reversed" for v in pkg["continuity_ledger"]["violations"])


def test_direction_reversal_fails():
    plan = _plan()
    plan["shots"][2]["movement_direction"] = "left"
    pkg = build_multishot_package(plan)
    assert any(v["code"] == "direction_reversed" for v in pkg["continuity_ledger"]["violations"])


def test_on_screen_text_fails():
    plan = _plan()
    plan["shots"][1]["has_text"] = True
    plan["shots"][1]["text_elements"] = ["shop sign"]
    pkg = build_multishot_package(plan)
    assert any(v["code"] == "on_screen_text" for v in pkg["continuity_ledger"]["violations"])


def test_missing_continuity_is_pending_not_pass():
    plan = _plan()
    del plan["continuity"]
    pkg = build_multishot_package(plan)
    assert pkg["continuity_ledger"]["verdict"] == "pending"
    assert pkg["package_verdict"] == "pending"


def test_valid_package_feeds_downstream():
    pkg = build_multishot_package(_plan())
    assert pkg["package_verdict"] == "ready"
    assert pkg["total_duration_sec"] == 30.0
    assert len(pkg["shots"]) == 3
    assert "First frame is the opening frame" in pkg["shots"][0]["prompt"]
    assert "硬切" in pkg["shots"][0]["prompt"]
    assert len(pkg["prompt_compiler_input"]["shots"]) == 3
    assert len(pkg["edit_assemble_input"]["trim_segments"]) == 3
    assert all(t["strategy"] == "direct" for t in pkg["edit_assemble_input"]["trim_segments"])


def test_capability_render_writes_report(tmp_path):
    cap = caps.get("video.multishot_lock")
    result = cap.render({"plan": _plan()}, tmp_path, duration=0.0, aspect="16:9", seed=7)
    assert result.qa["package_verdict"] == "ready"
    assert (tmp_path / "multishot_lock.json").exists()
