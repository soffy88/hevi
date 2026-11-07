"""Tests for the <雨停之前> graft: A1-A5 + B1+B2.

A1 story intake gate, A2 text/image consistency gate, A3 review
sign-off gate, A4 issue-kind labels, A5 per-version cost view,
B1 draft task ledger (fake backend, caller-supplied clocks),
B2 Seedance pricing registration (list prices only, no key).

No network, no paid API, no generation. The 3,500-yuan field
ledger is never used as a quote; Seedance figures are list prices
with source and date, derived per-second figures flagged
unverified.
"""

import json

import pytest

from hevi.capabilities.draft_task_ledger import (
    convert_draft_to_final,
    create_draft_task,
    task_status,
)
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.issue_kind_labels import (
    check_issue_kind,
    summarise_labelled,
)
from hevi.capabilities.review_signoff_gate import check_review_signoff
from hevi.capabilities.seedance_pricing_registration import (
    check_seedance_pricing_registration,
    seedance_pricing_record,
)
from hevi.capabilities.story_intake_gate import check_story_intake
from hevi.capabilities.text_image_consistency_gate import (
    check_text_image_consistency,
)
from hevi.capabilities.version_cost_view import (
    REQUIRED_TUITION_NOTE,
    build_version_cost_view,
)

TUITION_NOTE = REQUIRED_TUITION_NOTE


def _proposal(**overrides):
    proposal = {
        "audience": "喜欢悬疑短剧的年轻观众",
        "protagonist_goal": "林晚想在离开小城前弄清书店的异常",
        "obstacle": "街景正在变回 1995 年，时间对不上的信无法解释",
        "mood": "雨夜、暖光书店、安静中透着不对劲",
        "closing_question": "和自己长得一样的人是谁？",
        "one_sentence": "女孩走进旧书店，捡到一封写着自己名字的信，落款是自己出生前的一年。",
        "opening_anomaly": "女孩推开门，遇见一个和自己长得一样的人。",
        "expression_split": {
            "visual": ["街景变回 1995 年", "信的落款年份"],
            "dialogue": ["林晚……雨停之前，别走"],
        },
    }
    proposal.update(overrides)
    return proposal


# ---- A1: story intake gate ----

def test_a1_complete_proposal_passes():
    report = check_story_intake(_proposal())
    assert report["ok"] is True
    assert report["verdict"] == "pass"


def test_a1_missing_field_fails():
    report = check_story_intake(_proposal(obstacle=""))
    assert report["ok"] is False
    assert any(i["code"] == "missing_field" and i["field"] == "obstacle"
               for i in report["issues"])


def test_a1_missing_expression_split_fails():
    proposal = _proposal()
    del proposal["expression_split"]
    report = check_story_intake(proposal)
    assert report["ok"] is False
    assert any(i["code"] == "missing_expression_split" for i in report["issues"])


def test_a1_adjective_only_story_fails():
    report = check_story_intake(_proposal(
        one_sentence="一部非常悬疑、很有电影感、很高级的剧。",
        opening_anomaly="氛围感拉满，质感十足。",
    ))
    assert report["ok"] is False
    assert any(i["code"] == "adjective_only_story" for i in report["issues"])


def test_a1_adjective_heavy_but_concrete_passes():
    # Adjectives present, but a concrete event survives the peel.
    report = check_story_intake(_proposal(
        one_sentence="悬疑氛围里，女孩走进旧书店，捡到一封写着自己名字的信。",
    ))
    assert report["ok"] is True


def test_a1_non_object_fails():
    assert check_story_intake("我要一部悬疑剧")["ok"] is False


# ---- A2: text/image consistency gate ----

def _inventory():
    return {"elements": [
        {"element": "门", "present": True, "position": "临街正中"},
        {"element": "窗", "present": True, "position": "柜台对面"},
        {"element": "柜台", "present": True, "position": "进门右侧"},
        {"element": "挂钟", "present": True, "position": "柜台后墙上"},
    ]}


def test_a2_consistent_passes():
    card = {"assertions": [
        {"element": "窗", "present": True, "position": "柜台对面"},
        {"element": "挂钟", "present": True, "position": "柜台后墙上"},
    ]}
    report = check_text_image_consistency(card, _inventory())
    assert report["ok"] is True


def test_a2_window_case_fails():
    # Field case: picture shows a window, text says there is none.
    card = {"assertions": [
        {"element": "窗", "present": False},
    ]}
    report = check_text_image_consistency(card, _inventory())
    assert report["ok"] is False
    assert any(i["code"] == "presence_conflict" and i["element"] == "窗"
               for i in report["issues"])


def test_a2_position_conflict_fails():
    card = {"assertions": [
        {"element": "柜台", "present": True, "position": "进门左侧"},
    ]}
    report = check_text_image_consistency(card, _inventory())
    assert report["ok"] is False
    assert any(i["code"] == "position_conflict" for i in report["issues"])


def test_a2_element_missing_from_inventory_fails():
    card = {"assertions": [
        {"element": "信架", "present": True},
    ]}
    report = check_text_image_consistency(card, _inventory())
    assert report["ok"] is False
    assert any(i["code"] == "element_missing_from_inventory" for i in report["issues"])


# ---- A3: review sign-off gate ----

def _review(**overrides):
    review = {
        "version": "V8",
        "reviewer_feedback": [
            {"id": "F1", "item": "柜台到窗边的移动没交代"},
            {"id": "F2", "item": "配乐在人物开口时太响"},
        ],
        "author_confirmation": {
            "confirmed_ids": ["F1", "F2"],
            "rejected_ids": [],
            "note": "两条都成立",
        },
        "fix_list": ["F1", "F2"],
        "recheck": {
            "checked_ids": ["F1", "F2"],
            "new_problems": [],
        },
        "previous_version_retained": True,
    }
    review.update(overrides)
    return review


def test_a3_signed_off_review_passes():
    assert check_review_signoff(_review())["ok"] is True


def test_a3_unconfirmed_feedback_in_fix_list_fails():
    review = _review(author_confirmation={
        "confirmed_ids": ["F1"], "rejected_ids": [], "note": "F2 待定",
    })
    report = check_review_signoff(review)
    assert report["ok"] is False
    assert any(i["code"] == "unconfirmed_feedback_in_fix_list" for i in report["issues"])
    assert any(i["code"] == "feedback_without_author_decision" for i in report["issues"])


def test_a3_missing_author_confirmation_fails():
    review = _review()
    del review["author_confirmation"]
    report = check_review_signoff(review)
    assert report["ok"] is False
    assert any(i["code"] == "author_confirmation_missing" for i in report["issues"])


def test_a3_recheck_missing_item_fails():
    review = _review(recheck={"checked_ids": ["F1"], "new_problems": []})
    report = check_review_signoff(review)
    assert report["ok"] is False
    assert any(i["code"] == "recheck_missing_item" for i in report["issues"])


def test_a3_previous_version_not_retained_fails():
    review = _review(previous_version_retained=False)
    report = check_review_signoff(review)
    assert report["ok"] is False
    assert any(i["code"] == "previous_version_not_retained" for i in report["issues"])


# ---- A4: issue-kind labels ----

def test_a4_three_kinds_labelled():
    assert check_issue_kind(
        {"issue_kind": "continuity", "verdict": "fail"})["ok"] is True
    assert check_issue_kind(
        {"issue_kind": "aesthetic", "verdict": "fail"})["ok"] is True
    assert check_issue_kind(
        {"issue_kind": "unconfirmed", "verdict": "not_checked"})["ok"] is True


def test_a4_unlabelled_fails():
    report = check_issue_kind({"verdict": "fail"})
    assert report["ok"] is False
    assert any(i["code"] == "issue_kind_missing" for i in report["issues"])


def test_a4_aesthetic_as_must_fix_fails():
    report = check_issue_kind({
        "issue_kind": "aesthetic", "verdict": "fail",
        "execution_priority": "must_fix",
    })
    assert report["ok"] is False
    assert any(i["code"] == "aesthetic_executed_as_continuity" for i in report["issues"])


def test_a4_unconfirmed_never_counts_as_pass():
    report = check_issue_kind({"issue_kind": "unconfirmed", "verdict": "pass"})
    assert report["ok"] is False
    assert any(i["code"] == "unconfirmed_counted_as_pass" for i in report["issues"])
    summary = summarise_labelled([
        {"issue_kind": "unconfirmed", "verdict": "not_checked"},
        {"issue_kind": "continuity", "verdict": "pass"},
    ])
    assert summary["passed"] == 1
    assert summary["counts"] == {"continuity": 1, "aesthetic": 0, "unconfirmed": 1}


# ---- A5: version cost view ----

def _ledger():
    return {"batches": [
        {"batch_id": "v6", "status": "settled", "estimated_total": 2564.0,
         "actual_total": 2564.0},
        {"batch_id": "v8", "status": "settled", "estimated_total": 290.0,
         "actual_total": 290.0},
    ]}


def test_a5_version_view_marks_incomparable_methods():
    report = build_version_cost_view(_ledger(), [
        {"version_id": "V6", "batch_ids": ["v6"], "method": "1080p 逐镜生成",
         "trial_and_error": True, "cost_basis_note": TUITION_NOTE},
        {"version_id": "V8", "batch_ids": ["v8"], "method": "480p 按场生成",
         "trial_and_error": False, "cost_basis_note": None},
    ])
    assert report["ok"] is True
    assert report["comparable"] is False
    assert report["versions"][0]["actual_total"] == 2564.0
    assert report["versions"][1]["actual_total"] == 290.0


def test_a5_tuition_version_without_note_fails():
    report = build_version_cost_view(_ledger(), [
        {"version_id": "V6", "batch_ids": ["v6"], "method": "1080p 逐镜生成",
         "trial_and_error": True, "cost_basis_note": None},
    ])
    assert report["ok"] is False
    assert any(i["code"] == "tuition_note_missing" for i in report["issues"])


def test_a5_quote_request_refused():
    report = build_version_cost_view(
        _ledger(),
        [{"version_id": "V6", "batch_ids": ["v6"], "method": "1080p 逐镜生成",
          "trial_and_error": True, "cost_basis_note": TUITION_NOTE}],
        request_quote=True,
    )
    assert report["ok"] is False
    assert any(i["code"] == "quote_refused" for i in report["issues"])


# ---- B1: draft task ledger (fake backend) ----

def test_b1_create_status_convert_within_seven_days(tmp_path):
    ledger = tmp_path / "ledger.json"
    task = create_draft_task(
        ledger, draft_task_id="draft-001",
        created_at="2026-11-01T00:00:00Z", duration_s=24.0,
    )
    assert task["status"] == "draft"
    assert task["draft_resolution"] == "480p"
    status = task_status(ledger, "draft-001", "2026-11-03T00:00:00Z")
    assert status["status"] == "draft"
    converted = convert_draft_to_final(
        ledger, draft_task_id="draft-001",
        now="2026-11-03T00:00:00Z", resolution="1080p",
    )
    assert converted["ok"] is True
    assert converted["status"] == "final"
    assert task_status(ledger, "draft-001", "2026-11-04T00:00:00Z")["status"] == "final"


def test_b1_expired_after_seven_days(tmp_path):
    ledger = tmp_path / "ledger.json"
    create_draft_task(
        ledger, draft_task_id="draft-002",
        created_at="2026-11-01T00:00:00Z", duration_s=24.0,
    )
    # Exactly 7 days later: expired, conversion fails closed.
    status = task_status(ledger, "draft-002", "2026-11-08T00:00:00Z")
    assert status["status"] == "expired"
    converted = convert_draft_to_final(
        ledger, draft_task_id="draft-002",
        now="2026-11-08T00:00:00Z", resolution="1080p",
    )
    assert converted["ok"] is False
    assert any(i["code"] == "draft_task_expired" for i in converted["issues"])


def test_b1_local_file_cannot_replace_task_id(tmp_path):
    ledger = tmp_path / "ledger.json"
    converted = convert_draft_to_final(
        ledger, draft_task_id="", now="2026-11-03T00:00:00Z",
        resolution="1080p",
    )
    assert converted["ok"] is False
    assert any(i["code"] == "local_file_cannot_replace_task_id"
               for i in converted["issues"])


def test_b1_wrong_final_tier_fails(tmp_path):
    ledger = tmp_path / "ledger.json"
    create_draft_task(
        ledger, draft_task_id="draft-003",
        created_at="2026-11-01T00:00:00Z", duration_s=24.0,
    )
    converted = convert_draft_to_final(
        ledger, draft_task_id="draft-003",
        now="2026-11-03T00:00:00Z", resolution="480p",
    )
    assert converted["ok"] is False
    assert any(i["code"] == "final_tier_mismatch" for i in converted["issues"])


def test_b1_duplicate_task_id_raises(tmp_path):
    ledger = tmp_path / "ledger.json"
    create_draft_task(
        ledger, draft_task_id="draft-004",
        created_at="2026-11-01T00:00:00Z", duration_s=24.0,
    )
    with pytest.raises(CapabilityError):
        create_draft_task(
            ledger, draft_task_id="draft-004",
            created_at="2026-11-01T00:00:00Z", duration_s=24.0,
        )


# ---- B2: Seedance pricing registration ----

def test_b2_registered_record_passes_with_fresh_date():
    record = seedance_pricing_record()
    report = check_seedance_pricing_registration(record, today="2026-11-02")
    assert report["ok"] is True
    assert record["list_prices"][2]["token_price_per_million_cny"] == 77
    assert record["derived_figures_unverified"] is True


def test_b2_unsourced_record_refused():
    record = seedance_pricing_record()
    record["source"] = ""
    record["price_as_of"] = ""
    report = check_seedance_pricing_registration(record, today="2026-11-02")
    assert report["ok"] is False
    assert any(i["code"] == "price_source_missing" for i in report["issues"])
    assert any(i["code"] == "price_date_missing" for i in report["issues"])


def test_b2_invented_tier_refused():
    record = seedance_pricing_record()
    record["list_prices"].append({
        "resolution": "4K",
        "token_price_per_million_cny": 100,
        "token_price_with_video_input_per_million_cny": 60,
    })
    report = check_seedance_pricing_registration(record, today="2026-11-02")
    assert report["ok"] is False
    assert any(i["code"] == "unknown_resolution_tier" for i in report["issues"])


def test_b2_credential_must_not_be_stored():
    record = seedance_pricing_record()
    record["api_key"] = "sk-xxx"
    report = check_seedance_pricing_registration(record, today="2026-11-02")
    assert report["ok"] is False
    assert any(i["code"] == "credential_must_not_be_stored" for i in report["issues"])


def test_b2_stale_price_needs_recheck():
    record = seedance_pricing_record()
    report = check_seedance_pricing_registration(record, today="2026-12-15")
    assert report["ok"] is False
    assert any(i["code"] == "price_stale_recheck" for i in report["issues"])
