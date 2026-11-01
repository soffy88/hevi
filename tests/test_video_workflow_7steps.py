"""Tests for the seven-step video workflow graft (A1-A4 + B1-B4)."""

from __future__ import annotations

import pytest

from hevi.capabilities.ban_revision_log import apply_ban_revisions
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.fix_ticket import check_fix_ticket, locate_ticket, parse_timecode
from hevi.capabilities.generation_spec_gate import (
    authorize_generation_spec,
    check_generation_spec,
)
from hevi.capabilities.hardest_shot_pilot import check_pilot_batch, difficulty_score
from hevi.capabilities.post_production_checklist import (
    check_freeze_pad_rule,
    check_generation_side,
    check_post_checklist,
)
from hevi.capabilities.prompt_compiler import resolve_provider_caps
from hevi.capabilities.reference_role_gate import check_reference_roles
from hevi.capabilities.registry import get
from hevi.capabilities.three_layer_clip import (
    THREE_LAYER_FIXTURE_VERSION,
    build_three_layer_fixtures,
    check_three_layer_clip,
    count_action_clauses,
)
from hevi.capabilities.verdict_vocabulary import (
    normalise_verdict,
    summarise_verdicts,
    to_legacy_pass,
)


def _spec(**overrides):
    spec = {
        "total_duration_s": 30.0,
        "shot_count": 3,
        "aspect": "9:16",
        "camera_strategy": "locked",
        "audio_strategy": "silent_post_dubbed",
        "provider": "fasth3_local",
    }
    spec.update(overrides)
    return spec


# --- A1: spec sheet gate ---

def test_spec_gate_passes_locked_spec():
    report = check_generation_spec(_spec())
    assert report["ok"] is True
    assert report["verdict"] == "pass"
    assert report["checked_durations_s"] == [10.0, 10.0, 10.0]


def test_spec_gate_missing_aspect_fails():
    spec = _spec()
    del spec["aspect"]
    report = check_generation_spec(spec)
    assert report["ok"] is False
    assert "aspect" in report["missing"]


def test_spec_gate_missing_audio_strategy_fails():
    spec = _spec()
    del spec["audio_strategy"]
    report = check_generation_spec(spec)
    assert report["ok"] is False
    assert "audio_strategy" in report["missing"]


def test_spec_gate_shot_over_provider_cap_fails():
    report = check_generation_spec(_spec(
        total_duration_s=35.0, shot_count=1, shot_durations_s=[35.0]))
    assert report["ok"] is False
    assert any(i["code"] == "shot_over_provider_cap"
               for i in report["issues"])


def test_spec_gate_unknown_provider_fails():
    report = check_generation_spec(_spec(provider="gemini_api"))
    assert report["ok"] is False
    assert any(i["code"] == "tier_unknown" for i in report["issues"])


def test_spec_gate_no_provider_leaves_tier_not_checked():
    spec = _spec()
    del spec["provider"]
    report = check_generation_spec(spec)
    assert report["ok"] is True
    assert report["tier"]["status"] == "not_checked"


def test_spec_gate_explicit_caps_win_over_table():
    caps = resolve_provider_caps("fasth3_local")
    assert caps is not None
    caps = {**caps, "max_shot_s": 5.0}
    report = check_generation_spec(_spec(), provider_caps=caps)
    assert report["ok"] is False
    assert any(i["code"] == "shot_over_provider_cap"
               for i in report["issues"])


def test_spec_gate_sum_mismatch_fails():
    report = check_generation_spec(_spec(shot_durations_s=[10.0, 10.0, 5.0]))
    assert report["ok"] is False
    assert any(i["code"] == "shot_durations_sum_mismatch"
               for i in report["issues"])


def test_spec_gate_authorize_raises():
    with pytest.raises(CapabilityError):
        authorize_generation_spec(_spec(aspect="4:3"))


# --- A2: ban revision log ---

_BANS = [
    {"rule_id": "B1", "text": "不转正脸"},
    {"rule_id": "B2", "text": "不露背"},
]


def test_ban_revision_explicit_supersede_keeps_original():
    report = apply_ban_revisions(_BANS, [
        {"action": "supersede", "rule_id": "B1b", "supersedes": "B1",
         "text": "不转正脸，除非剧本要求"},
    ])
    assert report["ok"] is True
    assert [r["rule_id"] for r in report["rules"]] == ["B2", "B1b"]
    assert report["retired"] == [{
        "rule_id": "B1", "text": "不转正脸",
        "overturned_by": "B1b", "action": "supersede",
    }]
    assert report["rendered"] == ["不露背", "不转正脸，除非剧本要求"]


def test_ban_revision_silent_overwrite_fails():
    report = apply_ban_revisions(_BANS, [
        {"action": "add", "rule_id": "B1", "text": "可以转正脸"},
    ])
    assert report["ok"] is False
    assert any(i["code"] == "silent_overwrite" for i in report["issues"])


def test_ban_revision_supersede_missing_target_fails():
    report = apply_ban_revisions(_BANS, [
        {"action": "supersede", "rule_id": "B9", "supersedes": "B7",
         "text": "新规则"},
    ])
    assert report["ok"] is False
    assert any(i["code"] == "supersede_missing_target"
               for i in report["issues"])


def test_ban_revision_retire_keeps_original():
    report = apply_ban_revisions(_BANS, [
        {"action": "retire", "rule_id": "B2x", "supersedes": "B2"},
    ])
    assert report["ok"] is True
    assert [r["rule_id"] for r in report["rules"]] == ["B1"]
    assert report["retired"][0]["text"] == "不露背"


def test_ban_list_duplicate_rule_id_fails():
    report = apply_ban_revisions(
        _BANS + [{"rule_id": "B1", "text": "重复"}], [])
    assert report["ok"] is False
    assert any(i["code"] == "duplicate_rule_id" for i in report["issues"])


# --- A3: verdict vocabulary ---

def test_verdict_vocabulary_legacy_mapping():
    assert normalise_verdict(True) == "pass"
    assert normalise_verdict(False) == "fail"
    assert normalise_verdict(None) == "not_checked"
    assert normalise_verdict("skipped") == "not_checked"
    assert normalise_verdict("planned_not_measured") == "not_checked"
    assert normalise_verdict("PASS") == "pass"
    with pytest.raises(CapabilityError):
        normalise_verdict("roughly fine")
    with pytest.raises(CapabilityError):
        normalise_verdict(1)


def test_verdict_vocabulary_legacy_pass_roundtrip():
    assert to_legacy_pass("pass") is True
    assert to_legacy_pass("fail") is False
    assert to_legacy_pass("not_checked") is None


def test_verdict_summarise_all_or_nothing():
    assert summarise_verdicts(
        [{"verdict": "pass"}, {"verdict": "pass"}])["verdict"] == "pass"
    assert summarise_verdicts(
        [{"verdict": "pass"}, {"pass": None}])["verdict"] == "not_checked"
    assert summarise_verdicts(
        [{"verdict": "pass"}, {"verdict": "fail"}])["verdict"] == "fail"
    report = summarise_verdicts([{"pass": True}, {"verdict": "skipped"}])
    assert report["counts"] == {"pass": 1, "fail": 0, "not_checked": 1}


def test_verdict_summarise_disagreement_fails():
    report = summarise_verdicts([{"verdict": "pass", "pass": False}])
    assert report["ok"] is False
    assert report["verdict"] == "fail"


# --- A4: post-production checklist ---

def _checklist(**overrides):
    items = {name: "done" for name in (
        "subtitles", "title_card", "watermark_credit", "music_replace",
        "speed_change", "assembly", "freeze_frame_pad")}
    items.update(overrides)
    return items


def test_post_checklist_all_done_passes():
    report = check_post_checklist(_checklist())
    assert report["verdict"] == "pass"


def test_post_checklist_pending_is_not_checked_not_pass():
    report = check_post_checklist(_checklist(music_replace="pending"))
    assert report["verdict"] == "not_checked"
    assert report["ok"] is True


def test_post_checklist_missing_item_fails():
    items = _checklist()
    del items["subtitles"]
    report = check_post_checklist(items)
    assert report["ok"] is False
    assert report["verdict"] == "fail"


def test_generation_side_post_task_fails():
    report = check_generation_side(["subtitles", "assembly"])
    assert report["ok"] is False
    assert len(report["issues"]) == 2


def test_generation_side_phrase_fails_but_post_marker_passes():
    report = check_generation_side(prompt_text="请生成字幕并烧录进画面")
    assert report["ok"] is False
    report = check_generation_side(
        prompt_text="[字幕·后期叠加，不进画面生成]台词在此")
    assert report["ok"] is True


def test_freeze_pad_threshold_is_caller_supplied():
    with pytest.raises(CapabilityError):
        check_freeze_pad_rule(0.2, threshold_s=None)
    assert check_freeze_pad_rule(0.2, threshold_s=0.5)["verdict"] == "pass"
    assert check_freeze_pad_rule(0.6, threshold_s=0.5)["verdict"] == "fail"


# --- B1: reference role gate ---

def _role_image(role, duty, reviewed=True):
    return {"role": role, "duty": duty, "file": f"{role}.png",
            "sha256": "a" * 64, "reviewed": reviewed,
            "reviewed_by": "reviewer"}


def test_reference_roles_four_jobs_pass():
    plan = {"images": [
        _role_image("identity", "管脸、年龄、发型"),
        _role_image("costume", "管颜色、面料、纹样"),
        _role_image("pose", "管起始姿态"),
        _role_image("scene", "管背景、光线、空间"),
    ]}
    report = check_reference_roles(plan)
    assert report["ok"] is True
    assert report["verdict"] == "pass"


def test_reference_roles_two_jobs_pass():
    plan = {"images": [
        _role_image("identity", "管脸"),
        _role_image("scene", "管背景"),
    ]}
    assert check_reference_roles(plan)["ok"] is True


def test_reference_roles_five_images_fail():
    plan = {"images": [
        _role_image("identity", "管脸"),
        _role_image("costume", "管服装"),
        _role_image("pose", "管姿态"),
        _role_image("scene", "管场景"),
        {"role": "identity", "duty": "多一张", "file": "x.png",
         "sha256": "b" * 64, "reviewed": True, "reviewed_by": "r"},
    ]}
    report = check_reference_roles(plan)
    assert report["ok"] is False
    assert any(i["code"] == "too_many_images" for i in report["issues"])


def test_reference_roles_duplicate_role_fails():
    plan = {"images": [
        _role_image("identity", "管脸"),
        _role_image("identity", "也管脸"),
    ]}
    report = check_reference_roles(plan)
    assert report["ok"] is False
    assert any(i["code"] == "duplicate_role" for i in report["issues"])


def test_reference_roles_unreviewed_definition_fails():
    plan = {"images": [_role_image("pose", "管姿态", reviewed=False)]}
    report = check_reference_roles(plan)
    assert report["ok"] is False
    assert any(i["code"] == "unreviewed_pose" for i in report["issues"])


def test_reference_roles_missing_role_field_fails():
    plan = {"images": [{"duty": "没有角色", "file": "x.png",
                        "sha256": "b" * 64, "reviewed": True,
                        "reviewed_by": "r"}]}
    report = check_reference_roles(plan)
    assert report["ok"] is False
    assert any(i["code"] == "bad_role" for i in report["issues"])


def test_reference_roles_h3_route_is_boundary_not_checked():
    report = check_reference_roles(
        {"route": "h3_scene_assembly", "images": []})
    assert report["ok"] is True
    assert report["verdict"] == "not_checked"
    assert report["boundary"]["h3_picture_budget"] == 9
    assert report["boundary"]["h3_voice_budget"] == 3


# --- B2: hardest-shot pilot ---

def _shots():
    return [
        {"shot_id": "S1", "difficulty": {"big_motion": False}},
        {"shot_id": "S2", "difficulty": {"big_motion": True, "turn": True,
                                         "complex_camera": True}},
        {"shot_id": "S3", "difficulty": {"costume_change": True}},
    ]


def test_pilot_difficulty_scoring_and_selection():
    assert difficulty_score(_shots()[1])["score"] == 3
    report = check_pilot_batch(
        _shots(), pilot_shot_id="S2", pilot_result="pass", pilot_units=1,
        total_units=6, batch_units=3, reserve_fraction=0.25)
    assert report["ok"] is True
    assert report["pilot"]["difficulty_score"] == 3


def test_pilot_wrong_shot_fails():
    report = check_pilot_batch(
        _shots(), pilot_shot_id="S1", pilot_result="pass", pilot_units=1,
        total_units=6, batch_units=3, reserve_fraction=0.25)
    assert report["ok"] is False
    assert any(i["code"] == "pilot_not_hardest" for i in report["issues"])


def test_pilot_failed_refuses_batch():
    report = check_pilot_batch(
        _shots(), pilot_shot_id="S2", pilot_result="fail", pilot_units=1,
        total_units=6, batch_units=3, reserve_fraction=0.25)
    assert report["ok"] is False
    assert any(i["code"] == "pilot_failed" for i in report["issues"])


def test_pilot_not_checked_refuses_batch():
    report = check_pilot_batch(
        _shots(), pilot_shot_id="S2", pilot_result="not_checked",
        pilot_units=1, total_units=6, batch_units=3, reserve_fraction=0.25)
    assert report["ok"] is False
    assert any(i["code"] == "pilot_not_checked" for i in report["issues"])


def test_pilot_reserve_exhausted_refuses_batch():
    report = check_pilot_batch(
        _shots(), pilot_shot_id="S2", pilot_result="pass", pilot_units=1,
        total_units=6, batch_units=5, reserve_fraction=0.25)
    assert report["ok"] is False
    assert any(i["code"] == "reserve_exhausted" for i in report["issues"])


def test_pilot_reserve_fraction_required():
    report = check_pilot_batch(
        _shots(), pilot_shot_id="S2", pilot_result="pass", pilot_units=1,
        total_units=6, batch_units=3, reserve_fraction=None)
    assert report["ok"] is False
    assert any(i["code"] == "bad_reserve_fraction" for i in report["issues"])


# --- B3: three-layer clip ---

def test_three_layer_fixtures_versioned_and_passing():
    assert THREE_LAYER_FIXTURE_VERSION == "2"
    for fixture in build_three_layer_fixtures():
        report = check_three_layer_clip(fixture["clip"])
        assert report["verdict"] == fixture["expect"], fixture["name"]


def test_three_layer_render_has_each_layer_once():
    clip = build_three_layer_fixtures()[0]["clip"]
    report = check_three_layer_clip(clip, bans="禁令：无文字")
    assert report["ok"] is True
    rendered = report["rendered"]
    assert rendered is not None
    assert rendered.count("[公共约束]") == 1
    assert rendered.count("[静图瞬间]") == 1
    assert rendered.count("[分阶段动作]") == 1
    assert "[禁令]禁令：无文字" in rendered


def test_three_layer_two_actions_fail():
    clip = build_three_layer_fixtures()[1]["clip"]
    report = check_three_layer_clip(clip)
    assert report["verdict"] == "fail"
    assert any(i["code"] == "too_many_actions" for i in report["issues"])


def test_three_layer_explicit_clauses_win():
    beat = {"action": "阿兰抬起手同时保持微笑",
            "action_clauses": ["阿兰抬起手"]}
    assert count_action_clauses(beat)["count"] == 1
    assert count_action_clauses(beat)["source"] == "explicit"


def test_three_layer_gap_fails():
    clip = build_three_layer_fixtures()[0]["clip"]
    clip["beats"][1]["t_start_s"] = 4.0
    report = check_three_layer_clip(clip)
    assert report["verdict"] == "fail"
    assert any(i["code"] == "beat_gap" for i in report["issues"])


# --- B4: fix ticket ---

def _ticket(**overrides):
    ticket = {"timecode": "00:09", "segment": "S02",
              "check_item": "camera_turns_to_back",
              "verdict": "fail",
              "evidence_frame": {"t_s": 9.0, "frame_no": 270}}
    ticket.update(overrides)
    return ticket


def test_timecode_parsing():
    assert parse_timecode("00:09")["seconds_s"] == 9.0
    assert parse_timecode("01:02:03")["seconds_s"] == 3723.0
    assert parse_timecode("00:09.5")["seconds_s"] == 9.5
    assert parse_timecode("9 seconds")["ok"] is False


def test_fix_ticket_good_ticket_passes():
    report = check_fix_ticket(_ticket())
    assert report["ok"] is True
    assert report["seconds_s"] == 9.0


def test_fix_ticket_without_timecode_refused():
    ticket = _ticket()
    del ticket["timecode"]
    report = check_fix_ticket(ticket)
    assert report["ok"] is False
    assert any(i["code"] == "bad_timecode" for i in report["issues"])


def test_fix_ticket_fail_without_evidence_frame_refused():
    ticket = _ticket()
    del ticket["evidence_frame"]
    report = check_fix_ticket(ticket)
    assert report["ok"] is False
    assert any(i["code"] == "fail_without_evidence_frame"
               for i in report["issues"])


def test_fix_ticket_vague_verdict_refused():
    report = check_fix_ticket(_ticket(verdict="looks off"))
    assert report["ok"] is False
    assert any(i["code"] == "bad_verdict" for i in report["issues"])


def test_fix_ticket_locates_beat():
    beats = [
        {"t_start_s": 0.0, "t_end_s": 3.0},
        {"t_start_s": 3.0, "t_end_s": 7.0},
        {"t_start_s": 7.0, "t_end_s": 10.0},
    ]
    located = locate_ticket(_ticket(), beats)
    assert located["located"] is True
    assert located["beat_index"] == 2
    unlocated = locate_ticket(_ticket(timecode="00:15"), beats)
    assert unlocated["located"] is False
    assert any(i["code"] == "ticket_unlocatable"
               for i in unlocated["issues"])


# --- Registration ---

def test_new_capabilities_registered():
    for name in (
        "qa.generation_spec_gate",
        "qa.ban_revision_log",
        "qa.verdict_vocabulary",
        "qa.post_production_checklist",
        "qa.reference_role_gate",
        "qa.hardest_shot_pilot",
        "qa.three_layer_clip",
        "qa.fix_ticket",
    ):
        assert get(name) is not None, name
