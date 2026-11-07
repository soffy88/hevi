"""Tests for the code-stage MV graft: B2 + B3 + B4 (clean-room, method only).

B2 qa.dance_action_events: extraction from an offline keypoint
contract only; the only measured run uses code-generated
synthetic video, labelled synthetic_video, never human.
B3 qa.event_trigger_wiring: plan-only wiring, no music
generated; tolerance calibrated from measured dual-template runs.
B4 video.minimal_stage_render: minimal Three.js stage, zero
external assets, rendered twice with per-frame hash equality.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from hevi.capabilities import get as _get_capability
from hevi.capabilities.dance_action_events import (
    extract_dance_events,
    generate_synthetic_dance,
    pose_backend_status,
    render_synthetic_dance_video,
    score_events,
)
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.event_trigger_wiring import (
    MAPPING_RULES,
    calibrate_tolerance,
    check_wiring,
    wire_events,
)
from hevi.capabilities.minimal_stage_render import (
    build_stage_plan,
    render_minimal_stage,
    validate_stage_plan,
)


# ---------------------------------------------------------------- B2


def test_b2_extract_synthetic_all_four_types() -> None:
    synthetic = generate_synthetic_dance()
    report = extract_dance_events(synthetic)
    assert report["verdict"] == "pass"
    assert report["human_measured"] is False
    assert report["measurement_basis"] == "synthetic_video"
    assert report["frames_checked"] == 40
    assert [(e["type"], e["t"]) for e in report["events"]] == [
        ("footstep", 0.5),
        ("raise_arm", 1.2),
        ("turn", 2.0),
        ("hold", 2.8),
        ("footstep", 3.7),
    ]
    assert all(e["source"] == "pose_delta" for e in report["events"])
    assert all(e["confidence"] >= 0.5 for e in report["events"])
    assert report["candidates"] == []


def test_b2_score_synthetic_f1_perfect() -> None:
    synthetic = generate_synthetic_dance()
    report = extract_dance_events(synthetic)
    scored = score_events(report["events"], synthetic["ground_truth"], tolerance_ms=100.0)
    assert scored["overall"] == {
        "tp": 5, "fp": 0, "fn": 0,
        "precision": 1.0, "recall": 1.0, "f1": 1.0,
        "max_abs_error_ms": 0.0, "mean_abs_error_ms": 0.0,
    }
    assert scored["per_type"]["footstep"]["f1"] == 1.0
    assert scored["per_type"]["hold"]["f1"] == 1.0
    assert all(m["error_ms"] == 0.0 for m in scored["matches"])


def test_b2_score_shifted_truth_lowers_f1() -> None:
    synthetic = generate_synthetic_dance()
    report = extract_dance_events(synthetic)
    shifted = [
        dict(event, t=event["t"] + 0.5) for event in synthetic["ground_truth"]
    ]
    scored = score_events(report["events"], shifted, tolerance_ms=100.0)
    assert scored["overall"]["f1"] == 0.0
    assert scored["overall"]["tp"] == 0
    assert scored["overall"]["fn"] == 5


def test_b2_missing_keypoints_raise() -> None:
    with pytest.raises(CapabilityError, match="video path"):
        extract_dance_events({"video_path": "dance.mp4"})
    with pytest.raises(CapabilityError, match="non-empty 'frames'"):
        extract_dance_events({"fps": 10, "width": 320, "height": 240, "frames": []})
    with pytest.raises(CapabilityError, match="JSON object"):
        extract_dance_events(None)


def test_b2_missing_joint_raises() -> None:
    synthetic = generate_synthetic_dance()
    del synthetic["frames"][10]["joints"]["ankle_left"]
    with pytest.raises(CapabilityError, match="missing required joint"):
        extract_dance_events(synthetic)


def test_b2_t_sec_mismatch_raises() -> None:
    synthetic = generate_synthetic_dance()
    synthetic["frames"][3]["t_sec"] = 9.9
    with pytest.raises(CapabilityError, match="disagrees with frame/fps"):
        extract_dance_events(synthetic)


def test_b2_continuous_drift_has_no_events() -> None:
    frames = []
    for i in range(30):
        joints = {
            name: {"x": float(x + 3 * i), "y": float(y), "confidence": 1.0}
            for name, (x, y) in {
                "ankle_left": (135, 200), "ankle_right": (185, 200),
                "wrist_left": (115, 130), "wrist_right": (205, 130),
                "shoulder_left": (130, 110), "shoulder_right": (190, 110),
                "hip_left": (135, 170), "hip_right": (185, 170),
            }.items()
        }
        frames.append({"frame": i, "joints": joints})
    report = extract_dance_events(
        {"fps": 10, "width": 320, "height": 240, "frames": frames}
    )
    assert report["verdict"] == "pass"
    assert report["events"] == []


def test_b2_weak_signal_is_candidate_not_event() -> None:
    synthetic = generate_synthetic_dance()
    report = extract_dance_events(
        synthetic, thresholds={"footstep_min_drop_px": 20.0}
    )
    assert all(e["type"] != "footstep" for e in report["events"])
    assert any(c["type"] == "footstep" for c in report["candidates"])


def test_b2_confidence_floor_demotes_to_candidate() -> None:
    synthetic = generate_synthetic_dance()
    # Re-shape the first footstep dip so its strength is exactly
    # the threshold (confidence 0.5): a steep 6px dip.
    for frame, y in zip((2, 3, 4, 5, 6, 7, 8), (200.0, 200.0, 202.0, 206.0, 202.0, 200.0, 200.0)):
        synthetic["frames"][frame]["joints"]["ankle_left"]["y"] = y
    low_floor = extract_dance_events(synthetic, confidence_floor=0.5)
    assert any(e["type"] == "footstep" and e["t"] == 0.5 for e in low_floor["events"])
    high_floor = extract_dance_events(synthetic, confidence_floor=0.6)
    assert not any(e["type"] == "footstep" and e["t"] == 0.5 for e in high_floor["events"])
    assert any(c["type"] == "footstep" and c["t"] == 0.5 for c in high_floor["candidates"])


def test_b2_backend_status_is_offline_contract() -> None:
    status = pose_backend_status()
    assert status["backend"] == "offline_keypoint_contract"
    assert status["pixel_pose_estimation"] == "unavailable"
    assert status["human_measured"] is False


def test_b2_synthetic_video_renders_and_probes(tmp_path: Path) -> None:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("ffmpeg/ffprobe unavailable")
    synthetic = generate_synthetic_dance()
    out = tmp_path / "synthetic_dance.mp4"
    info = render_synthetic_dance_video(synthetic, out, work_dir=tmp_path / "frames")
    assert out.is_file() and out.stat().st_size > 0
    assert info["frame_count"] == 40
    assert info["duration_sec"] == pytest.approx(4.0, abs=0.25)
    assert info["human_measured"] is False
    assert info["measurement_basis"] == "synthetic_video"


# ---------------------------------------------------------------- B3


def _stage_template(*, light_hex="#FFFFFF", floor_hex="#101018", movement="dolly",
                    particle_kind="sparkle", sheet_id="stage-a", version=2):
    return {
        "sheet_id": sheet_id,
        "version": version,
        "stage": {
            "lighting_rig": {
                "lights": [
                    {"type": "key", "angle_deg": 45, "color_temperature_k": 5600,
                     "intensity": 1.0, "color_hex": light_hex},
                    {"type": "rim", "angle_deg": 210, "color_temperature_k": 3200,
                     "intensity": 0.6},
                ],
                "beat_curve": [
                    {"beat": 1, "intensity": 0.6},
                    {"beat": 2, "intensity": 1.0},
                    {"beat": 3, "intensity": 0.7},
                ],
            },
            "camera_path": {
                "start_shot": "full_body", "end_shot": "medium",
                "movement": movement,
                "beat_binding": {"beats": [1, 2, 4, 8]},
                "duration_s": 8.0,
            },
            "particles": {"kind": particle_kind, "density": 0.3,
                          "trigger_event": "footstep", "speed": 1.2},
            "materials": {
                "style": "glass_prism",
                "floor": {"reflective": True, "roughness": 0.2, "color_hex": floor_hex},
            },
        },
    }


def _b2_events():
    synthetic = generate_synthetic_dance()
    return extract_dance_events(synthetic)["events"]


def test_b3_wire_happy_path() -> None:
    plan = wire_events(_b2_events(), stage_template=_stage_template())
    assert plan["verdict"] == "pass"
    assert plan["rules_version"] == "1"
    assert plan["music_generated"] is False
    assert [(t["event_type"], t["music_action"], t["stage_action"], t["trigger_t"])
            for t in plan["triggers"]] == [
        ("footstep", "kick", "ground_light", 0.5),
        ("raise_arm", "accent", "light_pulse", 1.2),
        ("turn", "transition", "camera_move", 2.0),
        ("hold", "pause", "light_hold", 2.8),
        ("footstep", "kick", "ground_light", 3.7),
    ]
    assert all(t["stage_params"] is not None for t in plan["triggers"])
    assert plan["suppressed"] == []


def test_b3_mapping_table_covers_all_b2_types() -> None:
    assert set(MAPPING_RULES) == {"footstep", "turn", "raise_arm", "hold"}


def test_b3_no_events_raises() -> None:
    with pytest.raises(CapabilityError, match="non-empty list"):
        wire_events([], stage_template=_stage_template())
    with pytest.raises(CapabilityError, match="non-empty list"):
        wire_events(None, stage_template=_stage_template())


def test_b3_unmapped_type_fails() -> None:
    events = [{"type": "spin", "t": 1.0, "confidence": 0.9, "source": "pose_delta"}]
    plan = wire_events(events, stage_template=_stage_template())
    assert plan["verdict"] == "fail"
    assert any(i["code"] == "missing_mapping" for i in plan["issues"])


def test_b3_missing_or_invalid_template_fails() -> None:
    plan = wire_events(_b2_events(), stage_template=None)
    assert plan["verdict"] == "fail"
    assert any(i["code"] == "stage_template_missing" for i in plan["issues"])
    broken = _stage_template()
    del broken["stage"]["lighting_rig"]
    plan = wire_events(_b2_events(), stage_template=broken)
    assert plan["verdict"] == "fail"
    assert any(i["code"] == "stage_template_invalid" for i in plan["issues"])


def test_b3_low_confidence_event_is_suppressed() -> None:
    events = _b2_events()
    events[0] = dict(events[0], confidence=0.2)
    plan = wire_events(events, stage_template=_stage_template())
    assert plan["verdict"] == "pass"
    assert len(plan["triggers"]) == 4
    assert len(plan["suppressed"]) == 1
    assert plan["suppressed"][0]["type"] == "footstep"


def test_b3_all_suppressed_fails() -> None:
    events = [dict(e, confidence=0.1) for e in _b2_events()]
    plan = wire_events(events, stage_template=_stage_template())
    assert plan["verdict"] == "fail"
    assert any(i["code"] == "no_triggers" for i in plan["issues"])


def test_b3_beat_deltas_are_reported_not_snapped() -> None:
    beats = [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0]
    plan = wire_events(_b2_events(), stage_template=_stage_template(), beat_times=beats)
    assert plan["verdict"] == "pass"
    for trigger in plan["triggers"]:
        # Beats are 0.5s apart, so the nearest-beat delta is at most 250ms;
        # the trigger itself is never snapped onto the beat.
        assert abs(trigger["beat_delta_ms"]) <= 250.0
        assert trigger["trigger_t"] == trigger["event_t"]


def test_b3_check_wiring_pass_shift_and_missing_fail() -> None:
    events = _b2_events()
    plan = wire_events(events, stage_template=_stage_template())
    assert check_wiring(plan["triggers"], events)["verdict"] == "pass"
    shifted = [dict(t, trigger_t=t["trigger_t"] + 0.2) for t in plan["triggers"]]
    checked = check_wiring(shifted, events, tolerance_ms=100.0)
    assert checked["verdict"] == "fail"
    assert any(i["code"] == "trigger_out_of_tolerance" for i in checked["issues"])
    assert checked["max_abs_error_ms"] == pytest.approx(200.0)
    assert check_wiring(plan["triggers"][:-1], events)["verdict"] == "fail"


def test_b3_calibrate_tolerance_from_measurements() -> None:
    assert calibrate_tolerance([0.0, 0.0, 0.0])["tolerance_ms"] == 50.0
    assert calibrate_tolerance([10.0, 20.0, 30.0])["tolerance_ms"] == 50.0
    assert calibrate_tolerance([40.0, 60.0])["tolerance_ms"] == 90.0
    with pytest.raises(CapabilityError, match="non-empty"):
        calibrate_tolerance([])


def test_b3_dual_template_same_trigger_times() -> None:
    events = _b2_events()
    template_a = _stage_template(light_hex="#FFFFFF", floor_hex="#101018", movement="dolly")
    template_b = _stage_template(light_hex="#FF8800", floor_hex="#201010", movement="orbit",
                                 particle_kind="ember")
    plan_a = wire_events(events, stage_template=template_a)
    plan_b = wire_events(events, stage_template=template_b)
    assert plan_a["verdict"] == "pass" and plan_b["verdict"] == "pass"
    times_a = [t["trigger_t"] for t in plan_a["triggers"]]
    times_b = [t["trigger_t"] for t in plan_b["triggers"]]
    assert times_a == times_b
    # The templates differ, so the stage parameters must differ too.
    assert plan_a["triggers"][0]["stage_params"] != plan_b["triggers"][0]["stage_params"]
    check_a = check_wiring(plan_a["triggers"], events)
    check_b = check_wiring(plan_b["triggers"], events)
    assert check_a["verdict"] == "pass" and check_b["verdict"] == "pass"
    errors = [e["error_ms"] for e in check_a["errors"]] + [e["error_ms"] for e in check_b["errors"]]
    assert errors == [0.0] * 10
    calibrated = calibrate_tolerance(errors)
    assert calibrated["tolerance_ms"] == 50.0
    assert calibrated["max_abs_error_ms"] == 0.0


# ---------------------------------------------------------------- B4


def _browser_available() -> bool:
    try:
        import playwright  # noqa: F401
    except Exception:
        return False
    try:
        from hevi.capabilities.minimal_stage_render import resolve_three_module
        resolve_three_module()
    except Exception:
        return False
    cache = Path.home() / ".cache" / "ms-playwright"
    if cache.is_dir() and any("chromium" in d.name for d in cache.iterdir()):
        return True
    return any(Path(p).is_dir() for p in ("/home/soffy/.cache/ms-playwright",))


def test_b4_plan_gates_pass() -> None:
    plan = build_stage_plan(width=320, height=180, fps=10, duration_s=2.0)
    assert validate_stage_plan(plan)["verdict"] == "pass"


def test_b4_plan_gates_fail_on_wall_clock_and_wrong_protocol() -> None:
    plan = build_stage_plan(width=320, height=180, fps=10, duration_s=2.0)
    plan["render"]["wall_clock_sources"] = ["Date.now"]
    assert validate_stage_plan(plan)["verdict"] == "fail"
    plan = build_stage_plan(width=320, height=180, fps=10, duration_s=2.0)
    plan["adapter"]["protocol"] = "__timelines"
    assert validate_stage_plan(plan)["verdict"] == "fail"


def test_b4_unsupported_camera_movement_raises(tmp_path: Path) -> None:
    template = _stage_template(movement="crane")
    with pytest.raises(CapabilityError, match="not supported"):
        render_minimal_stage(stage_template=template, out_dir=tmp_path)


@pytest.mark.skipif(not _browser_available(), reason="Playwright/Chromium/three.js unavailable")
def test_b4_double_render_hash_identical(tmp_path: Path) -> None:
    report = render_minimal_stage(
        stage_template=_stage_template(), out_dir=tmp_path,
        width=320, height=180, fps=10, duration_s=1.0,
    )
    assert report["verdict"] == "pass", report["issues"]
    assert report["hashes_identical"] is True
    assert report["frame_count"] == 10
    assert len(report["runs"]) == 2
    for run in report["runs"]:
        assert len(run["frames"]) == 10
        assert all(f["settled"] is True for f in run["frames"])
        for frame in run["frames"]:
            assert (tmp_path / f"run_{run['run']}" / frame["file"]).is_file()
    hashes_a = [f["sha256"] for f in report["runs"][0]["frames"]]
    hashes_b = [f["sha256"] for f in report["runs"][1]["frames"]]
    assert hashes_a == hashes_b
    assert len(set(hashes_a)) > 1, "all frames identical means the scene is not animating"


@pytest.mark.skipif(not _browser_available(), reason="Playwright/Chromium/three.js unavailable")
def test_b4_template_change_changes_render(tmp_path: Path) -> None:
    report_a = render_minimal_stage(
        stage_template=_stage_template(light_hex="#FFFFFF", floor_hex="#101018"),
        out_dir=tmp_path / "a", width=320, height=180, fps=10, duration_s=1.0,
    )
    report_b = render_minimal_stage(
        stage_template=_stage_template(light_hex="#FF8800", floor_hex="#201010"),
        out_dir=tmp_path / "b", width=320, height=180, fps=10, duration_s=1.0,
    )
    assert report_a["verdict"] == "pass" and report_b["verdict"] == "pass"
    first_a = report_a["runs"][0]["frames"][0]["sha256"]
    first_b = report_b["runs"][0]["frames"][0]["sha256"]
    assert first_a != first_b


# ---------------------------------------------------------------- registry


def test_b2b3b4_capabilities_registered() -> None:
    for name in ("qa.dance_action_events", "qa.event_trigger_wiring",
                 "video.minimal_stage_render"):
        assert _get_capability(name).name == name


def test_b2b3b4_render_safe_report_modes(tmp_path: Path) -> None:
    b2 = _get_capability("qa.dance_action_events")
    result = b2.render_safe(
        {"mode": "synthetic", "fps": 10, "duration_s": 4.0},
        tmp_path / "b2", duration=0.0, aspect="16:9", seed=0,
    )
    assert result.qa["ok"] is True
    report = json.loads(Path(result.qa["report_json"]).read_text(encoding="utf-8"))
    assert report["score"]["overall"]["f1"] == 1.0
    b3 = _get_capability("qa.event_trigger_wiring")
    result = b3.render_safe(
        {"mode": "wire", "events": _b2_events(), "stage_template": _stage_template()},
        tmp_path / "b3", duration=0.0, aspect="16:9", seed=0,
    )
    assert result.qa["ok"] is True
    b4 = _get_capability("video.minimal_stage_render")
    result = b4.render_safe(
        {"mode": "plan", "stage_template": _stage_template()},
        tmp_path / "b4", duration=0.0, aspect="16:9", seed=0,
    )
    assert result.qa["ok"] is True
