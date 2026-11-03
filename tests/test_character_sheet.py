"""Tests for qa.character_sheet_gate (clean-room rewrite).

At least one positive and one negative case per grafted rule, plus
the missing-view pending branch, same-role conflict, and the rear
face ban.
"""

from __future__ import annotations

import json

import pytest

from hevi.capabilities import character_sheet as cs
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import get

ALL_VIEWS = list(cs.VIEW_IDS)


# ---------------------------------------------------------------- views

def test_full_detail_sheet_passes():
    result = cs.check_view_manifest(ALL_VIEWS, required=ALL_VIEWS)
    assert result["verdict"] == "pass"
    assert result["missing_views"] == []


def test_unknown_view_fails():
    result = cs.check_view_manifest(["face_front", "no_such_view"])
    assert result["verdict"] == "fail"
    assert any(i["code"] == "UNKNOWN_VIEW" for i in result["issues"])


def test_duplicate_current_view_fails():
    result = cs.check_view_manifest(["face_front", "face_front"])
    assert result["verdict"] == "fail"
    assert any(i["code"] == "DUPLICATE_VIEW" for i in result["issues"])


def test_missing_view_is_pending_not_fabricated():
    result = cs.check_view_manifest(["face_front"], required=["face_front", "hands"])
    assert result["verdict"] == "pending"
    assert result["missing_views"] == ["hands"]
    assert result["current_views"] == ["face_front"]


def test_detail_view_cannot_be_covered_by_full_body():
    result = cs.check_view_manifest(
        ["body_front"], required=["body_front", "hands"],
        claimed_substitutions={"hands": "body_front"})
    assert result["verdict"] == "fail"
    assert any(i["code"] == "DETAIL_NOT_SUBSTITUTED" for i in result["issues"])


def test_stale_view_does_not_count():
    result = cs.check_view_manifest(
        [{"view": "hands", "status": "stale"}],
        required=["hands"])
    assert result["verdict"] == "pending"
    assert result["missing_views"] == ["hands"]


def test_anatomical_side_convention():
    assert cs.LEFT_VIEWS <= set(cs.VIEW_IDS)
    assert cs.NOSE_EDGE["left"] == "right"
    assert cs.NOSE_EDGE["right"] == "left"
    assert cs.PRESETS["detail"] == tuple(ALL_VIEWS)


def test_anchor_sheet_views_reuse_catalogue():
    sheet = {"views": [{"view": "face_front", "status": "current"},
                       {"view": "hands", "status": "superseded"}]}
    result = cs.check_anchor_sheet_views(sheet, required=["face_front", "hands"])
    assert result["verdict"] == "pending"
    assert result["missing_views"] == ["hands"]


# ---------------------------------------------------------------- parts

def test_part_directive_in_scope_passes():
    result = cs.check_part_directives(
        [{"part": "face", "view": "face_front", "text": "red lips"}])
    assert result["verdict"] == "pass"


def test_part_directive_out_of_scope_fails():
    result = cs.check_part_directives(
        [{"part": "footwear", "view": "face_front", "text": "boots"}])
    assert result["verdict"] == "fail"
    assert any(i["code"] == "PART_VIEW_SCOPE" for i in result["issues"])


def test_face_directive_on_rear_view_fails():
    for view in ("face_back", "body_back", "clothing_back"):
        result = cs.check_part_directives(
            [{"part": "face", "view": view, "text": "smile"}])
        assert result["verdict"] == "fail", view
        assert any(i["code"] == "FACE_IN_REAR_VIEW" for i in result["issues"])


def test_back_clothing_on_front_view_fails():
    result = cs.check_part_directives(
        [{"part": "back_clothing", "view": "body_front", "text": "embroidery"}])
    assert result["verdict"] == "fail"
    assert any(i["code"] == "PART_VIEW_SCOPE" for i in result["issues"])


def test_back_clothing_beats_upper_clothing_on_rear_surface():
    result = cs.check_part_directives([
        {"part": "upper_clothing", "view": "body_left", "text": "blue robe"},
        {"part": "back_clothing", "view": "body_left", "text": "crane embroidery"},
    ])
    assert result["verdict"] == "pass"
    assert result["superseded_directives"][0]["part"] == "upper_clothing"
    assert result["effective_directives"][0]["part"] == "back_clothing"


def test_directive_text_is_literal_only():
    result = cs.check_part_directives(
        [{"part": "face", "view": "face_front", "text": "move to the top-left in 3 seconds"}])
    assert result["verdict"] == "pass"
    assert any(i["code"] == "LITERAL_ONLY" for i in result["issues"])
    assert result["effective_directives"][0]["literal_only"] is True
    assert result["effective_directives"][0]["literal_text"] == "move to the top-left in 3 seconds"


def test_unknown_part_fails():
    result = cs.check_part_directives(
        [{"part": "wings", "view": "body_front", "text": "wings"}])
    assert result["verdict"] == "fail"
    assert any(i["code"] == "UNKNOWN_PART" for i in result["issues"])


def test_custom_part_table_is_honoured():
    table = {"face": {"views": ("face_front",)}}
    result = cs.check_part_directives(
        [{"part": "face", "view": "face_left", "text": "x"}], part_table=table)
    assert result["verdict"] == "fail"


# ---------------------------------------------------------------- roles

def test_role_scopes_exclude_rear_views_for_face():
    result = cs.resolve_reference_roles(
        [{"role": "face", "ref_id": "r1"}], selected_views=ALL_VIEWS)
    assert result["verdict"] == "pass"
    entry = result["resolved_references"][0]
    assert "face_back" not in entry["views"]
    assert "body_back" not in entry["views"]
    assert entry["guidance_only"] is True


def test_same_role_conflict_later_wins():
    result = cs.resolve_reference_roles([
        {"role": "face", "ref_id": "old"},
        {"role": "face", "ref_id": "new"},
    ])
    assert result["verdict"] == "pass"
    assert [e["ref_id"] for e in result["resolved_references"]] == ["new"]
    assert result["superseded_references"][0]["ref_id"] == "old"
    assert any(i["code"] == "ROLE_CONFLICT_SUPERSEDED" for i in result["issues"])


def test_unknown_role_fails():
    result = cs.resolve_reference_roles([{"role": "aura", "ref_id": "r1"}])
    assert result["verdict"] == "fail"
    assert any(i["code"] == "UNKNOWN_ROLE" for i in result["issues"])


def test_explicit_directive_beats_role():
    result = cs.resolve_reference_roles(
        [{"role": "clothing", "ref_id": "r1"}],
        selected_views=["body_back"],
        explicit_directives=[{"part": "back_clothing", "view": "body_back", "text": "crane"}])
    entry = result["resolved_references"][0]
    assert "back_clothing on body_back" in entry["overridden_by_explicit_directive"]


def test_clothing_back_role_only_rear_views():
    result = cs.resolve_reference_roles(
        [{"role": "clothing_back", "ref_id": "r1"}], selected_views=ALL_VIEWS)
    entry = result["resolved_references"][0]
    assert entry["views"] == ["body_back", "body_left", "clothing_back"]


# ---------------------------------------------------------------- combined

def test_combined_plan_pass_and_pending():
    good = {"views": ALL_VIEWS, "required_views": ALL_VIEWS,
            "part_directives": [{"part": "face", "view": "face_front", "text": "calm"}],
            "references": [{"role": "face", "ref_id": "r1"}]}
    assert cs.check_character_sheet(good)["verdict"] == "pass"
    thin = {"views": ["face_front"], "required_views": ["face_front", "hands"]}
    result = cs.check_character_sheet(thin)
    assert result["verdict"] == "pending"
    assert result["view_manifest"]["missing_views"] == ["hands"]


def test_combined_plan_fail_beats_pending():
    plan = {"views": ["face_front"], "required_views": ["face_front", "hands"],
            "part_directives": [{"part": "face", "view": "body_back", "text": "smile"}]}
    assert cs.check_character_sheet(plan)["verdict"] == "fail"


def test_malformed_plan_raises():
    with pytest.raises(CapabilityError):
        cs.check_character_sheet("not a plan")


def test_capability_registered_and_renders_report(tmp_path):
    cap = get("qa.character_sheet_gate")
    result = cap.render(
        {"plan": {"views": ALL_VIEWS, "required_views": ALL_VIEWS}},
        tmp_path, duration=0.0, aspect="16:9", seed=1)
    report = json.loads((tmp_path / "character_sheet_gate.json").read_text(encoding="utf-8"))
    assert report["verdict"] == "pass"
    assert result.qa["verdict"] == "pass"
