"""Tests for the digital-human-koubo recheck graft: A1-A5 + B1 + B4.

Clean-room: only disciplines are judged here. No generation runs,
no model is called, no vendor is contacted, no key is used. B1
runs against a fake local ledger. B2 (voice unification chain)
and B3 (misread repair execution) are blocked -- they need real
audio evidence, a voice-clone key, and the speaker's own
recording -- and are not covered here.
"""

import pytest

import hevi.capabilities  # noqa: F401  (registers every capability)
from hevi.capabilities.asr_glossary import GLOSSARY_VERSION
from hevi.capabilities.av_duration_consistency_gate import (
    check_av_duration_consistency,
)
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.first_segment_confirmation_gate import (
    check_first_segment_confirmation,
)
from hevi.capabilities.misread_judgement_gate import check_misread_judgement
from hevi.capabilities.packaging_component_vocabulary import (
    check_packaging_plan,
    packaging_component_vocabulary,
)
from hevi.capabilities.reference_account_binding_gate import (
    check_reference_account_binding,
)
from hevi.capabilities.registry import get as registry_get
from hevi.capabilities.segment_cost_ledger import (
    ledger_totals,
    record_segment_cost,
    registered_renoise_rates,
)
from hevi.capabilities.segment_listenback_gate import check_segment_listenback


def _signoff():
    return {
        "reviewer_feedback": [{"id": "f1", "note": "check the opening line"}],
        "author_confirmation": {"confirmed_ids": ["f1"], "rejected_ids": []},
        "fix_list": ["f1"],
    }


def _confirmation(segment_id="s01"):
    return {
        "segment_id": segment_id,
        "confirmer": "reviewer-a",
        "confirmed_at": "2026-11-02T10:00:00Z",
        "decision": "confirmed",
        "review_signoff": _signoff(),
    }


def _listenback():
    return {
        "transcript": "hello world",
        "transcript_t2s": "hello world",
        "coverage": 0.9,
        "model_name": "small",
        "normalization": "builtin",
        "glossary_version": GLOSSARY_VERSION,
    }


def _cost_entry(segment_id="s01", credits=170.0):
    return {
        "segment_id": segment_id,
        "duration_s": 10.0,
        "resolution": "720p",
        "credits": credits,
        "price_source": "test price source",
        "price_as_of": "2026-11-02",
    }


# --- Registration: all seven new capabilities resolve ---

def test_new_capabilities_registered():
    for name in (
        "qa.first_segment_confirmation_gate",
        "qa.segment_listenback_gate",
        "qa.misread_judgement_gate",
        "qa.av_duration_consistency_gate",
        "qa.reference_account_binding_gate",
        "video.segment_cost_ledger",
        "qa.packaging_component_vocabulary",
    ):
        assert registry_get(name).name == name


# --- A1: first-segment confirmation ---

def test_a1_confirmed_first_segment_passes():
    plan = {
        "segments": ["s01", "s02"],
        "batch_requested": True,
        "first_segment_confirmation": _confirmation("s01"),
    }
    report = check_first_segment_confirmation(plan)
    assert report["verdict"] == "pass"
    assert report["batch_may_proceed"] is True


def test_a1_batch_without_confirmation_fails():
    report = check_first_segment_confirmation(
        {"segments": ["s01", "s02"], "batch_started": True}
    )
    assert report["verdict"] == "fail"
    codes = [i["code"] for i in report["issues"]]
    assert "first_segment_confirmation_missing" in codes
    assert "batch_without_first_segment_confirmation" in codes


def test_a1_wrong_segment_confirmation_fails():
    plan = {
        "segments": ["s01", "s02"],
        "batch_requested": True,
        "first_segment_confirmation": _confirmation("s02"),
    }
    report = check_first_segment_confirmation(plan)
    assert report["verdict"] == "fail"
    assert any(i["code"] == "confirmation_wrong_segment" for i in report["issues"])


def test_a1_pending_decision_fails():
    confirmation = _confirmation("s01")
    confirmation["decision"] = "pending"
    report = check_first_segment_confirmation(
        {"segments": ["s01"], "first_segment_confirmation": confirmation}
    )
    assert report["verdict"] == "fail"
    assert any(i["code"] == "confirmation_not_confirmed" for i in report["issues"])


def test_a1_dual_signoff_reused_missing_signoff_fails():
    confirmation = _confirmation("s01")
    del confirmation["review_signoff"]
    report = check_first_segment_confirmation(
        {"segments": ["s01"], "first_segment_confirmation": confirmation}
    )
    assert report["verdict"] == "fail"
    assert any(i["code"] == "dual_signoff_missing" for i in report["issues"])


def test_a1_undecided_feedback_in_signoff_fails():
    signoff = _signoff()
    signoff["reviewer_feedback"].append({"id": "f2", "note": "undecided"})
    confirmation = _confirmation("s01")
    confirmation["review_signoff"] = signoff
    report = check_first_segment_confirmation(
        {"segments": ["s01"], "first_segment_confirmation": confirmation}
    )
    assert report["verdict"] == "fail"
    assert any(i["code"] == "dual_signoff_failed" for i in report["issues"])


def test_a1_retake_without_requote_fails():
    plan = {
        "segments": ["s01"],
        "retake": True,
        "first_segment_confirmation": _confirmation("s01"),
    }
    report = check_first_segment_confirmation(plan)
    assert report["verdict"] == "fail"
    assert any(i["code"] == "retake_without_requote" for i in report["issues"])


# --- A2: per-segment listen-back ---

def test_a2_all_segments_with_listenback_pass():
    plan = {
        "assembly_requested": True,
        "segments": [
            {"segment_id": "s01", "listenback": _listenback()},
            {"segment_id": "s02", "listenback": _listenback()},
        ],
    }
    report = check_segment_listenback(plan)
    assert report["verdict"] == "pass"
    assert report["assembly_blocked"] is False


def test_a2_segment_without_listenback_blocks_assembly():
    plan = {
        "assembly_requested": True,
        "segments": [
            {"segment_id": "s01", "listenback": _listenback()},
            {"segment_id": "s02"},
        ],
    }
    report = check_segment_listenback(plan)
    assert report["verdict"] == "fail"
    assert report["assembly_blocked"] is True
    assert any(i["code"] == "listenback_missing" for i in report["issues"])


def test_a2_normalization_none_fails():
    record = _listenback()
    record["normalization"] = "none"
    record["glossary_version"] = None
    report = check_segment_listenback(
        {"segments": [{"segment_id": "s01", "listenback": record}]}
    )
    assert report["verdict"] == "fail"
    codes = [i["code"] for i in report["issues"]]
    assert "normalization_not_applied" in codes
    assert "glossary_version_stale" in codes


def test_a2_stale_glossary_fails():
    record = _listenback()
    record["glossary_version"] = "asr-glossary-v0"
    report = check_segment_listenback(
        {"segments": [{"segment_id": "s01", "listenback": record}]}
    )
    assert report["verdict"] == "fail"
    assert any(i["code"] == "glossary_version_stale" for i in report["issues"])


def test_a2_coverage_out_of_range_fails():
    record = _listenback()
    record["coverage"] = 1.5
    report = check_segment_listenback(
        {"segments": [{"segment_id": "s01", "listenback": record}]}
    )
    assert report["verdict"] == "fail"
    assert any(i["code"] == "coverage_invalid" for i in report["issues"])


# --- A3: misread judgement ---

def test_a3_agreeing_words_no_judgement_needed():
    record = {
        "script_words": ["hello", "world"],
        "transcript_words": ["hello", "world"],
        "prompt_included_script": False,
        "judgements": [],
    }
    assert check_misread_judgement(record)["verdict"] == "pass"


def test_a3_true_misread_classified_passes():
    record = {
        "script_words": ["hello", "world"],
        "transcript_words": ["hello", "word"],
        "prompt_included_script": False,
        "judgements": [
            {"word_index": 1, "classification": "true_misread",
             "basis": "speaker said word, heard on the recording"},
        ],
    }
    assert check_misread_judgement(record)["verdict"] == "pass"


def test_a3_prompted_transcript_is_not_evidence():
    record = {
        "script_words": ["hello", "world"],
        "transcript_words": ["hello", "world"],
        "prompt_included_script": True,
        "judgements": [],
    }
    report = check_misread_judgement(record)
    assert report["verdict"] == "fail"
    assert any(
        i["code"] == "prompted_transcript_not_pronunciation_evidence"
        for i in report["issues"]
    )


def test_a3_unclassified_judgement_fails():
    record = {
        "script_words": ["hello", "world"],
        "transcript_words": ["hello", "word"],
        "prompt_included_script": False,
        "judgements": [{"word_index": 1, "classification": "maybe"}],
    }
    report = check_misread_judgement(record)
    assert report["verdict"] == "fail"
    assert any(i["code"] == "judgement_unclassified" for i in report["issues"])


def test_a3_difference_without_judgement_fails():
    record = {
        "script_words": ["hello", "world"],
        "transcript_words": ["hello", "word"],
        "prompt_included_script": False,
        "judgements": [],
    }
    report = check_misread_judgement(record)
    assert report["verdict"] == "fail"
    assert any(i["code"] == "difference_without_judgement" for i in report["issues"])


def test_a3_unconfirmed_classification_allowed():
    record = {
        "script_words": ["hello", "world"],
        "transcript_words": ["hello", "word"],
        "prompt_included_script": False,
        "judgements": [{"word_index": 1, "classification": "unconfirmed"}],
    }
    assert check_misread_judgement(record)["verdict"] == "pass"


def test_a3_transcription_error_on_matching_word_fails():
    record = {
        "script_words": ["hello", "world"],
        "transcript_words": ["hello", "world"],
        "prompt_included_script": False,
        "judgements": [
            {"word_index": 1, "classification": "transcription_error",
             "basis": "no difference exists"},
        ],
    }
    report = check_misread_judgement(record)
    assert report["verdict"] == "fail"
    assert any(
        i["code"] == "transcription_error_without_difference"
        for i in report["issues"]
    )


# --- A4: AV duration consistency ---

def test_a4_matching_durations_pass():
    plan = {
        "tolerance_s": 0.05,
        "segments": [
            {"segment_id": "s01", "audio_duration_s": 10.0, "video_duration_s": 10.02},
        ],
    }
    report = check_av_duration_consistency(plan)
    assert report["verdict"] == "pass"
    assert report["counts"] == {"pass": 1, "fail": 0, "not_checked": 0}


def test_a4_drift_without_repair_chain_fails():
    plan = {
        "tolerance_s": 0.05,
        "segments": [
            {"segment_id": "s01", "audio_duration_s": 10.0, "video_duration_s": 10.4},
        ],
    }
    report = check_av_duration_consistency(plan)
    assert report["verdict"] == "fail"
    assert any(i["code"] == "drift_repair_chain_missing" for i in report["issues"])


def test_a4_drift_with_valid_repair_chain_passes():
    plan = {
        "tolerance_s": 0.05,
        "segments": [{
            "segment_id": "s01",
            "audio_duration_s": 10.0,
            "video_duration_s": 10.4,
            "drift_repair": {
                "audio_before_s": 10.0, "audio_after_s": 10.4,
                "video_before_s": 10.4, "video_after_s": 10.4,
            },
        }],
    }
    assert check_av_duration_consistency(plan)["verdict"] == "pass"


def test_a4_repair_chain_without_comparison_fails():
    plan = {
        "tolerance_s": 0.05,
        "segments": [{
            "segment_id": "s01",
            "audio_duration_s": 10.0,
            "video_duration_s": 10.4,
            "drift_repair": {"audio_after_s": 10.4},
        }],
    }
    report = check_av_duration_consistency(plan)
    assert report["verdict"] == "fail"
    assert any(
        i["code"] == "drift_repair_comparison_missing" for i in report["issues"]
    )


def test_a4_missing_tolerance_is_not_checked():
    plan = {
        "segments": [
            {"segment_id": "s01", "audio_duration_s": 10.0, "video_duration_s": 10.4},
        ],
    }
    report = check_av_duration_consistency(plan)
    assert report["verdict"] == "not_checked"
    assert report["counts"]["not_checked"] == 1


# --- A5: reference account binding ---

def test_a5_self_binding_passes():
    record = {
        "reference_id": "ref-1",
        "source_account": "acct-owner",
        "account_binding": {"kind": "self", "owner": "acct-owner"},
    }
    assert check_reference_account_binding(record)["verdict"] == "pass"


def test_a5_authorised_binding_passes():
    record = {
        "reference_id": "ref-2",
        "source_account": "acct-owner",
        "account_binding": {
            "kind": "authorised",
            "authoriser": "the person in the picture",
            "scope": "this piece only",
        },
    }
    assert check_reference_account_binding(record)["verdict"] == "pass"


def test_a5_no_binding_fails():
    record = {"reference_id": "ref-1", "source_account": "acct-owner"}
    report = check_reference_account_binding(record)
    assert report["verdict"] == "fail"
    assert any(i["code"] == "account_binding_missing" for i in report["issues"])


def test_a5_authorised_without_scope_fails():
    record = {
        "reference_id": "ref-2",
        "source_account": "acct-owner",
        "account_binding": {"kind": "authorised", "authoriser": "someone"},
    }
    report = check_reference_account_binding(record)
    assert report["verdict"] == "fail"
    assert any(i["code"] == "binding_scope_missing" for i in report["issues"])


def test_a5_demo_and_material_ids_forbidden():
    for field in ("demo_identity", "persona_id", "material_id"):
        record = {
            "reference_id": "ref-1",
            "source_account": "acct-owner",
            "account_binding": {"kind": "self", "owner": "acct-owner"},
            field: "some-id",
        }
        report = check_reference_account_binding(record)
        assert report["verdict"] == "fail"
        assert any(i["code"] == "forbidden_identity_field" for i in report["issues"])


def test_a5_unlicensed_material_and_cross_account_reuse_fail():
    record = {
        "reference_id": "ref-1",
        "source_account": "acct-owner",
        "account_binding": {"kind": "self", "owner": "acct-owner"},
        "contains_unlicensed_third_party_material": True,
        "cross_account_reuse": True,
    }
    report = check_reference_account_binding(record)
    assert report["verdict"] == "fail"
    codes = [i["code"] for i in report["issues"]]
    assert "unlicensed_third_party_material" in codes
    assert "cross_account_reuse" in codes


# --- B1: segment cost ledger (fake backend) ---

def test_b1_registered_rates_flagged_unverified():
    rates = registered_renoise_rates()
    assert rates["verified"] is False
    assert rates["price_as_of"] == "2026-11-02"
    assert rates["source"]
    by_tier = {r["resolution"]: r["credits_per_second"] for r in rates["rates"]}
    assert by_tier == {"480p": 10, "720p": 17}


def test_b1_fake_ledger_records_and_totals(tmp_path):
    ledger = tmp_path / "ledger.json"
    result = record_segment_cost(ledger, entry=_cost_entry("s01"))
    assert result["totals"] == {"segments": 1, "total_credits": 170.0,
                                "total_duration_s": 10.0}
    record_segment_cost(ledger, entry=_cost_entry("s02", credits=100.0))
    data = __import__("json").loads(ledger.read_text(encoding="utf-8"))
    assert ledger_totals(data)["total_credits"] == 270.0
    assert ledger_totals(data)["segments"] == 2


def test_b1_over_budget_entry_blocked(tmp_path):
    ledger = tmp_path / "ledger.json"
    record_segment_cost(ledger, entry=_cost_entry("s01"), budget_credits=200.0)
    with pytest.raises(CapabilityError, match="over the 200.0 credit budget"):
        record_segment_cost(
            ledger, entry=_cost_entry("s02", credits=100.0),
            budget_credits=200.0,
        )


def test_b1_unsourced_price_refused(tmp_path):
    entry = _cost_entry("s01")
    del entry["price_source"]
    with pytest.raises(CapabilityError, match="price_source"):
        record_segment_cost(tmp_path / "ledger.json", entry=entry)


def test_b1_unsourced_differing_rate_refused(tmp_path):
    entry = _cost_entry("s01")
    entry["rate_credits_per_second"] = 25
    with pytest.raises(CapabilityError, match="rate_source"):
        record_segment_cost(tmp_path / "ledger.json", entry=entry)


def test_b1_unknown_tier_refused(tmp_path):
    entry = _cost_entry("s01")
    entry["resolution"] = "1080p"
    with pytest.raises(CapabilityError, match="not a registered tier"):
        record_segment_cost(tmp_path / "ledger.json", entry=entry)


def test_b1_duplicate_segment_refused(tmp_path):
    ledger = tmp_path / "ledger.json"
    record_segment_cost(ledger, entry=_cost_entry("s01"))
    with pytest.raises(CapabilityError, match="duplicate segment_id"):
        record_segment_cost(ledger, entry=_cost_entry("s01"))


# --- B4: packaging component vocabulary ---

def test_b4_vocabulary_entries_carry_purpose_and_constraint():
    vocabulary = packaging_component_vocabulary()
    assert len(vocabulary) >= 20
    names = [entry["name"] for entry in vocabulary]
    assert len(names) == len(set(names))
    for entry in vocabulary:
        assert set(entry) == {"name", "purpose", "constraint"}
        assert entry["purpose"].strip()
        assert entry["constraint"].strip()


def test_b4_declared_plan_passes():
    plan = {"components": [
        {"name": "LowerThird", "purpose": "name the speaker",
         "constraint": "one at a time, never over the mouth"},
        {"name": "EvidenceCard", "purpose": "show the document",
         "constraint": "source line on the card"},
    ]}
    assert check_packaging_plan(plan)["verdict"] == "pass"


def test_b4_missing_constraint_fails():
    plan = {"components": [
        {"name": "LowerThird", "purpose": "name the speaker"},
    ]}
    report = check_packaging_plan(plan)
    assert report["verdict"] == "fail"
    assert any(
        i["code"] == "component_constraint_missing" for i in report["issues"]
    )


def test_b4_unknown_component_fails():
    plan = {"components": [
        {"name": "NotAComponent", "purpose": "x", "constraint": "y"},
    ]}
    report = check_packaging_plan(plan)
    assert report["verdict"] == "fail"
    assert any(i["code"] == "component_unknown" for i in report["issues"])


def test_b4_template_text_refused():
    plan = {"components": [
        {"name": "LowerThird", "purpose": "name the speaker",
         "constraint": "one at a time",
         "template_text": "copied template markup"},
    ]}
    report = check_packaging_plan(plan)
    assert report["verdict"] == "fail"
    assert any(i["code"] == "template_text_forbidden" for i in report["issues"])
