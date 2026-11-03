"""Tests for the oyasumi-gamedev graft: A1-A5 gates + B1/B2 engines.

Clean-room methods, restated in hevi's own words from
``hevi-vs-oyasumi-gamedev.md``. No site text, picture, or code is
reproduced. B1/B2 evidence is synthetic fixtures only.
"""

import hashlib
import json

import numpy as np
import pytest
from PIL import Image

from hevi.capabilities.camera_baseline_drop_gate import check_camera_sequence
from hevi.capabilities.effect_restraint_gate import check_effect_restraint
from hevi.capabilities.emotion_orientation_vocabulary import check_emotion_orientation
from hevi.capabilities.panel_contrast_gate import check_panel_contrast
from hevi.capabilities.parametric_pose_template import build_pose_template, render_pose_silhouette
from hevi.capabilities.single_image_sway import (
    _zone_mask,
    make_synthetic_base,
    render_single_image_sway,
    render_sway_frames,
)
from hevi.capabilities.stage_freeze_gate import check_stage_freeze


# ---------------------------------------------------------------- A1

def _panel_plan():
    return {
        "panels": [
            {"id": "p1", "importance": "low", "size_class": "small", "gutter_after_s": 0.5},
            {
                "id": "p2", "importance": "high", "size_class": "large",
                "contrast_basis": "twice the neighbours' area and still against their motion",
                "gutter_after_s": 2.0,
            },
            {"id": "p3", "importance": "medium", "size_class": "small", "gutter_after_s": 0.5},
        ]
    }


def test_a1_contrasted_page_passes():
    report = check_panel_contrast(_panel_plan())
    assert report["verdict"] == "pass"
    assert report["ok"] is True


def test_a1_missing_tier_fails():
    plan = _panel_plan()
    del plan["panels"][0]["importance"]
    report = check_panel_contrast(plan)
    assert report["verdict"] == "fail"
    assert any(i["code"] == "importance_undeclared" for i in report["issues"])


def test_a1_all_same_tier_fails():
    plan = _panel_plan()
    for panel in plan["panels"]:
        panel["importance"] = "medium"
    report = check_panel_contrast(plan)
    assert report["verdict"] == "fail"
    assert any(i["code"] == "no_contrast" for i in report["issues"])


def test_a1_standout_without_basis_fails():
    plan = _panel_plan()
    del plan["panels"][1]["contrast_basis"]
    report = check_panel_contrast(plan)
    assert report["verdict"] == "fail"
    assert any(i["code"] == "contrast_basis_missing" for i in report["issues"])


def test_a1_break_needs_two_cues():
    plan = _panel_plan()
    plan["panels"][1]["break_technique"] = "diagonal"
    plan["panels"][1]["order_cues"] = ["numbering"]
    report = check_panel_contrast(plan)
    assert report["verdict"] == "fail"
    assert any(i["code"] == "break_needs_two_cues" for i in report["issues"])
    plan["panels"][1]["order_cues"] = ["numbering", "gutter_width"]
    assert check_panel_contrast(plan)["verdict"] == "pass"


def test_a1_undeclared_gutter_is_not_checked():
    plan = {"panels": [
        {"id": "p1", "importance": "low", "size_class": "small"},
        {"id": "p2", "importance": "high", "size_class": "large", "contrast_basis": "size"},
    ]}
    report = check_panel_contrast(plan)
    assert report["verdict"] == "not_checked"
    assert report["ok"] is False


# ---------------------------------------------------------------- A2

def _shot_sequence():
    return {"shots": [
        {"id": "s1", "height": "eye", "distance": "medium", "role": "baseline"},
        {"id": "s2", "height": "eye", "distance": "medium", "role": "baseline"},
        {"id": "s3", "height": "low", "distance": "medium", "role": "drop"},
        {"id": "s4", "height": "low", "distance": "medium", "role": "bridge"},
    ]}


def test_a2_baseline_drop_bridge_passes():
    assert check_camera_sequence(_shot_sequence())["verdict"] == "pass"


def test_a2_short_baseline_fails():
    seq = _shot_sequence()
    seq["shots"] = seq["shots"][1:]
    report = check_camera_sequence(seq)
    assert report["verdict"] == "fail"
    assert any(i["code"] == "baseline_too_short" for i in report["issues"])


def test_a2_two_axis_drop_fails():
    seq = _shot_sequence()
    seq["shots"][2]["distance"] = "close"
    report = check_camera_sequence(seq)
    assert report["verdict"] == "fail"
    assert any(i["code"] == "drop_changes_two_axes" for i in report["issues"])


def test_a2_drop_without_bridge_fails():
    seq = _shot_sequence()
    seq["shots"][3]["role"] = "baseline"
    report = check_camera_sequence(seq)
    assert report["verdict"] == "fail"
    assert any(i["code"] == "drop_without_bridge" for i in report["issues"])


def test_a2_undeclared_tier_fails():
    seq = _shot_sequence()
    del seq["shots"][0]["height"]
    assert check_camera_sequence(seq)["verdict"] == "fail"


# ---------------------------------------------------------------- A3

def _pose_plan():
    return {
        "action_direction": "approach",
        "orientations": {
            "gaze": "toward", "face": "toward", "chest": "toward",
            "waist": "toward", "feet": "toward",
        },
        "face_visible": True,
    }


def test_a3_uniform_pose_passes():
    assert check_emotion_orientation(_pose_plan())["verdict"] == "pass"


def test_a3_undeclared_direction_fails():
    plan = _pose_plan()
    del plan["action_direction"]
    assert check_emotion_orientation(plan)["verdict"] == "fail"


def test_a3_misalignment_needs_intent():
    plan = _pose_plan()
    plan["orientations"]["feet"] = "away"
    assert check_emotion_orientation(plan)["verdict"] == "fail"
    plan["misalignment_intent"] = "feet already turning to leave"
    assert check_emotion_orientation(plan)["verdict"] == "pass"


def test_a3_face_body_conflict_needs_compound_emotion():
    plan = _pose_plan()
    plan["orientations"]["face"] = "toward"
    plan["orientations"]["chest"] = "away"
    plan["orientations"]["waist"] = "away"
    report = check_emotion_orientation(plan)
    assert report["verdict"] == "fail"
    assert any(i["code"] == "face_body_conflict_undeclared" for i in report["issues"])
    plan["composite_emotion"] = "smiling while pulling away"
    assert check_emotion_orientation(plan)["verdict"] == "pass"


def test_a3_faceless_needs_readability_basis():
    plan = _pose_plan()
    plan["face_visible"] = False
    assert check_emotion_orientation(plan)["verdict"] == "fail"
    plan["silhouette_readability"] = "shoulders and feet point at the door"
    assert check_emotion_orientation(plan)["verdict"] == "pass"


# ---------------------------------------------------------------- A4

def _effect_plan():
    return {"items": [
        {
            "id": "e1", "lead_effect": "gathering_lines",
            "effect_role": "pull the eye to the letter on the table",
            "overwhelms_subject": False,
            "layer_off_checked": True, "layer_off_changes_intent": True,
            "thresholds": {"density": 0.6},
            "measurements": {"density": 0.4},
        }
    ]}


def test_a4_restrained_effect_passes():
    assert check_effect_restraint(_effect_plan())["verdict"] == "pass"


def test_a4_two_lead_effects_fail():
    plan = _effect_plan()
    plan["items"][0]["lead_effect"] = ["gathering_lines", "speed_lines"]
    assert check_effect_restraint(plan)["verdict"] == "fail"


def test_a4_overwhelming_effect_fails():
    plan = _effect_plan()
    plan["items"][0]["overwhelms_subject"] = True
    assert check_effect_restraint(plan)["verdict"] == "fail"


def test_a4_redundant_effect_fails():
    plan = _effect_plan()
    plan["items"][0]["layer_off_changes_intent"] = False
    report = check_effect_restraint(plan)
    assert report["verdict"] == "fail"
    assert any(i["code"] == "effect_redundant" for i in report["issues"])


def test_a4_unchecked_is_not_checked():
    plan = _effect_plan()
    del plan["items"][0]["layer_off_checked"]
    report = check_effect_restraint(plan)
    assert report["verdict"] == "not_checked"


def test_a4_over_threshold_fails():
    plan = _effect_plan()
    plan["items"][0]["measurements"]["density"] = 0.9
    assert check_effect_restraint(plan)["verdict"] == "fail"


def test_a4_fixed_symbol_fails():
    plan = _effect_plan()
    plan["items"][0]["fixed_emotion_symbol"] = True
    assert check_effect_restraint(plan)["verdict"] == "fail"


# ---------------------------------------------------------------- A5

def _stage_plan():
    return {"stages": [
        {"name": "prototype", "frozen": True, "frozen_contents": ["question", "verdict"],
         "arrival_conditions_met": True},
        {"name": "vertical_slice", "frozen": True, "frozen_contents": ["one finished scene"],
         "arrival_conditions_met": True, "inputs_from": ["prototype"]},
        {"name": "alpha", "frozen": False, "frozen_contents": [],
         "arrival_conditions_met": False, "inputs_from": ["vertical_slice"]},
    ]}


def test_a5_frozen_chain_passes():
    assert check_stage_freeze(_stage_plan())["verdict"] == "pass"


def test_a5_unfrozen_input_fails():
    plan = _stage_plan()
    plan["stages"][1]["frozen"] = False
    report = check_stage_freeze(plan)
    assert report["verdict"] == "fail"
    assert any(i["code"] == "unfrozen_input" for i in report["issues"])


def test_a5_frozen_without_contents_fails():
    plan = _stage_plan()
    plan["stages"][0]["frozen_contents"] = []
    assert check_stage_freeze(plan)["verdict"] == "fail"


def test_a5_frozen_change_needs_review():
    plan = _stage_plan()
    plan["changes"] = [{"stage": "prototype", "re_review_declared": False}]
    assert check_stage_freeze(plan)["verdict"] == "fail"
    plan["changes"] = [{"stage": "prototype", "re_review_declared": True}]
    assert check_stage_freeze(plan)["verdict"] == "pass"


def test_a5_unknown_stage_fails():
    plan = _stage_plan()
    plan["stages"].append({"name": "gold", "frozen": False, "arrival_conditions_met": False})
    assert check_stage_freeze(plan)["verdict"] == "fail"


def test_a5_out_of_order_fails():
    plan = {"stages": [
        {"name": "alpha", "frozen": False, "arrival_conditions_met": True},
        {"name": "prototype", "frozen": True, "frozen_contents": ["q"],
         "arrival_conditions_met": True},
    ]}
    assert check_stage_freeze(plan)["verdict"] == "fail"


# ---------------------------------------------------------------- B1

def _sway_params():
    return {
        "synthetic": {
            "width": 120, "height": 90, "background": [255, 255, 255],
            "shapes": [
                {"kind": "rect", "color": [34, 139, 34], "box": [10, 10, 50, 40]},
                {"kind": "circle", "color": [220, 20, 20], "center": [90, 60], "radius": 15},
            ],
        },
        "sway_kinds": {
            "gentle_sway": {"waveform": "sine", "axis": "horizontal"},
            "flag_flutter": {"waveform": "triangle", "axis": "vertical"},
        },
        "zones": [
            {"name": "leaves", "color": [34, 139, 34], "tolerance": 0,
             "sway_kind": "gentle_sway", "amplitude_px": 3, "speed_hz": 1.0, "phase": 0.0},
            {"name": "flag", "color": [220, 20, 20], "tolerance": 0,
             "sway_kind": "flag_flutter", "amplitude_px": 2, "speed_hz": 2.0, "phase": 0.0},
        ],
        "frames": 6,
        "fps": 6,
    }


def test_b1_sway_renders_and_zones_do_not_bleed(tmp_path):
    params = _sway_params()
    report = render_single_image_sway(params, tmp_path / "sway")
    assert report["verdict"] == "pass"
    assert len(report["frame_records"]) == 6
    assert (tmp_path / "sway" / "sway.mp4").exists()
    frames = [np.array(Image.open(tmp_path / "sway" / "frames" / r["file"])) for r in report["frame_records"]]
    assert any(not np.array_equal(frames[0], frame) for frame in frames[1:])
    # A pixel far from every zone is byte-identical in every frame.
    assert all(tuple(frame[85, 5]) == tuple(frames[0][85, 5]) for frame in frames)


def test_b1_two_runs_are_hash_identical(tmp_path):
    first = render_single_image_sway(_sway_params(), tmp_path / "a")
    second = render_single_image_sway(_sway_params(), tmp_path / "b")
    assert [r["sha256"] for r in first["frame_records"]] == [r["sha256"] for r in second["frame_records"]]
    assert first["video_sha256"] == second["video_sha256"]


def test_b1_unknown_sway_kind_fails(tmp_path):
    params = _sway_params()
    params["zones"][0]["sway_kind"] = "not_declared"
    report = render_single_image_sway(params, tmp_path / "sway")
    assert report["verdict"] == "fail"


def test_b1_zone_mask_matches_only_its_colour():
    base = make_synthetic_base(_sway_params()["synthetic"])
    mask = _zone_mask(base, (34, 139, 34), 0)
    assert mask[20, 20]
    assert not mask[60, 90]
    assert not mask[85, 5]


def test_b1_zero_amplitude_is_still():
    base = make_synthetic_base(_sway_params()["synthetic"])
    zones = [{"name": "leaves", "color": (34, 139, 34), "tolerance": 0,
              "waveform": "sine", "axis": "horizontal",
              "amplitude_px": 0.0, "speed_hz": 1.0, "phase": 0.0}]
    frames = render_sway_frames(base, zones, 4, 6)
    assert all(np.array_equal(frames[0], frame) for frame in frames)


# ---------------------------------------------------------------- B2

def _pose_spec():
    return {
        "template_name": "walk_cycle",
        "action": "walk",
        "parameters": {"stride": 0.6, "speed": 1.2},
        "ranges": {"stride": [0.2, 1.0], "speed": [0.5, 2.0]},
        "joints": {
            "shoulder_l": 20, "shoulder_r": -20, "hip_l": -20, "hip_r": 20,
            "waist_twist": 10, "chest_twist": -10,
            "elbow_l": 5, "elbow_r": 5, "knee_l": 10, "knee_r": 10,
            "spine_lean": 5, "head_tilt": 0,
        },
        "constraints": ["counter_swing", "counter_twist"],
        "gaze_direction": "toward",
    }


def test_b2_pose_template_passes_and_emits_json(tmp_path):
    result = build_pose_template(_pose_spec())
    assert result["verdict"] == "pass"
    pose = result["pose"]
    assert pose["synthetic"] is True
    assert pose["joints_deg"]["shoulder_l"] == 20
    silhouette = render_pose_silhouette(pose, tmp_path / "silhouette.png")
    assert silhouette.exists()
    assert hashlib.sha256(silhouette.read_bytes()).hexdigest()


def test_b2_three_parameter_sets_differ(tmp_path):
    variants = []
    for stride, speed in ((0.3, 0.8), (0.6, 1.2), (0.9, 1.8)):
        spec = _pose_spec()
        spec["parameters"] = {"stride": stride, "speed": speed}
        spec["joints"]["shoulder_l"] = int(30 * stride)
        spec["joints"]["hip_r"] = int(30 * stride)
        result = build_pose_template(spec)
        assert result["verdict"] == "pass"
        path = tmp_path / f"pose_{stride}.png"
        render_pose_silhouette(result["pose"], path)
        variants.append(hashlib.sha256(path.read_bytes()).hexdigest())
    assert len(set(variants)) == 3


def test_b2_out_of_range_fails():
    spec = _pose_spec()
    spec["parameters"]["stride"] = 1.5
    report = build_pose_template(spec)
    assert report["verdict"] == "fail"
    assert any(i["code"] == "parameter_out_of_range" for i in report["issues"])


def test_b2_counter_swing_violation_fails():
    spec = _pose_spec()
    spec["joints"]["hip_r"] = -20
    report = build_pose_template(spec)
    assert report["verdict"] == "fail"
    assert any(i["code"] == "counter_swing_violated" for i in report["issues"])


def test_b2_counter_twist_violation_fails():
    spec = _pose_spec()
    spec["joints"]["chest_twist"] = 10
    report = build_pose_template(spec)
    assert report["verdict"] == "fail"
    assert any(i["code"] == "counter_twist_violated" for i in report["issues"])


def test_b2_missing_gaze_fails():
    spec = _pose_spec()
    del spec["gaze_direction"]
    assert build_pose_template(spec)["verdict"] == "fail"


def test_b2_unknown_constraint_fails():
    spec = _pose_spec()
    spec["constraints"] = ["teleport"]
    assert build_pose_template(spec)["verdict"] == "fail"


# ---------------------------------------------------------------- registry

def test_registry_registers_all_seven():
    from hevi.capabilities.registry import get as registry_get

    for name in (
        "qa.panel_contrast_gate",
        "qa.camera_baseline_drop_gate",
        "qa.emotion_orientation_vocabulary",
        "qa.effect_restraint_gate",
        "qa.stage_freeze_gate",
        "video.single_image_sway",
        "qa.parametric_pose_template",
    ):
        assert registry_get(name) is not None, name
