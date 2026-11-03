"""Tests for the code-stage MV graft: A1 + A2 + B1 (clean-room, method only).

A1 qa.greenscreen_generation_gate: plan text only, no generation.
A2 pipeline.project_style_sheet stage block: version + stale
discipline reused; missing lighting/camera fields stay pending.
B1 qa.chroma_key_gate: six gates over supplied measurements;
the FFmpeg route is contract only here (the real 5-second sample
is recorded outside this repo, in /data/soffy/code-stage-sample/).
"""

from __future__ import annotations

import hashlib

import pytest

from hevi.capabilities.chroma_key_gate import (
    build_ffmpeg_chromakey_command,
    check_chroma_key_evidence,
    validate_key_params,
)
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.greenscreen_generation_gate import (
    check_greenscreen_generation_plan,
)
from hevi.capabilities.project_style_sheet import (
    check_render_readiness,
    check_stage_readiness,
    validate_stage_block,
    validate_style_sheet,
)


@pytest.fixture()
def anchor_files(tmp_path):
    """Two real files, so the strict-entry binding resolver (which
    requires anchor/binding files to exist on disk) can succeed."""
    anchor = tmp_path / "dancer-anchor.png"
    anchor.write_bytes(b"anchor-image-bytes")
    other = tmp_path / "other.png"
    other.write_bytes(b"other-image-bytes")
    return {
        "file": str(anchor),
        "sha": hashlib.sha256(b"anchor-image-bytes").hexdigest(),
        "other_file": str(other),
        "other_sha": hashlib.sha256(b"other-image-bytes").hexdigest(),
    }


def _anchors(files, confirmed=True):
    return {
        "Lan Xi": {
            "file": files["file"],
            "sha256": files["sha"],
            "look": "silver-grey high ponytail, black-and-white tech streetwear",
            "confirmed": confirmed,
        }
    }


def _bindings(files):
    return {1: {"file": files["file"], "sha256": files["sha"]}}


def _plan(files, **overrides):
    plan = {
        "prompt": "Lan Xi dances on a pure green screen, fixed camera, full body in frame, "
        "silver-grey high ponytail, black-and-white tech streetwear",
        "character": "Lan Xi",
        "camera": {"movement": "fixed", "shot_size": "full_body"},
        "framing": {"full_body_visible": True, "subject_exits_frame": False},
        "background": {"color_hex": "#00FF00", "green_screen": True},
        "duration_s": 8.0,
        "fps": 24,
        "width": 1280,
        "height": 720,
        "provider": "pixstag",
        "anchors": _anchors(files),
        "reference_bindings": _bindings(files),
    }
    plan.update(overrides)
    return plan


def _stage_sheet(**overrides):
    sheet = {
        "schema_version": 1,
        "sheet_id": "stage-a",
        "version": 2,
        "proportions": {"head_height_ratio": 0.5},
        "outline": {"stroke_width_px": 6},
        "palette": {"colors": ["#111111", "#EEEEEE"]},
        "lighting": {"key_light_intensity": 1.2},
        "material": {"roughness": 0.6},
        "motion": {"walk_cycle_sec": 0.8},
        "stage": {
            "lighting_rig": {
                "lights": [
                    {"type": "key", "angle_deg": 45, "color_temperature_k": 5600, "intensity": 1.0, "color_hex": "#FFFFFF"},
                    {"type": "rim", "angle_deg": 210, "color_temperature_k": 3200, "intensity": 0.6},
                ],
                "beat_curve": [
                    {"beat": 1, "intensity": 0.6},
                    {"beat": 2, "intensity": 1.0},
                    {"beat": 3, "intensity": 0.7},
                ],
            },
            "camera_path": {
                "start_shot": "full_body",
                "end_shot": "medium",
                "movement": "dolly",
                "beat_binding": {"beats": [1, 2, 4, 8]},
                "duration_s": 8.0,
            },
            "particles": {"kind": "sparkle", "density": 0.3, "trigger_event": "footstep", "speed": 1.2},
            "materials": {
                "style": "glass_prism",
                "floor": {"reflective": True, "roughness": 0.2, "color_hex": "#101018"},
            },
        },
    }
    sheet.update(overrides)
    return sheet


def _evidence(**overrides):
    frame = {
        "frame": 0,
        "edge_transition_px": 3,
        "green_fringe_ratio": 0.01,
        "spill_ratio": 0.01,
        "foot_y_px": 620,
        "ground_y_px": 620,
        "shadow_present": True,
        "shadow_angle_deg": 45,
        "light_angle_deg": 45,
        "subject_height_ratio": 0.75,
        "subject_light_angle_deg": 45,
        "subject_light_intensity": 1.0,
    }
    evidence = {
        "frames": [frame],
        "designed_height_ratio": 0.75,
        "stage_light_angle_deg": 45,
        "stage_light_intensity": 1.0,
    }
    evidence.update(overrides)
    return evidence


# --- A1: qa.greenscreen_generation_gate ---


def test_a1_valid_plan_passes_all_five_checks(anchor_files):
    report = check_greenscreen_generation_plan(_plan(anchor_files))
    assert report["verdict"] == "pass"
    assert report["checks"] == {
        "camera": True,
        "containment": True,
        "background": True,
        "caps": True,
        "anchor": True,
    }
    assert report["anchor"]["name"] == "Lan Xi"
    assert report["caps"]["provider"] == "pixstag"


def test_a1_moving_camera_fails(anchor_files):
    report = check_greenscreen_generation_plan(
        _plan(anchor_files, camera={"movement": "pan", "shot_size": "full_body"})
    )
    assert report["verdict"] == "fail"
    assert any(i["code"] == "camera_not_fixed" for i in report["issues"])
    assert report["checks"]["camera"] is False


def test_a1_camera_movement_word_in_prompt_fails(anchor_files):
    plan = _plan(anchor_files)
    plan["prompt"] += ", slow dolly in"
    report = check_greenscreen_generation_plan(plan)
    assert report["verdict"] == "fail"
    assert any(i["code"] == "camera_movement_in_prompt" for i in report["issues"])


def test_a1_close_up_shot_fails(anchor_files):
    report = check_greenscreen_generation_plan(
        _plan(anchor_files, camera={"movement": "fixed", "shot_size": "close_up"})
    )
    assert report["verdict"] == "fail"
    assert any(i["code"] == "shot_not_full_body" for i in report["issues"])


def test_a1_subject_exits_frame_fails(anchor_files):
    report = check_greenscreen_generation_plan(
        _plan(anchor_files, framing={"full_body_visible": True, "subject_exits_frame": True})
    )
    assert report["verdict"] == "fail"
    assert any(i["code"] == "subject_exits_frame" for i in report["issues"])
    assert report["checks"]["containment"] is False


def test_a1_stage_word_in_prompt_fails(anchor_files):
    plan = _plan(anchor_files)
    plan["prompt"] += ", on a concert stage with neon lighting"
    report = check_greenscreen_generation_plan(plan)
    assert report["verdict"] == "fail"
    assert any(i["code"] == "stage_word_in_prompt" for i in report["issues"])
    assert report["checks"]["background"] is False


def test_a1_non_pure_green_background_fails(anchor_files):
    report = check_greenscreen_generation_plan(
        _plan(anchor_files, background={"color_hex": "#00B140", "green_screen": True})
    )
    assert report["verdict"] == "fail"
    assert any(i["code"] == "background_not_pure_green" for i in report["issues"])


def test_a1_duration_over_provider_cap_fails(anchor_files):
    # pixstag tier-table cap is 30s; 31s must fail, 30s must pass.
    report = check_greenscreen_generation_plan(_plan(anchor_files, duration_s=31.0))
    assert report["verdict"] == "fail"
    assert any(i["code"] == "duration_exceeds_provider_cap" for i in report["issues"])
    assert check_greenscreen_generation_plan(_plan(anchor_files, duration_s=30.0))["verdict"] == "pass"


def test_a1_unknown_provider_tier_fails(anchor_files):
    report = check_greenscreen_generation_plan(_plan(anchor_files, provider="no_such_provider"))
    assert report["verdict"] == "fail"
    assert any(i["code"] in ("provider_missing", "tier_unknown") for i in report["issues"])
    assert report["checks"]["caps"] is False


def test_a1_explicit_provider_caps_win(anchor_files):
    caps = {"provider": "custom", "max_shot_s": 5.0, "min_shot_s": 1.0}
    report = check_greenscreen_generation_plan(_plan(anchor_files, provider_caps=caps, duration_s=8.0))
    assert report["verdict"] == "fail"
    assert any(i["code"] == "duration_exceeds_provider_cap" for i in report["issues"])
    assert check_greenscreen_generation_plan(_plan(anchor_files, provider_caps=caps, duration_s=5.0))["verdict"] == "pass"


def test_a1_unconfirmed_anchor_fails(anchor_files):
    report = check_greenscreen_generation_plan(
        _plan(anchor_files, anchors=_anchors(anchor_files, confirmed=False))
    )
    assert report["verdict"] == "fail"
    assert any(i["code"] == "anchor_unresolved" for i in report["issues"])
    assert report["checks"]["anchor"] is False


def test_a1_anchor_not_bound_fails(anchor_files):
    report = check_greenscreen_generation_plan(
        _plan(anchor_files, reference_bindings={1: {"file": anchor_files["other_file"], "sha256": anchor_files["other_sha"]}})
    )
    assert report["verdict"] == "fail"
    assert any(i["code"] == "anchor_not_bound" for i in report["issues"])


def test_a1_missing_picture_1_fails(anchor_files):
    report = check_greenscreen_generation_plan(
        _plan(anchor_files, reference_bindings={2: {"file": anchor_files["file"], "sha256": anchor_files["sha"]}})
    )
    assert report["verdict"] == "fail"
    assert any(i["code"] == "picture_1_missing" for i in report["issues"])


def test_a1_missing_anchors_fails_not_silent(anchor_files):
    plan = _plan(anchor_files)
    del plan["anchors"]
    report = check_greenscreen_generation_plan(plan)
    assert report["verdict"] == "fail"
    assert any(i["code"] == "anchors_missing" for i in report["issues"])


def test_a1_malformed_plan_raises():
    with pytest.raises(CapabilityError):
        check_greenscreen_generation_plan("dance on green")
    with pytest.raises(CapabilityError):
        check_greenscreen_generation_plan({"character": "Lan Xi"})


# --- A2: pipeline.project_style_sheet stage block ---


def test_a2_plain_sheet_still_valid_without_stage():
    sheet = _stage_sheet()
    del sheet["stage"]
    report = validate_style_sheet(sheet)
    assert report["ok"] is True
    assert report["stage_present"] is False
    # The pre-existing readiness discipline is unchanged.
    assert check_render_readiness(
        sheet, sample_confirmation={"version": 2, "confirmed": True, "sample_duration_sec": 4.0}
    )["ok"] is True


def test_a2_stage_sheet_validates():
    report = validate_style_sheet(_stage_sheet())
    assert report["ok"] is True
    assert report["stage_present"] is True
    assert report["stage_ok"] is True
    assert report["stage_problems"] == []


def test_a2_stage_block_validates_standalone():
    report = validate_stage_block(_stage_sheet()["stage"])
    assert report["ok"] is True
    assert report["present"] is True


def test_a2_stage_readiness_ready_with_fresh_sample():
    report = check_stage_readiness(
        _stage_sheet(),
        sample_confirmation={"version": 2, "confirmed": True, "sample_duration_sec": 4.0},
    )
    assert report["ok"] is True
    assert report["status"] == "ready"
    assert report["stale"] is False


def test_a2_missing_lighting_rig_is_pending():
    sheet = _stage_sheet()
    del sheet["stage"]["lighting_rig"]
    report = check_stage_readiness(
        sheet, sample_confirmation={"version": 2, "confirmed": True, "sample_duration_sec": 4.0}
    )
    assert report["ok"] is False
    assert report["status"] == "pending"
    assert any("lighting_rig" in p for p in report["problems"])
    assert validate_style_sheet(sheet)["ok"] is False


def test_a2_missing_camera_path_is_pending():
    sheet = _stage_sheet()
    del sheet["stage"]["camera_path"]
    report = check_stage_readiness(
        sheet, sample_confirmation={"version": 2, "confirmed": True, "sample_duration_sec": 4.0}
    )
    assert report["ok"] is False
    assert report["status"] == "pending"
    assert any("camera_path" in p for p in report["problems"])


def test_a2_missing_stage_block_is_pending():
    sheet = _stage_sheet()
    del sheet["stage"]
    report = check_stage_readiness(
        sheet, sample_confirmation={"version": 2, "confirmed": True, "sample_duration_sec": 4.0}
    )
    assert report["ok"] is False
    assert report["status"] == "pending"
    assert any("stage" in p for p in report["problems"])


def test_a2_stale_sample_keeps_stage_pending():
    report = check_stage_readiness(
        _stage_sheet(),
        sample_confirmation={"version": 1, "confirmed": True, "sample_duration_sec": 4.0},
    )
    assert report["ok"] is False
    assert report["status"] == "pending"
    assert report["stale"] is True


def test_a2_bad_beat_curve_fails():
    stage = _stage_sheet()["stage"]
    stage["lighting_rig"]["beat_curve"] = [{"beat": 2, "intensity": 1.0}, {"beat": 1, "intensity": 0.5}]
    report = validate_stage_block(stage)
    assert report["ok"] is False
    assert any("beat_curve" in p for p in report["problems"])


def test_a2_bad_particle_density_fails():
    stage = _stage_sheet()["stage"]
    stage["particles"]["density"] = 1.5
    report = validate_stage_block(stage)
    assert report["ok"] is False
    assert any("density" in p for p in report["problems"])


def test_a2_bad_floor_colour_fails():
    stage = _stage_sheet()["stage"]
    stage["materials"]["floor"]["color_hex"] = "dark blue"
    report = validate_stage_block(stage)
    assert report["ok"] is False
    assert any("color_hex" in p for p in report["problems"])


def test_a2_stage_must_be_object():
    with pytest.raises(CapabilityError):
        validate_stage_block("glass prism stage")


# --- B1: qa.chroma_key_gate ---


def test_b1_valid_evidence_passes_all_six_gates():
    report = check_chroma_key_evidence(_evidence())
    assert report["verdict"] == "pass"
    assert report["frames_checked"] == 1
    assert all(gate["ok"] for gate in report["gates"].values())
    assert set(report["gates"]) == {"edge", "spill", "grounding", "shadow", "proportion", "lighting"}


def test_b1_hard_edge_fails():
    frame = _evidence()["frames"][0]
    frame["edge_transition_px"] = 0
    report = check_chroma_key_evidence(_evidence(frames=[frame]))
    assert report["verdict"] == "fail"
    assert report["gates"]["edge"]["ok"] is False
    assert any(i["code"] == "edge_transition" for i in report["issues"])


def test_b1_green_fringe_fails():
    frame = _evidence()["frames"][0]
    frame["green_fringe_ratio"] = 0.09
    report = check_chroma_key_evidence(_evidence(frames=[frame]))
    assert report["verdict"] == "fail"
    assert report["gates"]["edge"]["ok"] is False
    assert any(i["code"] == "green_fringe" for i in report["issues"])


def test_b1_spill_fails():
    frame = _evidence()["frames"][0]
    frame["spill_ratio"] = 0.08
    report = check_chroma_key_evidence(_evidence(frames=[frame]))
    assert report["verdict"] == "fail"
    assert report["gates"]["spill"]["ok"] is False


def test_b1_floating_feet_fail_grounding():
    frame = _evidence()["frames"][0]
    frame["foot_y_px"] = 615
    report = check_chroma_key_evidence(_evidence(frames=[frame]))
    assert report["verdict"] == "fail"
    assert report["gates"]["grounding"]["ok"] is False
    assert any(i["code"] == "grounding" for i in report["issues"])


def test_b1_grounding_within_2px_passes():
    frame = _evidence()["frames"][0]
    frame["foot_y_px"] = 622
    assert check_chroma_key_evidence(_evidence(frames=[frame]))["verdict"] == "pass"


def test_b1_missing_shadow_fails():
    frame = _evidence()["frames"][0]
    frame["shadow_present"] = False
    report = check_chroma_key_evidence(_evidence(frames=[frame]))
    assert report["verdict"] == "fail"
    assert report["gates"]["shadow"]["ok"] is False
    assert any(i["code"] == "shadow_missing" for i in report["issues"])


def test_b1_shadow_direction_mismatch_fails():
    frame = _evidence()["frames"][0]
    frame["shadow_angle_deg"] = 90
    report = check_chroma_key_evidence(_evidence(frames=[frame]))
    assert report["verdict"] == "fail"
    assert any(i["code"] == "shadow_angle" for i in report["issues"])


def test_b1_proportion_drift_fails():
    frame = _evidence()["frames"][0]
    frame["subject_height_ratio"] = 0.60
    report = check_chroma_key_evidence(_evidence(frames=[frame]))
    assert report["verdict"] == "fail"
    assert report["gates"]["proportion"]["ok"] is False


def test_b1_lighting_mismatch_fails():
    frame = _evidence()["frames"][0]
    frame["subject_light_angle_deg"] = 180
    report = check_chroma_key_evidence(_evidence(frames=[frame]))
    assert report["verdict"] == "fail"
    assert report["gates"]["lighting"]["ok"] is False
    assert any(i["code"] == "lighting_angle" for i in report["issues"])


def test_b1_missing_measurement_fails_its_gate():
    frame = _evidence()["frames"][0]
    del frame["foot_y_px"]
    report = check_chroma_key_evidence(_evidence(frames=[frame]))
    assert report["verdict"] == "fail"
    assert report["gates"]["grounding"]["ok"] is False
    assert any(i["code"] == "measurement_missing" for i in report["issues"])


def test_b1_malformed_evidence_raises():
    with pytest.raises(CapabilityError):
        check_chroma_key_evidence({"frames": []})
    with pytest.raises(CapabilityError):
        check_chroma_key_evidence("keyed frames")


def test_b1_key_params_validate_green_only():
    report = validate_key_params({"key_color_hex": "#00FF00", "similarity": 0.15, "blend": 0.1})
    assert report["ok"] is True
    assert report["filter"] == "chromakey=0x00ff00:0.15:0.1"
    red = validate_key_params({"key_color_hex": "#FF0000"})
    assert red["ok"] is False
    assert any("green-dominant" in p for p in red["problems"])


def test_b1_ffmpeg_command_contract():
    command = build_ffmpeg_chromakey_command(
        "fg.mp4", "bg.mp4", "out.mp4",
        key_params={"key_color_hex": "#00FF00", "similarity": 0.15, "blend": 0.1},
    )
    assert command[0] == "ffmpeg"
    assert command[-1] == "out.mp4"
    filter_complex = command[command.index("-filter_complex") + 1]
    assert "chromakey=0x00ff00:0.15:0.1" in filter_complex
    assert "overlay=0:0" in filter_complex
    with pytest.raises(CapabilityError):
        build_ffmpeg_chromakey_command("fg.mp4", "bg.mp4", "out.mp4", key_params={"key_color_hex": "#FF0000"})


# --- Registration ---


def test_new_capabilities_registered_once():
    from hevi.capabilities import chroma_key_gate as _ck
    from hevi.capabilities import greenscreen_generation_gate as _gs
    from hevi.capabilities import project_style_sheet as _pss

    assert _gs.register_greenscreen_generation_gate_capabilities_once() == []
    assert _ck.register_chroma_key_gate_capabilities_once() == []
    assert _pss.register_project_style_sheet_capabilities_once() == []

    from hevi.capabilities.registry import get as _get

    assert _get("qa.greenscreen_generation_gate").name == "qa.greenscreen_generation_gate"
    assert _get("qa.chroma_key_gate").name == "qa.chroma_key_gate"
    assert _get("pipeline.project_style_sheet").name == "pipeline.project_style_sheet"
