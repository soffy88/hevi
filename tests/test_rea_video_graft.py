"""Tests for the rea-video graft (clean-room).

A gates judge records; B1 measures synthetic colour clips made
locally with ffmpeg; B2/B3/B4 judge documents and plans. No
upstream code, YAML, video, key, or model is involved anywhere
in this file, and no upstream accuracy figure is used as a
threshold.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from hevi.capabilities import get as _get_capability
from hevi.capabilities.capability_map_schema import validate_capability_map
from hevi.capabilities.cost_tier_confirmation_gate import check_cost_tier_confirmation
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.evidence_priority_gate import check_evidence_priority
from hevi.capabilities.forensic_evidence_executor import analyze_video
from hevi.capabilities.generation_unit_splitter import split_generation_units
from hevi.capabilities.production_method_vocabulary import check_production_method_labels
from hevi.capabilities.real_material_isolation_gate import check_real_material_isolation
from hevi.capabilities.review_fusion_gate import check_review_fusion
from hevi.capabilities.sound_source_labels_gate import check_sound_sources
from hevi.capabilities.three_track_contract import check_three_track_contract

FFMPEG_OK = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None

EXPECTED = [
    "qa.production_method_vocabulary",
    "qa.evidence_priority_gate",
    "qa.real_material_isolation_gate",
    "qa.sound_source_labels_gate",
    "qa.review_fusion_gate",
    "qa.cost_tier_confirmation_gate",
    "qa.forensic_evidence_executor",
    "model.capability_map_schema",
    "story.generation_unit_splitter",
    "audio.three_track_contract",
]


@pytest.mark.parametrize("name", EXPECTED)
def test_capabilities_registered(name):
    assert _get_capability(name) is not None


# ---- A1 ----

def _label_plan():
    return {
        "shots": [
            {"id": "s1", "label": "live_action",
             "evidence": {"kind": "human_review", "ref": "reviewer-1"}},
            {"id": "s2", "label": "ai_video",
             "evidence": {"kind": "aigc_marker", "ref": "marker-offset-12"}},
        ],
        "overlays": [{"shot_id": "s1", "kind": "subtitle"}],
    }


def test_a1_pass():
    assert check_production_method_labels(_label_plan())["ok"] is True


def test_a1_unknown_label():
    plan = _label_plan()
    plan["shots"][0]["label"] = "hologram"
    report = check_production_method_labels(plan)
    assert report["verdict"] == "fail"
    assert any("unknown_label" in i for i in report["issues"])


def test_a1_unbound_label():
    plan = _label_plan()
    del plan["shots"][0]["evidence"]
    report = check_production_method_labels(plan)
    assert any("unbound_label" in i for i in report["issues"])


def test_a1_overlay_in_base_label():
    plan = _label_plan()
    plan["shots"][0]["label"] = "subtitle"
    report = check_production_method_labels(plan)
    assert any("overlay_in_base_label" in i for i in report["issues"])


# ---- A2 ----

def _review():
    return {
        "shots": [
            {"id": "s1", "tool_label": "ai_video", "reviewer_label": "ai_video",
             "hard_evidence": {"kind": "aigc_marker", "supports": "ai_video"},
             "reviewer_saw_images": True, "must_watch": False},
        ]
    }


def test_a2_pass():
    assert check_evidence_priority(_review())["ok"] is True


def test_a2_hard_evidence_overruled():
    review = _review()
    review["shots"][0]["reviewer_label"] = "live_action"
    review["shots"][0]["must_watch"] = True
    report = check_evidence_priority(review)
    assert any("hard_evidence_overruled" in i for i in report["issues"])


def test_a2_disagreement_not_flagged():
    review = _review()
    review["shots"][0]["reviewer_label"] = "3d_render"
    del review["shots"][0]["hard_evidence"]
    report = check_evidence_priority(review)
    assert any("disagreement_not_flagged" in i for i in report["issues"])


def test_a2_blind_override():
    review = _review()
    review["shots"][0]["reviewer_label"] = "3d_render"
    review["shots"][0]["reviewer_saw_images"] = False
    review["shots"][0]["must_watch"] = True
    del review["shots"][0]["hard_evidence"]
    report = check_evidence_priority(review)
    assert any("blind_override" in i for i in report["issues"])


# ---- A3 ----

def test_a3_pass():
    plan = {
        "user_assets": [{"id": "photo1", "kind": "photo", "confirmed": True,
                         "confirmation_ref": "owner-note-1"}],
        "embedded": [{"id": "e1", "status": "real_or_ai_unconfirmed"}],
        "steps": [{"id": "st1", "action": "use_asset", "target_asset_id": "photo1"}],
    }
    assert check_real_material_isolation(plan)["ok"] is True


def test_a3_model_substitute_fails():
    plan = {
        "user_assets": [{"id": "photo1", "kind": "photo"}],
        "embedded": [],
        "steps": [{"id": "st1", "action": "generate", "target_asset_id": "photo1"}],
    }
    report = check_real_material_isolation(plan)
    assert any("model_substitute_for_real" in i for i in report["issues"])


def test_a3_confirmed_without_ref_fails():
    plan = {
        "user_assets": [],
        "embedded": [{"id": "e1", "status": "confirmed_real"}],
        "steps": [],
    }
    report = check_real_material_isolation(plan)
    assert any("unconfirmed_confirmation" in i for i in report["issues"])


# ---- A4 ----

def _sound_plan():
    return {
        "tracks": {
            "voice": {"source": "on_camera", "confidence": 0.9},
            "music": {"source": "library_lean", "confidence": 0.6,
                      "confirmation_method": "ask_owner", "status": "pending"},
            "sfx": [{"candidate": "door_slam", "confidence": 0.3, "candidate": True}],
        }
    }


def test_a4_pass():
    assert check_sound_sources(_sound_plan())["ok"] is True


def test_a4_missing_track():
    plan = _sound_plan()
    del plan["tracks"]["voice"]
    assert any("unlabelled_track" in i for i in check_sound_sources(plan)["issues"])


def test_a4_sfx_overconfident():
    plan = _sound_plan()
    plan["tracks"]["sfx"][0]["confidence"] = 0.9
    report = check_sound_sources(plan)
    assert any("sfx_overconfident" in i for i in report["issues"])


def test_a4_music_without_confirmation_method():
    plan = _sound_plan()
    del plan["tracks"]["music"]["confirmation_method"]
    report = check_sound_sources(plan)
    assert any("music_unconfirmed" in i for i in report["issues"])


# ---- A5 ----

def _fusion():
    return {
        "deterministic_weight": 0.6,
        "hard_constraints": ["frozen_frame_not_generated", "rigid_push_pull_not_live"],
        "verdicts": [
            {"shot_id": "s1", "tool_label": "ai_video", "reviewer_label": "ai_video",
             "final_label": "ai_video", "must_watch": False},
        ],
    }


def test_a5_pass():
    assert check_review_fusion(_fusion())["ok"] is True


def test_a5_weight_mismatch():
    record = _fusion()
    record["deterministic_weight"] = 0.5
    assert any("weight_mismatch" in i for i in check_review_fusion(record)["issues"])


def test_a5_missing_constraint():
    record = _fusion()
    record["hard_constraints"] = ["frozen_frame_not_generated"]
    assert any("missing_hard_constraint" in i for i in check_review_fusion(record)["issues"])


def test_a5_frozen_frame_constraint():
    record = _fusion()
    record["verdicts"][0]["frozen_frame"] = True
    assert any("hard_constraint_broken" in i for i in check_review_fusion(record)["issues"])


# ---- A6 ----

def _cost_plan():
    return {
        "tiers": [
            {"tier": "G1", "confirmed": True, "confirmation_ref": "c1"},
            {"tier": "G2", "confirmed": True, "confirmation_ref": "c2"},
            {"tier": "G3", "confirmed": True, "confirmation_ref": "c3"},
            {"tier": "G4", "confirmed": True, "confirmation_ref": "c4"},
        ],
        "units": [{"id": "u1", "cache_key": {"input_hash": "abc", "model": "m1",
                                             "params": {"a": 1}}}],
        "h3_entries": [{"id": "h1", "tier": "h3_api_15s", "tier_max_s": 15}],
    }


def test_a6_pass():
    assert check_cost_tier_confirmation(_cost_plan())["ok"] is True


def test_a6_tier_skipped():
    plan = _cost_plan()
    plan["tiers"][1]["confirmed"] = False
    del plan["tiers"][1]["confirmation_ref"]
    report = check_cost_tier_confirmation(plan)
    assert any("tier_skipped" in i for i in report["issues"])


def test_a6_h3_unpartitioned():
    plan = _cost_plan()
    plan["h3_entries"] = [{"id": "h1", "tier": "h3", "tier_max_s": 20}]
    report = check_cost_tier_confirmation(plan)
    assert any("h3_tier_unpartitioned" in i for i in report["issues"])


def test_a6_bad_cache_key():
    plan = _cost_plan()
    plan["units"][0]["cache_key"] = {"input_hash": "abc"}
    assert any("bad_cache_key" in i for i in check_cost_tier_confirmation(plan)["issues"])


# ---- B1 ----

def _ffmpeg(args, **kwargs):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args],
                   check=True, timeout=120, **kwargs)


@pytest.mark.skipif(not FFMPEG_OK, reason="ffmpeg/ffprobe not available")
def test_b1_cuts_and_frozen(tmp_path):
    red = tmp_path / "red.mp4"
    blue = tmp_path / "blue.mp4"
    _ffmpeg(["-f", "lavfi", "-i", "color=c=red:s=64x36:d=1:r=10", str(red)])
    _ffmpeg(["-f", "lavfi", "-i", "color=c=blue:s=64x36:d=1:r=10", str(blue)])
    concat = tmp_path / "list.txt"
    concat.write_text(f"file '{red}'\nfile '{blue}'\n", encoding="utf-8")
    cut_video = tmp_path / "cuts.mp4"
    _ffmpeg(["-f", "concat", "-safe", "0", "-i", str(concat), "-c", "copy", str(cut_video)])
    report = analyze_video(cut_video, cut_threshold=20.0, frozen_epsilon=1.0,
                           min_frozen_frames=5)
    assert report["frame_count"] == 20
    assert [c["after_frame"] for c in report["cuts"]] == [10]
    frozen_video = tmp_path / "frozen.mp4"
    _ffmpeg(["-f", "lavfi", "-i", "color=c=red:s=64x36:d=3:r=10", str(frozen_video)])
    frozen = analyze_video(frozen_video, cut_threshold=20.0, frozen_epsilon=1.0,
                           min_frozen_frames=5)
    assert frozen["cuts"] == []
    assert frozen["frozen_runs"] and frozen["frozen_runs"][0]["frames"] == 30


@pytest.mark.skipif(not FFMPEG_OK, reason="ffmpeg/ffprobe not available")
def test_b1_repeated_frames_estimate_source_fps(tmp_path):
    src = tmp_path / "src.mp4"
    _ffmpeg(["-f", "lavfi", "-i", "testsrc=s=64x36:d=1:r=10", str(src)])
    upsampled = tmp_path / "up.mp4"
    _ffmpeg(["-i", str(src), "-vf", "fps=30", "-r", "30", str(upsampled)])
    report = analyze_video(upsampled, cut_threshold=20.0, frozen_epsilon=1.0,
                           min_frozen_frames=5)
    assert report["repeated_frame_ratio"] > 0.5
    assert 8.0 <= report["estimated_source_fps"] <= 12.0


def test_b1_missing_threshold_raises(tmp_path):
    with pytest.raises(CapabilityError):
        analyze_video(tmp_path / "none.mp4", cut_threshold=None,
                      frozen_epsilon=1.0, min_frozen_frames=5)


# ---- B2 ----

def _capability_doc():
    return {
        "signals": ["histogram_jump"],
        "primitives": [{"id": "cut_detect", "kind": "analysis"}],
        "models": [
            {"id": "route_a", "primitive_ids": ["cut_detect"],
             "boundary": "cuts only",
             "price": {"amount": 0.04, "unit": "usd/s", "source": "third-party",
                       "verified": False},
             "license": "conditional", "verified_date": "2026-11-03",
             "confidence": "medium"},
            {"id": "minimax_h3_route", "primitive_ids": ["cut_detect"],
             "boundary": "4-15s", "tier": "h3_api_15s",
             "price": {"amount": 0.04, "unit": "usd/s", "source": "third-party",
                       "verified": False},
             "license": "conditional", "verified_date": "2026-11-03",
             "confidence": "medium"},
        ],
    }


def test_b2_pass():
    report = validate_capability_map(_capability_doc(), today="2026-11-03")
    assert report["ok"] is True


def test_b2_stale_entry():
    report = validate_capability_map(_capability_doc(), today="2027-03-01")
    assert any("stale_entry" in i for i in report["issues"])
    assert report["stale_entries"] == ["route_a", "minimax_h3_route"]


def test_b2_price_claimed_verified_fails():
    doc = _capability_doc()
    doc["models"][0]["price"]["verified"] = True
    assert any("price_claimed_verified" in i
               for i in validate_capability_map(doc, today="2026-11-03")["issues"])


def test_b2_h3_unpartitioned_fails():
    doc = _capability_doc()
    del doc["models"][1]["tier"]
    assert any("h3_tier_unpartitioned" in i
               for i in validate_capability_map(doc, today="2026-11-03")["issues"])


def test_b2_dangling_primitive_fails():
    doc = _capability_doc()
    doc["models"][0]["primitive_ids"] = ["nope"]
    assert any("dangling_primitive" in i
               for i in validate_capability_map(doc, today="2026-11-03")["issues"])


# ---- B3 ----

def _shots():
    return [
        {"id": "s1", "scene": "room", "start_s": 0.0, "end_s": 6.0,
         "action_pause_after": True, "has_text_ui": False},
        {"id": "s2", "scene": "room", "start_s": 6.0, "end_s": 12.0,
         "action_pause_after": True, "has_text_ui": True},
        {"id": "s3", "scene": "street", "start_s": 12.0, "end_s": 18.0,
         "action_pause_after": True, "has_text_ui": False},
    ]


def test_b3_merge_and_carryover():
    report = split_generation_units(_shots())
    assert [u["shot_ids"] for u in report["units"]] == [["s1", "s2"], ["s3"]]
    assert report["units"][1]["tail_frame_carryover_from"] == "s2"
    assert report["code_layer"][0]["shot_id"] == "s2"
    assert report["ok"] is True


def test_b3_split_at_pause_over_ceiling():
    shots = [
        {"id": "s1", "scene": "room", "start_s": 0.0, "end_s": 10.0,
         "action_pause_after": True, "has_text_ui": False},
        {"id": "s2", "scene": "room", "start_s": 10.0, "end_s": 20.0,
         "action_pause_after": True, "has_text_ui": False},
    ]
    report = split_generation_units(shots)
    assert len(report["units"]) == 2


def test_b3_overlong_without_pause_raises():
    shots = [
        {"id": "s1", "scene": "room", "start_s": 0.0, "end_s": 10.0,
         "action_pause_after": False, "has_text_ui": False},
        {"id": "s2", "scene": "room", "start_s": 10.0, "end_s": 20.0,
         "action_pause_after": True, "has_text_ui": False},
    ]
    with pytest.raises(CapabilityError):
        split_generation_units(shots)


# ---- B4 ----

def _contract_plan():
    return {
        "separation": {"method": "caller_stems", "record_ref": "stems-1"},
        "tracks": {
            "voice": {"source": "on_camera", "confidence": 0.9},
            "music": {"source": "library", "confidence": 0.7,
                      "tempo": {"bpm": 120, "method": "onset_autocorrelation"},
                      "key": {"tonality": "C major", "method": "krumhansl"}},
            "sfx": [{"candidate": "door", "confidence": 0.3, "candidate": True}],
        },
    }


def test_b4_pass():
    report = check_three_track_contract(_contract_plan())
    assert report["ok"] is True
    assert report["separation_performed_here"] is False


def test_b4_separation_undeclared():
    plan = _contract_plan()
    del plan["separation"]
    assert any("separation_undeclared" in i
               for i in check_three_track_contract(plan)["issues"])


def test_b4_sfx_overconfident():
    plan = _contract_plan()
    plan["tracks"]["sfx"][0]["confidence"] = 0.8
    assert any("sfx_overconfident" in i
               for i in check_three_track_contract(plan)["issues"])


def test_b4_measurement_without_method():
    plan = _contract_plan()
    del plan["tracks"]["music"]["tempo"]["method"]
    assert any("measurement_without_method" in i
               for i in check_three_track_contract(plan)["issues"])
