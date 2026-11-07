"""Tests for the portrait 8-dimension graft (clean-room).

A gates judge plans; B1 serves the 32-entry extension vocabulary;
B2 assembles gated prompts.  No image API, key, model, or article
text is involved anywhere in this file, and no effectiveness
claim is used as a threshold.  Adult portraits only: the adult
gate is a hard intercept in every assembly test.
"""

from __future__ import annotations

import json

import pytest

from hevi.capabilities import names as _capability_names
from hevi.capabilities.adult_portrait_gate import check_adult_portrait
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.negative_prompt_firewall_gate import (
    check_negative_prompt_firewall,
)
from hevi.capabilities.physical_language_gate import check_physical_language
from hevi.capabilities.portrait_eight_dim_assembler import (
    assemble_eight_dim_plan,
)
from hevi.capabilities.portrait_eight_dim_vocab import (
    _render_eight_dim_vocab,
)
from hevi.capabilities.restraint_ceiling_gate import check_restraint_ceiling
from hevi.image.portrait_vocab import eight_dim as ed


def _valid_dimensions(**overrides):
    dims = {
        "anchoring": "复古杂志影调，编辑时尚肖像",
        "fabric": "FA-01",
        "expression": "EX-01",
        "lens": "LE-01",
        "light": "SL-01",
        "environment": "背景虚化，柔和的咖啡馆晨光",
        "restraint": "克制自然，不过度修饰",
        "negatives": ["extra limbs", "plastic skin", "over-smoothed texture"],
    }
    dims.update(overrides)
    return dims


def _valid_plan(**overrides):
    plan = {
        "age_years": 25,
        "subject_text": "25 岁成年女性",
        "identity": "脸型五官按参考图",
        "framing": "拍到胸部以上",
    }
    plan.update(_valid_dimensions())
    plan.update(overrides)
    return plan


# ---- A1: negative-prompt firewall ----

FIREWALL_OK = ["extra limbs", "plastic skin", "over-smoothed texture"]


def test_firewall_all_classes_pass():
    report = check_negative_prompt_firewall({"negatives": FIREWALL_OK})
    assert report["verdict"] == "pass"
    assert report["covered"] == ["deformation", "cgi_look", "over_smoothing"]


def test_firewall_missing_deformation_fails():
    report = check_negative_prompt_firewall(
        {"negatives": ["plastic skin", "over-smoothed texture"]}
    )
    assert report["verdict"] == "fail"
    assert any("deformation" in i for i in report["issues"])


def test_firewall_missing_cgi_fails():
    report = check_negative_prompt_firewall(
        {"negatives": ["extra limbs", "over-smoothed texture"]}
    )
    assert report["verdict"] == "fail"
    assert any("cgi_look" in i for i in report["issues"])


def test_firewall_missing_smoothing_fails():
    report = check_negative_prompt_firewall(
        {"negatives": ["extra limbs", "plastic skin"]}
    )
    assert report["verdict"] == "fail"
    assert any("over_smoothing" in i for i in report["issues"])


def test_firewall_empty_fails():
    report = check_negative_prompt_firewall({"negatives": []})
    assert report["verdict"] == "fail"


def test_firewall_leading_no_stripped():
    report = check_negative_prompt_firewall(
        {"negatives": ["no extra limbs", "no doll face", "no waxy skin"]}
    )
    assert report["verdict"] == "pass"


def test_firewall_non_dict_raises():
    with pytest.raises(CapabilityError):
        check_negative_prompt_firewall(None)


# ---- A2: physical language ----

def test_physical_language_valid_passes():
    report = check_physical_language({"dimensions": _valid_dimensions()})
    assert report["verdict"] == "pass", report["issues"]


def test_physical_language_missing_dimension_fails():
    dims = _valid_dimensions()
    del dims["lens"]
    report = check_physical_language({"dimensions": dims})
    assert report["verdict"] == "fail"
    assert any("dim_missing: lens" in i for i in report["issues"])


def test_physical_language_vague_anchoring_fails():
    dims = _valid_dimensions(anchoring="美丽漂亮精致的她")
    report = check_physical_language({"dimensions": dims})
    assert report["verdict"] == "fail"
    assert any("anchoring" in i for i in report["issues"])


def test_physical_language_environment_without_depth_fails():
    dims = _valid_dimensions(environment="温馨的咖啡馆氛围，氛围感十足")
    report = check_physical_language({"dimensions": dims})
    assert report["verdict"] == "fail"
    assert any("environment" in i for i in report["issues"])


def test_physical_language_adjective_stack_fabric_fails():
    dims = _valid_dimensions(fabric="美丽漂亮的衣服")
    report = check_physical_language({"dimensions": dims})
    assert report["verdict"] == "fail"
    assert any("fabric" in i for i in report["issues"])


def test_physical_language_non_dict_raises():
    with pytest.raises(CapabilityError):
        check_physical_language(None)


# ---- A3: adult portrait ----

def test_adult_age_25_passes():
    report = check_adult_portrait({"age_years": 25, "subject_text": "成年女性"})
    assert report["verdict"] == "pass"
    assert report["declared_age"] == 25


def test_adult_missing_age_fails():
    report = check_adult_portrait({"subject_text": "成年女性"})
    assert report["verdict"] == "fail"
    assert any("age_undeclared" in i for i in report["issues"])


def test_adult_age_17_fails():
    report = check_adult_portrait({"age_years": 17})
    assert report["verdict"] == "fail"
    assert any("age_under_18" in i for i in report["issues"])


def test_adult_declaration_16_fails():
    report = check_adult_portrait({"age_declaration": "16岁"})
    assert report["verdict"] == "fail"


def test_adult_declaration_25_passes():
    report = check_adult_portrait({"age_declaration": "25 years old"})
    assert report["verdict"] == "pass"
    assert report["declared_age"] == 25


def test_adult_minor_term_hard_intercept():
    report = check_adult_portrait(
        {"age_years": 25, "subject_text": "未成年学生"}
    )
    assert report["verdict"] == "fail"
    assert any("minor_indicator" in i for i in report["issues"])


def test_adult_digit_string_age_passes():
    report = check_adult_portrait({"age_years": "30"})
    assert report["verdict"] == "pass"


def test_adult_bool_age_fails():
    report = check_adult_portrait({"age_years": True})
    assert report["verdict"] == "fail"


# ---- A4: restraint ceiling ----

def test_restraint_clean_passes():
    report = check_restraint_ceiling(
        {"picks": {"gaze": "GA-01"}, "text": "目光落在镜头，脸可略侧"}
    )
    assert report["verdict"] == "pass"


def test_restraint_seated_motion_conflict_fails():
    # Sitting + walking: the assembler's seated-blocked-motion rule.
    report = check_restraint_ceiling(
        {"picks": {"sitting": "SI-02", "motion": "MO-01"}, "text": ""}
    )
    assert report["verdict"] == "fail"
    assert any("conflict" in i for i in report["issues"])


def test_restraint_conflict_via_find_conflicts():
    from hevi.image.portrait_vocab.assemble import find_conflicts

    conflicts = find_conflicts(
        [
            {"id": "GA-08", "category": "gaze"},
            {"id": "GA-01", "category": "gaze"},
        ]
    )
    assert conflicts, "closed eyes x looking at camera must conflict"
    report = check_restraint_ceiling(
        {"picks": {}, "text": "夸张的五官，极致妆容"}
    )
    assert report["verdict"] == "fail"


def test_restraint_exaggeration_fails():
    report = check_restraint_ceiling({"picks": {}, "text": "五官夸张，妆容极致"})
    assert report["verdict"] == "fail"
    assert any("exaggeration" in i for i in report["issues"])


def test_restraint_synonym_stack_fails():
    report = check_restraint_ceiling(
        {"picks": {}, "text": "柔和温柔温暖亲切的微笑"}
    )
    assert report["verdict"] == "fail"
    assert any("synonym_stack" in i for i in report["issues"])


def test_restraint_two_synonyms_pass():
    report = check_restraint_ceiling(
        {"picks": {}, "text": "柔和的晨光，温柔的表情"}
    )
    assert report["verdict"] == "pass"


# ---- B1: extension vocabulary ----

def test_extension_index_counts():
    assert ed.load_index()["total"] == 32
    assert ed.counts() == {
        "fabric": 8,
        "skin_light": 8,
        "lens_optics": 8,
        "micro_expression": 8,
    }


def test_extension_search_finds_silk():
    hits = ed.search(query="silk")
    assert [h["id"] for h in hits] == ["FA-01"]


def test_extension_get_entry_by_chinese_name():
    assert ed.get_entry("轮廓光")["id"] == "SL-01"


def test_extension_unknown_category_raises():
    with pytest.raises(ed.EightDimVocabError):
        ed.entries("no_such_category")


def test_extension_entry_shape_matches_66():
    for entry in ed.entries():
        assert set(entry) == {"id", "category", "zh", "en", "how", "feeling"}


# ---- B2: assembler ----

def test_assembler_valid_plan():
    result = assemble_eight_dim_plan(_valid_plan())
    assert result["gates"] == {
        "adult": "pass",
        "firewall": "pass",
        "physical_language": "pass",
        "restraint": "pass",
    }
    assert result["entry_ids"] == ["FA-01", "EX-01", "LE-01", "SL-01"]
    assert "生丝面料垂落贴身" in result["prompt_zh"]
    assert "85mm portrait focal length" in result["prompt_en"]
    assert "extra limbs" in result["negative_prompt"]
    assert "extra limbs" not in result["prompt_zh"]
    assert result["declared_age"] == 25
    assert result["adult_only"] is True


def test_assembler_second_combination():
    result = assemble_eight_dim_plan(
        _valid_plan(fabric="FA-04", expression="EX-07", lens="LE-03", light="SL-02")
    )
    assert result["entry_ids"] == ["FA-04", "EX-07", "LE-03", "SL-02"]
    assert "天鹅绒" in result["prompt_zh"] or "绒面吸光" in result["prompt_zh"]
    assert "f/1.8 aperture" in result["prompt_en"]


def test_assembler_third_combination_by_name():
    result = assemble_eight_dim_plan(
        _valid_plan(
            fabric="亚麻衬衫",
            expression="垂目出神",
            lens="浅景深",
            light="眼神光",
        )
    )
    assert result["entry_ids"] == ["FA-03", "EX-06", "LE-05", "SL-07"]


def test_assembler_missing_lens_refused():
    plan = _valid_plan()
    del plan["lens"]
    with pytest.raises(CapabilityError):
        assemble_eight_dim_plan(plan)


def test_assembler_underage_refused():
    with pytest.raises(CapabilityError):
        assemble_eight_dim_plan(_valid_plan(age_years=16))


def test_assembler_missing_firewall_class_refused():
    with pytest.raises(CapabilityError):
        assemble_eight_dim_plan(
            _valid_plan(negatives=["extra limbs", "plastic skin"])
        )


def test_assembler_wrong_category_pick_refused():
    with pytest.raises(CapabilityError):
        assemble_eight_dim_plan(_valid_plan(fabric="LE-01"))


# ---- Render smoke + registry ----

def test_vocab_render_writes_catalogue(tmp_path):
    result = _render_eight_dim_vocab(
        {"action": "list"}, tmp_path, duration=0.0, aspect="16:9", seed=0
    )
    payload = json.loads(
        (tmp_path / "portrait_eight_dim_catalogue.json").read_text(
            encoding="utf-8"
        )
    )
    assert payload["total"] == 32
    assert result.qa["returned"] == 32


def test_all_six_capabilities_registered():
    import hevi.capabilities.adult_portrait_gate  # noqa: F401
    import hevi.capabilities.negative_prompt_firewall_gate  # noqa: F401
    import hevi.capabilities.physical_language_gate  # noqa: F401
    import hevi.capabilities.portrait_eight_dim_assembler  # noqa: F401
    import hevi.capabilities.portrait_eight_dim_vocab  # noqa: F401
    import hevi.capabilities.restraint_ceiling_gate  # noqa: F401

    registered = set(_capability_names())
    for name in (
        "qa.negative_prompt_firewall",
        "qa.physical_language_gate",
        "qa.adult_portrait_gate",
        "qa.restraint_ceiling_gate",
        "image.portrait_eight_dim_vocab",
        "image.portrait_eight_dim_assembler",
    ):
        assert name in registered, name
