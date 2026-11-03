"""Offline tests for the motion-method gates (clean-room intake).

Fixtures are invented for these tests only: a fictional tea-shop
explainer, invented word timings and invented baseline ids. No upstream
research file, sample, demo media, font or prompt text is reused.
No network, no paid calls, no rendering, no real ASR model.
"""

from __future__ import annotations

import pytest

import hevi.capabilities as caps
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.motion_gates import (
    build_semantic_shot_list,
    check_caption_plan,
    check_reuse_baseline,
    check_sample_first,
    clear_transcript_cache,
    request_transcript,
    verify_cached_transcript,
)

NAMES = [
    "edit.semantic_shot_list",
    "edit.reuse_baseline_gate",
    "audio.transcript_once",
    "qa.sample_first_gate",
    "edit.caption_plan_gate",
]


def test_registered_names():
    for name in NAMES:
        assert caps.contains(name), name


def _shots():
    return [
        {"id": "s1", "start_sec": 0.0, "end_sec": 5.0, "meaning": "Tea shop opens at dawn",
         "focus": "the kettle", "main_effect": "steam rise", "aux_effects": ["light warm"],
         "enter": "fade in", "exit": "pan right", "readable_window_sec": 4.0,
         "handoff_to": "s2"},
        {"id": "s2", "start_sec": 5.0, "end_sec": 10.0, "meaning": "First customer arrives",
         "focus": "the door", "main_effect": "door swing", "aux_effects": [],
         "enter": "pan right", "exit": "cut to counter", "readable_window_sec": 4.0,
         "handoff_to": None},
    ]


def _shot_plan():
    return {"shots": _shots(),
            "transitions": [{"from_shot": "s1", "to_shot": "s2", "reason": "sequence"}]}


# ------------------------------------------------------------ 1. shot list

def test_shot_list_pass_and_chinese_reason():
    plan = _shot_plan()
    plan["transitions"] = [{"from_shot": "s1", "to_shot": "s2", "reason": "深入"}]
    out = build_semantic_shot_list(plan)
    assert out["verdict"] == "pass"
    assert out["shot_count"] == 2
    assert out["transitions"][0]["reason"] == "deepen"
    assert out["render_status"] == "plan_only_no_render"


def test_shot_list_single_shot_needs_no_transition():
    plan = {"shots": [_shots()[0]], "transitions": []}
    plan["shots"][0]["handoff_to"] = None
    out = build_semantic_shot_list(plan)
    assert out["verdict"] == "pass" and out["transition_count"] == 0


def test_shot_list_single_title_card_allowed_but_repeat_blocked():
    ok = _shot_plan()
    ok["shots"][0]["title_card"] = True
    ok["shots"][0]["center_card"] = True
    assert build_semantic_shot_list(ok)["title_center_card_count"] == 1
    bad = _shot_plan()
    for shot in bad["shots"]:
        shot["title_card"] = True
        shot["center_card"] = True
    with pytest.raises(CapabilityError, match="title-plus-center-card"):
        build_semantic_shot_list(bad)


def test_shot_list_illegal_inputs():
    with pytest.raises(CapabilityError):
        build_semantic_shot_list({"shots": []})
    with pytest.raises(CapabilityError):
        build_semantic_shot_list("not-a-plan")
    two_focus = _shot_plan()
    two_focus["shots"][0]["focuses"] = ["kettle", "door"]
    with pytest.raises(CapabilityError, match="exactly one main focus"):
        build_semantic_shot_list(two_focus)
    generic_reason = _shot_plan()
    generic_reason["transitions"][0]["reason"] = "fade"
    with pytest.raises(CapabilityError, match="not a semantic reason"):
        build_semantic_shot_list(generic_reason)
    missing_transition = _shot_plan()
    missing_transition["transitions"] = []
    with pytest.raises(CapabilityError, match="no transition"):
        build_semantic_shot_list(missing_transition)
    bad_window = _shot_plan()
    bad_window["shots"][0]["readable_window_sec"] = 99.0
    with pytest.raises(CapabilityError, match="readable_window"):
        build_semantic_shot_list(bad_window)
    unknown_handoff = _shot_plan()
    unknown_handoff["shots"][0]["handoff_to"] = "nope"
    with pytest.raises(CapabilityError, match="unknown shot"):
        build_semantic_shot_list(unknown_handoff)


# ------------------------------------------------------------ 2. reuse gate

def _reuse_ok():
    return {
        "baseline": {"id": "tea-shop-v1", "code": "tea-shop-code-v1", "font": "tea-font-v1",
                     "licensed_assets": ["tea-photo-a"]},
        "reuse": {"inherits": ["tea-shop-code-v1", "tea-photo-a"],
                  "new_content": {"semantic_events": ["door opens"],
                                  "subtitles": ["Tea shop opens at dawn"],
                                  "asset_map": {"kettle": "kettle-v2"}}},
    }


def test_reuse_approved_inherits_only_registered():
    out = check_reuse_baseline(_reuse_ok())
    assert out["verdict"] == "approved"
    assert out["is_new_film"] is True
    assert out["default_card_rebuild"] is False
    assert out["fallback_used"] is None


def test_reuse_missing_baseline_reports_missing_no_fallback():
    out = check_reuse_baseline({"reuse": {"inherits": [], "new_content": None}})
    assert out["verdict"] == "blocked"
    assert out["missing"] == ["baseline"]
    assert out["default_card_rebuild"] is False


def test_reuse_missing_fields_and_unknown_and_stale_updates():
    req = _reuse_ok()
    del req["baseline"]["font"]
    out = check_reuse_baseline(req)
    assert out["verdict"] == "blocked" and "baseline.font" in out["missing"]
    req = _reuse_ok()
    req["reuse"]["inherits"] = ["not-registered"]
    out = check_reuse_baseline(req)
    assert out["verdict"] == "blocked" and out["unknown_inherits"] == ["not-registered"]
    req = _reuse_ok()
    req["reuse"]["new_content"]["subtitles"] = []
    out = check_reuse_baseline(req)
    assert out["verdict"] == "blocked" and "new_content.subtitles" in out["missing_updates"]
    with pytest.raises(CapabilityError):
        check_reuse_baseline({"reuse": "not-a-dict"})


# ------------------------------------------------------------ 3. transcript once

def _words():
    return [{"word": "tea", "start_sec": 0.0, "end_sec": 0.5},
            {"word": "shop", "start_sec": 0.5, "end_sec": 1.0},
            {"word": "opens", "start_sec": 1.0, "end_sec": 1.5}]


def test_transcript_store_hit_verify_and_blocks():
    clear_transcript_cache()
    req = {"media_id": "tea-1", "source_hash": "hash-a", "language": "en",
           "words": _words(), "duration_sec": 1.5}
    first = request_transcript(req)
    assert first["status"] == "stored" and first["verified"] is False
    hit = request_transcript({"media_id": "tea-1", "source_hash": "hash-a", "language": "en",
                              "duration_sec": 1.5, "expected_proper_nouns": ["tea"]})
    assert hit["status"] == "cache_hit" and hit["verified"] is False and hit["gaps"] == []
    hit_bad_lang = request_transcript({"media_id": "tea-1", "source_hash": "hash-a",
                                       "language": "fr"})
    assert "language_mismatch" in hit_bad_lang["gaps"]
    assert hit_bad_lang["verified"] is False
    dup = request_transcript({"media_id": "tea-1", "source_hash": "hash-a",
                              "words": [{"word": "other", "start_sec": 0.0, "end_sec": 0.5}]})
    assert dup["status"] == "blocked" and dup["reason"] == "duplicate_transcribe_blocked"
    second_impl = request_transcript({"media_id": "tea-1", "source_hash": "hash-a",
                                      "implementation": "other-engine"})
    assert second_impl["status"] == "blocked" and second_impl["reason"] == "second_implementation_blocked"
    full = request_transcript({"media_id": "tea-1", "source_hash": "hash-a", "full_rerun": True})
    assert full["status"] == "blocked" and full["reason"] == "full_rerun_blocked"
    assert full["resume_from_sec"] == 1.5
    verified = verify_cached_transcript("tea-1", "hash-a", "reviewer-1")
    assert verified["status"] == "verified"
    clear_transcript_cache()


def test_transcript_pending_never_fabricates_or_switches():
    clear_transcript_cache()
    no_audio = request_transcript({"media_id": "m1", "source_hash": "h1", "audio_present": False})
    assert no_audio["status"] == "pending" and no_audio["reason"] == "missing_audio"
    no_model = request_transcript({"media_id": "m2", "source_hash": "h2",
                                   "model_available": False, "provider": "faster-whisper"})
    assert no_model["status"] == "pending" and no_model["reason"] == "missing_model_weights"
    assert no_model["switched_provider"] is None
    no_payload = request_transcript({"media_id": "m3", "source_hash": "h3"})
    assert no_payload["status"] == "pending" and no_payload["reason"] == "awaiting_transcript"
    with pytest.raises(CapabilityError):
        request_transcript({"media_id": "m4"})
    with pytest.raises(CapabilityError):
        verify_cached_transcript("ghost", "hash-x", "reviewer-1")
    clear_transcript_cache()


def test_transcript_coverage_gap_on_hit():
    clear_transcript_cache()
    request_transcript({"media_id": "tea-2", "source_hash": "hash-b", "words": _words()})
    hit = request_transcript({"media_id": "tea-2", "source_hash": "hash-b", "duration_sec": 10.0})
    assert "coverage_gap" in hit["gaps"]
    with pytest.raises(CapabilityError, match="open gaps"):
        verify_cached_transcript("tea-2", "hash-b", "reviewer-1", duration_sec=10.0)
    clear_transcript_cache()


# ------------------------------------------------------------ 4. sample first

def test_sample_default_requires_15_to_20_and_acceptance():
    assert check_sample_first({})["verdict"] == "sample_required"
    sample = {"duration_sec": 18.0, "covers_full_meaning": True,
              "tech_checks_passed": True, "user_accepted": False}
    out = check_sample_first({"sample": sample})
    assert out["verdict"] == "awaiting_user_acceptance"
    assert out["can_expand_to_full"] is False
    blocked = check_sample_first({"sample": sample, "expand_to_full": True})
    assert blocked["verdict"] == "blocked"
    sample["user_accepted"] = True
    ok = check_sample_first({"sample": sample, "expand_to_full": True})
    assert ok["verdict"] == "approved" and ok["can_expand_to_full"] is True


def test_sample_boundaries_and_explicit_bypass():
    for duration in (15.0, 20.0):
        out = check_sample_first({"sample": {"duration_sec": duration, "covers_full_meaning": True,
                                             "tech_checks_passed": True, "user_accepted": True}})
        assert out["verdict"] == "approved", duration
    for duration in (14.9, 20.1):
        out = check_sample_first({"sample": {"duration_sec": duration, "covers_full_meaning": True,
                                             "tech_checks_passed": True, "user_accepted": True}})
        assert out["verdict"] == "blocked" and out["reason"] == "duration_out_of_window"
    fragment = check_sample_first({"sample": {"duration_sec": 18.0, "covers_full_meaning": False,
                                              "tech_checks_passed": True, "user_accepted": True}})
    assert fragment["verdict"] == "blocked" and fragment["reason"] == "meaning_incomplete"
    full = check_sample_first({"explicit_full_film": True})
    assert full["verdict"] == "approved_explicit_bypass" and full["can_expand_to_full"] is True
    other = check_sample_first({"explicit_duration_request_sec": 60.0})
    assert other["sample_duration_sec"] == 60.0
    with pytest.raises(CapabilityError):
        check_sample_first({"sample": {"duration_sec": "long"}})


# ------------------------------------------------------------ 5. caption plan

def test_caption_missing_blocked_and_explicit_decline_allowed():
    blocked = check_caption_plan({"has_voice": True})
    assert blocked["verdict"] == "blocked" and blocked["missing"] == ["captions"]
    declined = check_caption_plan({"has_voice": True, "captions_explicitly_declined": True})
    assert declined["verdict"] == "approved" and declined["captions_enabled"] is False
    sneaky = check_caption_plan({"has_voice": True, "captions": {"enabled": False}})
    assert sneaky["verdict"] == "blocked"
    allowed = check_caption_plan({"has_voice": True, "captions_explicitly_declined": True,
                                  "captions": {"enabled": False}})
    assert allowed["verdict"] == "approved"


def test_caption_geometry_does_not_cover_main_visual():
    ok = check_caption_plan({"has_voice": True,
                             "captions": {"enabled": True, "position": "bottom",
                                          "frame_height_px": 1920, "band_height_px": 200,
                                          "subtitle_rect": {"x": 80, "y": 1600, "w": 920, "h": 200}},
                             "main_visual_rect": {"x": 0, "y": 0, "w": 1080, "h": 1200}})
    assert ok["verdict"] == "approved" and ok["main_visual_safe"] is True
    overlap = check_caption_plan({"has_voice": True,
                                  "captions": {"enabled": True, "position": "bottom",
                                               "subtitle_rect": {"x": 0, "y": 500, "w": 1080, "h": 200}},
                                  "main_visual_rect": {"x": 0, "y": 0, "w": 1080, "h": 1200}})
    assert overlap["verdict"] == "blocked"
    center = check_caption_plan({"has_voice": True, "captions": {"enabled": True, "position": "center"}})
    assert center["verdict"] == "blocked"
    tall = check_caption_plan({"has_voice": True, "captions": {"enabled": True, "position": "bottom",
                                                               "frame_height_px": 1000, "band_height_px": 400}})
    assert tall["verdict"] == "blocked"
    no_voice = check_caption_plan({"has_voice": False, "captions": {"enabled": False}})
    assert no_voice["verdict"] == "approved"
    with pytest.raises(CapabilityError):
        check_caption_plan({"has_voice": "yes"})
    with pytest.raises(CapabilityError):
        check_caption_plan("not-a-plan")
