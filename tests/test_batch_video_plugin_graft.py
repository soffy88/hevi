"""Tests for the batch-video-plugin graft (A1-A6 gates, B1-B4 fake contracts)."""

import pytest

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import contains

from hevi.capabilities import (
    round_cap_gate as a1,
    stale_round_watchdog_gate as a2,
    spec_authenticity_dual_track_gate as a3,
    dialogue_unverified_gate as a4,
    ai_disclosure_dual_track_gate as a5,
    failed_shot_no_hard_cut_gate as a6,
    review_signal_vocabulary as b1,
    edit_plan_compiler as b2,
    round_engine_contract as b3,
    template_plan_substitution as b4,
)


def _round_plan(**overrides):
    plan = {
        "max_success_per_round": 3,
        "max_requeue_attempts": 2,
        "auto_dispatch": True,
        "final_cut_done": False,
        "rounds": [
            {
                "successful_count": 3,
                "failed_count": 1,
                "requeues": [{"shot_id": "s2", "attempts": 1, "reason": "seam jump"}],
            },
        ],
    }
    plan.update(overrides)
    return plan


def test_a1_pass_over_cap_requeue_and_final_cut():
    assert a1.check_round_cap(_round_plan())["verdict"] == "pass"
    over = _round_plan(rounds=[{"successful_count": 4, "failed_count": 0, "requeues": []}])
    report = a1.check_round_cap(over)
    assert report["verdict"] == "fail"
    assert any(i["code"] == "round_success_over_cap" for i in report["issues"])
    exhausted = _round_plan(
        rounds=[{
            "successful_count": 1,
            "failed_count": 2,
            "requeues": [{"shot_id": "s2", "attempts": 3, "reason": "retry"}],
        }]
    )
    report = a1.check_round_cap(exhausted)
    assert report["verdict"] == "fail"
    assert any(i["code"] == "requeue_exhausted" for i in report["issues"])
    unreasoned = _round_plan(
        rounds=[{
            "successful_count": 1,
            "failed_count": 1,
            "requeues": [{"shot_id": "s2", "attempts": 1}],
        }]
    )
    assert any(
        i["code"] == "requeue_without_reason"
        for i in a1.check_round_cap(unreasoned)["issues"]
    )
    after_final = _round_plan(final_cut_done=True, generate_after_final_cut=True)
    assert any(
        i["code"] == "generation_after_final_cut"
        for i in a1.check_round_cap(after_final)["issues"]
    )
    assert any(
        i["code"] == "failed_counted_in_cap"
        for i in a1.check_round_cap(_round_plan(failed_counted_in_cap=True))["issues"]
    )
    with pytest.raises(CapabilityError):
        a1.check_round_cap({"rounds": [{"successful_count": 1}]})
    with pytest.raises(CapabilityError):
        a1.check_round_cap({"max_success_per_round": 6})


def test_a2_stale_takeover_and_forged_records():
    record = {
        "stall_threshold_s": 1800,
        "watchdog_interval_s": 60,
        "checked_at": 10000,
        "rounds": [{"id": "r1", "last_activity_at": 8000}],
        "takeovers": [
            {"round_id": "r1", "taken_at": 9900, "ledger_note": "watchdog took over"}
        ],
    }
    assert a2.check_stale_round_watchdog(record)["verdict"] == "pass"
    untaken = dict(record, takeovers=[])
    report = a2.check_stale_round_watchdog(untaken)
    assert report["verdict"] == "fail"
    assert any(i["code"] == "stale_round_untaken" for i in report["issues"])
    fresh = dict(
        record,
        rounds=[{"id": "r1", "last_activity_at": 9900}],
        checked_at=10000,
    )
    report = a2.check_stale_round_watchdog(fresh)
    assert any(i["code"] == "takeover_without_stall" for i in report["issues"])
    unrecorded = dict(
        record,
        takeovers=[{"round_id": "r1", "taken_at": 9900}],
    )
    assert any(
        i["code"] == "takeover_unrecorded"
        for i in a2.check_stale_round_watchdog(unrecorded)["issues"]
    )
    predated = dict(
        record,
        takeovers=[
            {"round_id": "r1", "taken_at": 7000, "ledger_note": "took over"}
        ],
    )
    assert any(
        i["code"] == "takeover_predates_activity"
        for i in a2.check_stale_round_watchdog(predated)["issues"]
    )
    with pytest.raises(CapabilityError):
        a2.check_stale_round_watchdog({"checked_at": 10000, "rounds": []})


def test_a3_dual_track_no_conflation():
    good = {
        "spec_verdict": "pass",
        "authenticity_verdict": "pass",
        "spec_evidence": "duration and resolution measured",
        "authenticity_evidence": "reviewer notes",
    }
    report = a3.check_spec_authenticity(good)
    assert report["verdict"] == "pass"
    assert report["combined_verdict"] == "pass"
    mixed = dict(good, authenticity_verdict="fail", authenticity_evidence="")
    report = a3.check_spec_authenticity(mixed)
    assert report["verdict"] == "fail"
    assert report["combined_verdict"] == "fail"
    hidden = dict(good, authenticity_verdict="fail", overall_verdict="pass")
    assert any(
        i["code"] == "verdict_conflation"
        for i in a3.check_spec_authenticity(hidden)["issues"]
    )
    missing = {"spec_verdict": "pass", "spec_evidence": "measured"}
    report = a3.check_spec_authenticity(missing)
    assert report["verdict"] == "fail"
    assert any(i["code"] == "authenticity_missing" for i in report["issues"])


def test_a4_dialogue_unchecked_labelling():
    unchecked = {
        "shots": [
            {"id": "s1", "dialogue": ["Hello."]},
        ],
        "dialogue_verification_status": "not_checked",
    }
    report = a4.check_dialogue_verification(unchecked)
    assert report["verdict"] == "pass"
    assert report["not_checked_shots"] == ["s1"]
    claimed = {
        "shots": [
            {
                "id": "s1",
                "dialogue": ["Hello."],
                "dialogue_check": {"method": "frame", "claimed": "verified"},
            },
        ],
        "dialogue_verification_status": "verified",
    }
    report = a4.check_dialogue_verification(claimed)
    assert report["verdict"] == "fail"
    assert any(
        i["code"] == "dialogue_claimed_verified_without_evidence"
        for i in report["issues"]
    )
    evidenced = {
        "shots": [
            {
                "id": "s1",
                "dialogue": ["Hello."],
                "dialogue_check": {"method": "asr", "evidence": "transcript seg 1"},
            },
        ],
        "dialogue_verification_status": "verified",
    }
    assert a4.check_dialogue_verification(evidenced)["verdict"] == "pass"
    silent = {"shots": [{"id": "s1"}]}
    report = a4.check_dialogue_verification(silent)
    assert report["verdict"] == "pass"
    assert report["dialogue_absent"] is True


def test_a5_disclosure_dual_track():
    good = {
        "on_screen_burnins": [],
        "external_disclosure": "All pictures in this film are AI-generated, not real footage.",
    }
    assert a5.check_ai_disclosure(good)["verdict"] == "pass"
    burned = dict(
        good,
        on_screen_burnins=[{"kind": "watermark"}],
    )
    report = a5.check_ai_disclosure(burned)
    assert report["verdict"] == "fail"
    assert any(i["code"] == "on_screen_burnin_present" for i in report["issues"])
    captionless = {"on_screen_burnins": [], "external_disclosure": ""}
    assert any(
        i["code"] == "external_disclosure_missing"
        for i in a5.check_ai_disclosure(captionless)["issues"]
    )
    vague = dict(good, external_disclosure="A lovely short film.")
    assert any(
        i["code"] == "disclosure_does_not_state_ai_generated"
        for i in a5.check_ai_disclosure(vague)["issues"]
    )
    real_claim = dict(
        good,
        external_disclosure="AI-generated pictures, shot as real footage on location.",
    )
    assert any(
        i["code"] == "disclosure_claims_real_footage"
        for i in a5.check_ai_disclosure(real_claim)["issues"]
    )


def test_a6_failed_shot_never_in_timeline():
    plan = {
        "shots": [
            {"id": "s1", "verdict": "pass"},
            {"id": "s2", "verdict": "fail"},
        ],
        "timeline": ["s1"],
        "redraw_list": ["s2"],
    }
    assert a6.check_edit_plan(plan)["verdict"] == "pass"
    in_timeline = dict(plan, timeline=["s1", "s2"])
    report = a6.check_edit_plan(in_timeline)
    assert report["verdict"] == "fail"
    assert any(i["code"] == "failed_shot_in_edit" for i in report["issues"])
    not_redrawn = dict(plan, redraw_list=[])
    assert any(
        i["code"] == "failed_shot_not_requeued"
        for i in a6.check_edit_plan(not_redrawn)["issues"]
    )


def test_b1_vocabulary_closed_and_thresholds_caller_declared():
    assert len(b1.list_review_signals()) == 15
    assert len({s["kind"] for s in b1.list_review_signals()}) == 15
    plan = {
        "signals": [
            {"kind": "lighting_drift", "method": "automatic", "threshold": 25},
            {"kind": "identity_drift", "method": "manual"},
        ]
    }
    report = b1.check_review_signals(plan)
    assert report["verdict"] == "pass"
    assert report["executed_here"] is False
    unknown = {"signals": [{"kind": "alien_artifact", "method": "manual"}]}
    assert any(
        i["code"] == "signal_kind_unknown"
        for i in b1.check_review_signals(unknown)["issues"]
    )
    no_threshold = {
        "signals": [{"kind": "exposure_jump", "method": "automatic"}]
    }
    assert any(
        i["code"] == "threshold_missing"
        for i in b1.check_review_signals(no_threshold)["issues"]
    )
    dressed = {
        "signals": [
            {"kind": "plastic_skin", "method": "manual", "measured_value": 0.9}
        ]
    }
    assert any(
        i["code"] == "manual_signal_dressed_as_measured"
        for i in b1.check_review_signals(dressed)["issues"]
    )
    mismatch = {
        "signals": [{"kind": "seam_difference", "method": "manual", "threshold": 40}]
    }
    assert any(
        i["code"] == "signal_method_mismatch"
        for i in b1.check_review_signals(mismatch)["issues"]
    )


def _edit_plan(**overrides):
    plan = {
        "shots": [
            {"id": "s1", "duration_s": 5.1667, "fps": 24, "verdict": "pass"},
            {"id": "s2", "duration_s": 5.875, "frames": 141, "verdict": "pass"},
        ],
        "seams": [{"kind": "xfade"}],
        "finish": {"temperature": "uniform", "loudness": "uniform", "grain": "light"},
        "redraw_list": [],
        "total_duration_s": 11.0417,
    }
    plan.update(overrides)
    return plan


def test_b2_edit_plan_tiling_grid_and_redraw():
    report = b2.compile_edit_plan(_edit_plan())
    assert report["verdict"] == "pass"
    assert report["executed_here"] is False
    assert len(report["compiled_shots"]) == 2
    off_grid = _edit_plan(
        shots=[
            {"id": "s1", "duration_s": 10.0, "fps": 24, "verdict": "pass"},
        ],
        seams=[],
        total_duration_s=10.0,
    )
    assert any(
        i["code"] == "frames_off_grid"
        for i in b2.compile_edit_plan(off_grid)["issues"]
    )
    gap = _edit_plan(
        shots=[
            {"id": "s1", "duration_s": 5.1667, "fps": 24, "verdict": "pass", "start_s": 1.0},
            {"id": "s2", "duration_s": 5.875, "frames": 141, "verdict": "pass"},
        ]
    )
    assert any(
        i["code"] == "tiling_gap_or_overlap"
        for i in b2.compile_edit_plan(gap)["issues"]
    )
    failed_in = _edit_plan(
        shots=[
            {"id": "s1", "duration_s": 5.1667, "fps": 24, "verdict": "fail"},
            {"id": "s2", "duration_s": 5.875, "frames": 141, "verdict": "pass"},
        ],
        redraw_list=["s1"],
    )
    assert any(
        i["code"] == "failed_shot_in_plan"
        for i in b2.compile_edit_plan(failed_in)["issues"]
    )


def test_b3_engine_contract_transitions_and_cap():
    sequence = {
        "round_id": "r1",
        "max_success_per_round": 1,
        "events": [
            {"take_id": "t1", "event": "dispatch"},
            {"take_id": "t1", "event": "report"},
            {"take_id": "t1", "event": "review"},
            {"take_id": "t1", "event": "select"},
        ],
    }
    report = b3.check_round_engine_contract(sequence)
    assert report["verdict"] == "pass"
    assert report["executed_here"] is False
    skipped = dict(
        sequence,
        events=[{"take_id": "t1", "event": "select"}],
    )
    assert any(
        i["code"] == "illegal_transition"
        for i in b3.check_round_engine_contract(skipped)["issues"]
    )
    over_cap = dict(
        sequence,
        events=sequence["events"]
        + [
            {"take_id": "t2", "event": "dispatch"},
            {"take_id": "t2", "event": "report"},
            {"take_id": "t2", "event": "review"},
            {"take_id": "t2", "event": "select"},
        ],
    )
    assert any(
        i["code"] == "round_success_over_cap"
        for i in b3.check_round_engine_contract(over_cap)["issues"]
    )
    assert b3.allowed_transitions("reviewed") == ("selected", "failed", "dispatched")
    with pytest.raises(CapabilityError):
        b3.check_round_engine_contract({"events": []})
    with pytest.raises(CapabilityError):
        b3.allowed_transitions("nowhere")


def test_b4_planner_substitution_signature_and_arc():
    contract = {
        "planner": {
            "entry_point": "plan_shots",
            "parameters": ["story_text", "shot_count"],
        },
        "returns": ["beats"],
        "beats": [
            {"start_s": 0.0, "end_s": 2.0, "arc": "opening"},
            {"start_s": 2.0, "end_s": 4.0, "arc": "development"},
            {"start_s": 4.0, "end_s": 6.0, "arc": "turn"},
            {"start_s": 6.0, "end_s": 8.0, "arc": "close"},
        ],
        "total_duration_s": 8.0,
    }
    report = b4.check_template_planner_contract(contract)
    assert report["verdict"] == "pass"
    assert report["executed_here"] is False
    wrong_sig = dict(
        contract,
        planner={"entry_point": "plan_shots", "parameters": ["story_text"]},
    )
    assert any(
        i["code"] == "planner_signature_mismatch"
        for i in b4.check_template_planner_contract(wrong_sig)["issues"]
    )
    broken_arc = dict(
        contract,
        beats=[
            {"start_s": 0.0, "end_s": 4.0, "arc": "close"},
            {"start_s": 4.0, "end_s": 8.0, "arc": "opening"},
        ],
    )
    assert any(
        i["code"] == "arc_order_broken"
        for i in b4.check_template_planner_contract(broken_arc)["issues"]
    )
    gapped = dict(
        contract,
        beats=[
            {"start_s": 0.0, "end_s": 2.0, "arc": "opening"},
            {"start_s": 3.0, "end_s": 8.0, "arc": "close"},
        ],
    )
    assert any(
        i["code"] == "beat_tiling_gap_or_overlap"
        for i in b4.check_template_planner_contract(gapped)["issues"]
    )


def test_registry_names_present():
    for name in (
        "qa.round_cap_gate",
        "qa.stale_round_watchdog_gate",
        "qa.spec_authenticity_dual_track_gate",
        "qa.dialogue_unverified_gate",
        "qa.ai_disclosure_dual_track_gate",
        "qa.failed_shot_no_hard_cut_gate",
        "qa.review_signal_vocabulary",
        "video.edit_plan_compiler",
        "qa.round_engine_contract",
        "qa.template_plan_substitution",
    ):
        assert contains(name), name
