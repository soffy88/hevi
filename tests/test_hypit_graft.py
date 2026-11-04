"""Tests for the Hypit graft: A1-A6 gates and B1-B2 schemas.

All fixtures are written in our own words. No upstream DSL
text, example script, or cost figure is reproduced here.
"""

from __future__ import annotations

import pytest

from hevi.capabilities import code_rendered_text_gate as a4
from hevi.capabilities import cost_honesty_gate as a5
from hevi.capabilities import hypit_license_note as a6
from hevi.capabilities import three_layer_project_gate as a2
from hevi.capabilities import three_layer_project_schema as b2
from hevi.capabilities import variant_reuse_gate as a3
from hevi.capabilities import word_anchor_gate as a1
from hevi.capabilities import word_anchor_timeline_schema as b1
from hevi.capabilities.errors import CapabilityError


def _anchor_plan(**overrides):
    plan = {
        "script": [
            {
                "text": "The captain lifts the trophy as the crowd roars.",
                "anchors": [
                    {
                        "name": "trophy-lift",
                        "words": ["lifts", "the", "trophy"],
                        "attachments": [{"kind": "broll", "asset": "trophy-shot"}],
                    }
                ],
            }
        ],
        "reprojection_declared": True,
    }
    plan.update(overrides)
    return plan


def _layered_project(**overrides):
    project = {
        "source": {"script": "Host ranks the finalists.", "assets": ["stage"]},
        "recipe": {"parameters": {"palette": "navy", "font_size": 42}},
        "run_record": {
            "targets": ["final-cut"],
            "reuse": [{"build_id": "build-001", "artifact": "stage"}],
        },
    }
    project.update(overrides)
    return project


# A1: word-anchor gate


def test_a1_pass():
    report = a1.check_word_anchor(_anchor_plan())
    assert report["ok"] is True


def test_a1_unnamed_anchor_fails():
    plan = _anchor_plan()
    plan["script"][0]["anchors"][0]["name"] = "  "
    assert a1.check_word_anchor(plan)["ok"] is False


def test_a1_handwritten_timecode_fails():
    plan = _anchor_plan()
    plan["script"][0]["anchors"][0]["attachments"][0]["start_s"] = 3.5
    assert a1.check_word_anchor(plan)["ok"] is False


def test_a1_anchor_words_not_in_line_fails():
    plan = _anchor_plan()
    plan["script"][0]["anchors"][0]["words"] = ["moon", "landing"]
    assert a1.check_word_anchor(plan)["ok"] is False


def test_a1_missing_reprojection_fails():
    assert a1.check_word_anchor(_anchor_plan(reprojection_declared=False))["ok"] is False


def test_a1_anchor_without_attachments_fails():
    plan = _anchor_plan()
    plan["script"][0]["anchors"][0]["attachments"] = []
    assert a1.check_word_anchor(plan)["ok"] is False


# A2: three-layer project gate


def test_a2_pass():
    assert a2.check_three_layer_project(_layered_project())["ok"] is True


def test_a2_source_with_recipe_param_fails():
    project = _layered_project()
    project["source"]["palette"] = "navy"
    assert a2.check_three_layer_project(project)["ok"] is False


def test_a2_recipe_with_script_fails():
    project = _layered_project()
    project["recipe"]["script"] = "Host ranks the finalists."
    assert a2.check_three_layer_project(project)["ok"] is False


def test_a2_run_record_with_creation_fails():
    project = _layered_project()
    project["run_record"]["script"] = "A brand-new line."
    assert a2.check_three_layer_project(project)["ok"] is False


def test_a2_reuse_without_build_id_fails():
    project = _layered_project()
    project["run_record"]["reuse"] = [{"artifact": "stage"}]
    assert a2.check_three_layer_project(project)["ok"] is False


# A3: variant reuse gate


def _variant_plan(**overrides):
    plan = {
        "base_build_id": "build-001",
        "assets": [
            {"asset_id": "stage", "changed": False, "reused": True, "build_id": "build-001"},
            {"asset_id": "host-line", "changed": True, "reused": False},
        ],
        "rerun_scope": ["host-line"],
    }
    plan.update(overrides)
    return plan


def test_a3_pass():
    assert a3.check_variant_reuse(_variant_plan())["ok"] is True


def test_a3_unchanged_without_reuse_declaration_fails():
    plan = _variant_plan()
    plan["assets"][0]["reused"] = False
    assert a3.check_variant_reuse(plan)["ok"] is False


def test_a3_reuse_without_build_id_fails():
    plan = _variant_plan()
    del plan["assets"][0]["build_id"]
    assert a3.check_variant_reuse(plan)["ok"] is False


def test_a3_changed_asset_claimed_reused_fails():
    plan = _variant_plan()
    plan["assets"][1]["reused"] = True
    assert a3.check_variant_reuse(plan)["ok"] is False


def test_a3_rerun_scope_reaches_unchanged_fails():
    plan = _variant_plan(rerun_scope=["stage", "host-line"])
    assert a3.check_variant_reuse(plan)["ok"] is False


# A4: code-rendered text gate


def test_a4_pass():
    plan = {
        "text_items": [
            {
                "content": "Rank S",
                "kind": "ranking",
                "rendered_by": "code",
                "source_text": "Rank S",
            }
        ]
    }
    assert a4.check_code_rendered_text(plan)["ok"] is True


def test_a4_model_drawn_price_fails():
    plan = {"text_items": [{"content": "$19", "kind": "price", "rendered_by": "model"}]}
    assert a4.check_code_rendered_text(plan)["ok"] is False


def test_a4_code_text_mismatch_fails():
    plan = {
        "text_items": [
            {
                "content": "Rank S",
                "kind": "ranking",
                "rendered_by": "code",
                "source_text": "Rank A",
            }
        ]
    }
    assert a4.check_code_rendered_text(plan)["ok"] is False


# A5: cost honesty gate


def test_a5_measured_pass():
    claim = {
        "amount": 2.0,
        "currency": "USD",
        "basis": "measured",
        "breakdown": [{"amount": 1.2}, {"amount": 0.8}],
        "measured_evidence": "provider bill #4417",
        "verified": True,
    }
    assert a5.check_cost_honesty(claim)["ok"] is True


def test_a5_self_reported_pass():
    claim = {
        "amount": 2.0,
        "currency": "USD",
        "basis": "self_reported",
        "source": "upstream project write-up",
        "verified": False,
    }
    assert a5.check_cost_honesty(claim)["ok"] is True


def test_a5_no_basis_fails():
    claim = {"amount": 2.0, "currency": "USD"}
    assert a5.check_cost_honesty(claim)["ok"] is False


def test_a5_self_reported_claimed_measured_fails():
    claim = {
        "amount": 2.0,
        "currency": "USD",
        "basis": "self_reported",
        "source": "upstream project write-up",
        "verified": True,
    }
    assert a5.check_cost_honesty(claim)["ok"] is False


def test_a5_breakdown_mismatch_fails():
    claim = {
        "amount": 2.0,
        "currency": "USD",
        "basis": "measured",
        "breakdown": [{"amount": 1.0}],
        "measured_evidence": "provider bill #4417",
    }
    assert a5.check_cost_honesty(claim)["ok"] is False


# A6: licence note


def test_a6_canonical_notes_pass():
    for note in a6.hypit_license_notes():
        assert a6.check_license_note(note)["ok"] is True


def test_a6_missing_multi_tenant_restriction_fails():
    note = dict(a6.hypit_license_notes()[0])
    del note["multi_tenant_restriction"]
    assert a6.check_license_note(note)["ok"] is False


def test_a6_missing_redistribution_restriction_fails():
    note = dict(a6.hypit_license_notes()[0])
    del note["redistribution_restriction"]
    assert a6.check_license_note(note)["ok"] is False


def test_a6_missing_attribution_retention_fails():
    note = dict(a6.hypit_license_notes()[0])
    del note["attribution_retention"]
    assert a6.check_license_note(note)["ok"] is False


def test_a6_mit_claim_fails():
    note = dict(a6.hypit_license_notes()[0])
    note["license"] = "MIT"
    assert a6.check_license_note(note)["ok"] is False


# B1: word-anchor timeline schema


def _timeline_plan(**overrides):
    plan = {
        "anchors": [
            {
                "name": "trophy-lift",
                "words": ["lifts", "the", "trophy"],
                "attachments": [{"kind": "broll"}],
            }
        ],
        "alignment": {
            "steps": [
                "normalize_evidence_audio",
                "align_word_boundaries",
                "convert_to_sample_domain",
                "project_to_timeline",
            ],
            "sample_rate_hz": 16000,
            "word_boundaries": [
                {"word": "lifts", "start_sample": 16000, "end_sample": 16800},
                {"word": "trophy", "start_sample": 17600, "end_sample": 18400},
            ],
        },
        "placements": [{"anchor": "trophy-lift"}],
    }
    plan.update(overrides)
    return plan


def test_b1_contract_pass_and_fake():
    contract = b1.compile_word_anchor_timeline_contract(_timeline_plan())
    assert contract["executed_here"] is False
    assert contract["alignment_executed"] is False
    assert contract["output_file"] is None
    assert contract["word_boundary_count"] == 2


def test_b1_unknown_anchor_placement_fails():
    plan = _timeline_plan(placements=[{"anchor": "no-such-anchor"}])
    with pytest.raises(CapabilityError):
        b1.compile_word_anchor_timeline_contract(plan)


def test_b1_wrong_steps_fails():
    plan = _timeline_plan()
    plan["alignment"]["steps"] = ["align_word_boundaries"]
    with pytest.raises(CapabilityError):
        b1.compile_word_anchor_timeline_contract(plan)


# B2: three-layer project schema


def _schema_project(**overrides):
    project = {
        "source": {"script_lines": ["Host ranks the finalists."]},
        "recipe": {"name": "ranking-board", "parameters": {"palette": "navy"}},
        "run_record": {
            "targets": ["final-cut"],
            "reuse": [{"build_id": "build-001", "artifact": "stage"}],
        },
    }
    project.update(overrides)
    return project


def test_b2_contract_pass_and_fake():
    contract = b2.compile_three_layer_project_contract(_schema_project())
    assert contract["executed_here"] is False
    assert contract["rendered_here"] is False
    assert contract["output_file"] is None
    assert contract["source_lines"] == 1


def test_b2_missing_layer_fails():
    project = _schema_project()
    del project["recipe"]
    with pytest.raises(CapabilityError):
        b2.compile_three_layer_project_contract(project)


def test_b2_reuse_without_build_id_fails():
    project = _schema_project()
    project["run_record"]["reuse"] = [{"artifact": "stage"}]
    with pytest.raises(CapabilityError):
        b2.compile_three_layer_project_contract(project)
