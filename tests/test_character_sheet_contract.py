"""Tests for qa.character_sheet_contract (clean-room rewrite).

At least one positive and one negative case per P1 rule, plus the
byte-determinism and golden-fixture cases, the silent-upgrade
refusal, the layout OFF/ON branches, the atlas ban, and the
style-adds-object ban.
"""

from __future__ import annotations

import pytest

from hevi.capabilities import character_sheet_contract as csc
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import get


def _good_state(**overrides):
    state = {
        "schema_version": 3,
        "sheet_id": "sheet-1",
        "views": ["face_front", "body_front"],
    }
    state.update(overrides)
    return state


def _good_plan(**overrides):
    plan = {
        "state": _good_state(),
        "layout": {
            "mode": "off",
            "guidance_note": "semantic guidance, not a hard constraint",
        },
        "style": {
            "name": "watercolor",
            "changed": ["brushwork", "texture"],
            "added_elements": [],
            "preserved": ["face", "proportion", "costume"],
        },
    }
    plan.update(overrides)
    return plan


# ---------------------------------------------------------------- state contract

def test_current_state_passes():
    result = csc.validate_sheet_state(_good_state())
    assert result["verdict"] == "pass"
    assert result["issues"] == []
    assert result["schema_version"] == 3


def test_unknown_state_key_fails():
    result = csc.validate_sheet_state(_good_state(surprise_field=1))
    assert result["verdict"] == "fail"
    assert any(i["code"] == "UNKNOWN_STATE_KEY" for i in result["issues"])


def test_missing_required_key_fails():
    state = _good_state()
    del state["sheet_id"]
    result = csc.validate_sheet_state(state)
    assert result["verdict"] == "fail"
    assert any(i["code"] == "MISSING_STATE_KEY" for i in result["issues"])


def test_unsupported_schema_version_fails():
    result = csc.validate_sheet_state(_good_state(schema_version=9))
    assert result["verdict"] == "fail"
    assert any(i["code"] == "UNSUPPORTED_SCHEMA_VERSION"
               for i in result["issues"])


def test_old_schema_without_migration_fails():
    result = csc.validate_sheet_state(_good_state(schema_version=2))
    assert result["verdict"] == "fail"
    assert any(i["code"] == "SILENT_UPGRADE" for i in result["issues"])


def test_old_schema_with_migration_passes():
    state = _good_state(
        schema_version=2,
        migration={"from_version": 2, "to_version": 3})
    assert csc.validate_sheet_state(state)["verdict"] == "pass"


def test_old_schema_with_wrong_migration_fails():
    state = _good_state(
        schema_version=1,
        migration={"from_version": 2, "to_version": 3})
    result = csc.validate_sheet_state(state)
    assert any(i["code"] == "SILENT_UPGRADE" for i in result["issues"])


def test_unknown_view_fails():
    result = csc.validate_sheet_state(_good_state(views=["no_such_view"]))
    assert any(i["code"] == "UNKNOWN_VIEW" for i in result["issues"])


def test_overlong_directive_fails():
    state = _good_state(part_directives=[
        {"part": "face", "text": "x" * 1001}])
    result = csc.validate_sheet_state(state)
    assert any(i["code"] == "DIRECTIVE_TOO_LONG" for i in result["issues"])


def test_non_object_state_raises():
    with pytest.raises(CapabilityError):
        csc.validate_sheet_state(["not", "an", "object"])


def test_canonical_bytes_deterministic_regardless_of_key_order():
    first = csc.canonical_sheet_bytes({"b": 1, "a": [1, 2]})
    second = csc.canonical_sheet_bytes({"a": [1, 2], "b": 1})
    assert first == second


def test_canonical_bytes_golden_fixture():
    # Exact bytes pinned: any serialisation change breaks this test
    # on purpose, so a drift is reviewed, not silently absorbed.
    expected = b'{"schema_version":3,"sheet_id":"s1","views":["face_front"]}'
    assert csc.canonical_sheet_bytes({
        "views": ["face_front"], "sheet_id": "s1", "schema_version": 3,
    }) == expected


# ---------------------------------------------------------------- layout guide

def test_layout_off_passes():
    result = csc.check_layout_guide(_good_plan())
    assert result["verdict"] == "pass"
    assert result["mode"] == "off"


def test_layout_off_with_guide_image_fails():
    plan = _good_plan(layout={
        "mode": "off",
        "guidance_note": "semantic guidance, not a hard constraint",
        "guide_image": {"source": "self_drawn", "declaration": "drawn here"},
    })
    result = csc.check_layout_guide(plan)
    assert any(i["code"] == "GUIDE_IMAGE_WHILE_OFF"
               for i in result["issues"])


def test_layout_on_self_drawn_passes():
    plan = _good_plan(layout={
        "mode": "on",
        "guidance_note": "语义指导，不是硬约束",
        "guide_image": {
            "source": "self_drawn",
            "declaration": "neutral silhouette drawn in-house",
        },
    })
    assert csc.check_layout_guide(plan)["verdict"] == "pass"


def test_layout_on_atlas_source_fails():
    plan = _good_plan(layout={
        "mode": "on",
        "guidance_note": "semantic guidance, not a hard constraint",
        "guide_image": {"source": "mannequin_atlas", "declaration": "atlas"},
    })
    result = csc.check_layout_guide(plan)
    assert any(i["code"] == "ATLAS_FORBIDDEN" for i in result["issues"])


def test_layout_on_without_declaration_fails():
    plan = _good_plan(layout={
        "mode": "on",
        "guidance_note": "semantic guidance, not a hard constraint",
        "guide_image": {"source": "self_drawn", "declaration": "  "},
    })
    result = csc.check_layout_guide(plan)
    assert any(i["code"] == "GUIDE_DECLARATION_MISSING"
               for i in result["issues"])


def test_layout_without_guidance_marker_fails():
    plan = _good_plan(layout={"mode": "off", "guidance_note": "put it here"})
    result = csc.check_layout_guide(plan)
    assert any(i["code"] == "MISSING_GUIDANCE_MARKER"
               for i in result["issues"])


# ---------------------------------------------------------------- style

def test_style_only_painting_passes():
    assert csc.check_style_only(_good_plan()["style"])["verdict"] == "pass"


def test_style_unknown_name_fails():
    style = {"name": "claymation", "changed": ["texture"],
             "added_elements": []}
    result = csc.check_style_only(style)
    assert any(i["code"] == "UNKNOWN_STYLE" for i in result["issues"])


def test_style_adding_scenery_fails():
    style = {"name": "anime", "changed": ["line"],
             "added_elements": ["cherry tree backdrop"]}
    result = csc.check_style_only(style)
    assert any(i["code"] == "STYLE_ADDS_OBJECT" for i in result["issues"])


def test_style_changing_costume_fails():
    style = {"name": "photo", "changed": ["costume", "shading"],
             "added_elements": []}
    result = csc.check_style_only(style)
    assert any(i["code"] == "STYLE_CHANGES_SUBJECT"
               for i in result["issues"])


def test_style_none_with_no_change_passes():
    assert csc.check_style_only(
        {"name": "none", "changed": [], "added_elements": []}
    )["verdict"] == "pass"


# ---------------------------------------------------------------- combined

def test_combined_plan_passes():
    result = csc.check_sheet_contract(_good_plan())
    assert result["verdict"] == "pass"
    assert result["state"]["verdict"] == "pass"
    assert result["layout"]["verdict"] == "pass"
    assert result["style"]["verdict"] == "pass"


def test_combined_plan_reports_each_failing_part():
    plan = _good_plan(
        state=_good_state(schema_version=2),
        style={"name": "anime", "changed": ["line"],
               "added_elements": ["a new prop"]})
    result = csc.check_sheet_contract(plan)
    assert result["verdict"] == "fail"
    assert result["state"]["verdict"] == "fail"
    assert result["style"]["verdict"] == "fail"


def test_capability_registered():
    assert get("qa.character_sheet_contract").name == "qa.character_sheet_contract"
