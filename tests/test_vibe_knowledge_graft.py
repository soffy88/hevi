"""Tests for the vibe-knowledge graft (A1-A6 gates, B1-B4 contracts)."""

import pytest

from hevi.capabilities.registry import contains

from hevi.capabilities import (
    source_sentence_ledger as a1,
    premium_composition_gate as a2,
    duration_complexity_advisor as a3,
    quote_confirmation_gate as a4,
    narration_alignment_gate as a5,
    ai_disclosure_gate as a6,
    knowledge_film_templates as b1,
    style_catalog_schema as b2,
    knowledge_qc_contract as b3,
    two_tier_synthesis_contract as b4,
)


def _good_sentences():
    return [
        {
            "text": "The bridge opened in 1998.",
            "kind": "fact",
            "sources": [{"label": "City archive", "locator": "record 12"}],
        },
        {
            "text": "Imagine a city with no bridges at all.",
            "kind": "illustration",
            "illustrative_marker": True,
        },
    ]


def test_a1_pass_and_missing_source_fails():
    assert a1.check_source_sentence_ledger(
        {"sentences": _good_sentences()}
    )["verdict"] == "pass"
    bad = [
        {
            "text": "The bridge cost 40 million.",
            "kind": "fact",
            "sources": [],
        }
    ]
    report = a1.check_source_sentence_ledger({"sentences": bad})
    assert report["verdict"] == "fail"
    assert any(i["code"].endswith("source_missing") for i in report["issues"])


def test_a1_dispute_needs_both_sides():
    one_sided = [
        {
            "text": "Scholars disagree about the date.",
            "kind": "fact",
            "disputed": True,
            "sources": [
                {"label": "A", "locator": "p1", "side": "early"},
            ],
        }
    ]
    report = a1.check_source_sentence_ledger({"sentences": one_sided})
    assert report["verdict"] == "fail"
    assert any("dispute_one_sided" in i["code"] for i in report["issues"])
    two_sided = [
        {
            "text": "Scholars disagree about the date.",
            "kind": "fact",
            "disputed": True,
            "sources": [
                {"label": "A", "locator": "p1", "side": "early"},
                {"label": "B", "locator": "p2", "side": "late"},
            ],
        }
    ]
    assert a1.check_source_sentence_ledger(
        {"sentences": two_sided}
    )["verdict"] == "pass"


def test_a1_illustration_unmarked_and_as_fact_fail():
    unmarked = [
        {"text": "Picture a world of glass.", "kind": "illustration"}
    ]
    assert a1.check_source_sentence_ledger(
        {"sentences": unmarked}
    )["verdict"] == "fail"
    as_fact = [
        {
            "text": "Picture a world of glass.",
            "kind": "illustration",
            "illustrative_marker": True,
            "presented_as_fact": True,
            "sources": [{"label": "X", "locator": "y"}],
        }
    ]
    assert a1.check_source_sentence_ledger(
        {"sentences": as_fact}
    )["verdict"] == "fail"


def test_a2_pass_and_layer_and_still_fail():
    good = {
        "shots": [
            {
                "layers": ["base", "motion"],
                "longest_still_s": 2.0,
                "on_screen_text": [{"text": "short", "group": "a"}],
            }
        ]
    }
    assert a2.check_premium_composition(good)["verdict"] == "pass"
    thin = {"shots": [{"layers": ["base"], "longest_still_s": 1.0}]}
    assert a2.check_premium_composition(thin)["verdict"] == "fail"
    long_still = {
        "shots": [
            {"layers": ["base", "motion", "info"], "longest_still_s": 9.0}
        ]
    }
    report = a2.check_premium_composition(long_still)
    assert report["verdict"] == "fail"
    assert any("still_too_long" in i["code"] for i in report["issues"])


def test_a2_text_limits_caller_set():
    plan = {
        "max_on_screen_chars": 4,
        "max_on_screen_groups": 1,
        "shots": [
            {
                "layers": ["base", "info"],
                "on_screen_text": [
                    {"text": "toolong", "group": "a"},
                    {"text": "ok", "group": "b"},
                ],
            }
        ],
    }
    report = a2.check_premium_composition(plan)
    assert report["verdict"] == "fail"
    codes = [i["code"] for i in report["issues"]]
    assert any("too_long" in c for c in codes)
    assert any("too_many" in c for c in codes)
    assert report["thresholds_applied"]["max_on_screen_chars"] == 4


def test_a3_tier_mapping_and_gap_reminder():
    assessment = {
        "dimensions": {
            "concept_count": 0,
            "prerequisite_depth": 0,
            "evidence_density": 0,
            "abstraction_level": 0,
            "audience_unfamiliarity": 0,
        },
        "chars_per_second": 5.0,
        "declared_tier": "deep",
    }
    report = a3.advise_duration_complexity(assessment)
    assert report["verdict"] == "pass"
    assert report["computed_tier"] == "glance"
    assert len(report["reminders"]) == 1
    assert report["reminders"][0]["code"] == "tier_gap_two_or_more"


def test_a3_rate_required_and_dimension_range():
    no_rate = {
        "dimensions": {name: 1 for name in a3.DIMENSIONS},
    }
    report = a3.advise_duration_complexity(no_rate)
    assert report["verdict"] == "fail"
    assert any(
        i["code"] == "chars_per_second_missing" for i in report["issues"]
    )
    bad_score = {
        "dimensions": {name: 3 for name in a3.DIMENSIONS},
        "chars_per_second": 5.0,
    }
    assert a3.advise_duration_complexity(bad_score)["verdict"] == "fail"


def test_a4_pass_and_popup_refused():
    good = {
        "estimate": {
            "items": [{"name": "shot", "credits": 10}],
            "total_credits": 10,
        },
        "confirmation": {
            "confirmed": True,
            "source": "user_verbatim",
            "verbatim": "yes, go ahead at 10 credits",
        },
        "batch_size": 1,
    }
    report = a4.check_quote_confirmation(good)
    assert report["verdict"] == "pass"
    assert report["allowed"] is True
    popup = dict(good)
    popup["confirmation"] = {
        "confirmed": True,
        "source": "host_popup",
        "verbatim": "ok",
    }
    assert a4.check_quote_confirmation(popup)["verdict"] == "fail"
    blanket = dict(good)
    blanket["confirmation"] = {
        "confirmed": True,
        "source": "prior_blanket",
        "verbatim": "just generate",
    }
    assert a4.check_quote_confirmation(blanket)["verdict"] == "fail"


def test_a4_batch_needs_smoke_and_storyboard_delegated():
    batch = {
        "estimate": {
            "items": [{"name": "shot", "credits": 10}],
            "total_credits": 10,
        },
        "confirmation": {
            "confirmed": True,
            "source": "user_verbatim",
            "verbatim": "go",
        },
        "batch_size": 4,
        "smoke_passed": False,
    }
    assert a4.check_quote_confirmation(batch)["verdict"] == "fail"
    with_board = dict(batch)
    with_board["smoke_passed"] = True
    with_board["storyboard"] = [
        {"shot_id": "s1", "visual": "bridge", "duration_sec": 5}
    ]
    assert a4.check_quote_confirmation(with_board)["verdict"] == "pass"
    broken_board = dict(with_board)
    broken_board["storyboard"] = [{"shot_id": "s1"}]
    assert a4.check_quote_confirmation(broken_board)["verdict"] == "fail"


def test_a5_pass_clone_refused_without_authorisation():
    good = {
        "chars_per_second": 5.0,
        "max_gap_s": 0.2,
        "max_lead_s": 0.3,
        "readback_threshold": 0.95,
        "narration": {
            "text": "hello world",
            "measured_duration_s": 3.0,
            "evidence_id": "n1",
        },
        "beats": [{"gap_s": 0.1, "lead_s": 0.2}],
        "readback_ratio": 0.97,
        "voice": {"clone": False},
    }
    assert a5.check_narration_alignment(good)["verdict"] == "pass"
    cloned = dict(good)
    cloned["voice"] = {"clone": True, "voice_origin": "unknown"}
    report = a5.check_narration_alignment(cloned)
    assert report["verdict"] == "fail"
    codes = [i["code"] for i in report["issues"]]
    assert "clone_origin_unauthorised" in codes
    assert "clone_authorization_missing" in codes
    authorised = dict(good)
    authorised["voice"] = {
        "clone": True,
        "voice_origin": "self",
        "authorization": "self-recording consent on file",
    }
    assert a5.check_narration_alignment(authorised)["verdict"] == "pass"


def test_a5_thresholds_required_and_readback_fails():
    missing = {
        "narration": {
            "text": "hello",
            "measured_duration_s": 2.0,
            "evidence_id": "n1",
        },
        "beats": [{}],
    }
    report = a5.check_narration_alignment(missing)
    assert report["verdict"] == "fail"
    assert any(
        i["code"] == "chars_per_second_missing" for i in report["issues"]
    )
    low = {
        "chars_per_second": 5.0,
        "max_gap_s": 0.2,
        "max_lead_s": 0.3,
        "readback_threshold": 0.95,
        "narration": {
            "text": "hello world",
            "measured_duration_s": 3.0,
            "evidence_id": "n1",
        },
        "beats": [{"gap_s": 0.1, "lead_s": 0.2}],
        "readback_ratio": 0.5,
    }
    report = a5.check_narration_alignment(low)
    assert any(
        i["code"] == "readback_below_threshold" for i in report["issues"]
    )


def test_a6_living_face_refused_and_disclosure_required():
    living = {
        "frames": [
            {
                "depicts_real_person": True,
                "depicts_face": True,
                "person_status": "living",
                "ai_generated": True,
                "disclosure": "AI generated",
            }
        ]
    }
    report = a6.check_ai_disclosure(living)
    assert report["verdict"] == "fail"
    assert any("living_person_face" in i["code"] for i in report["issues"])
    historical = {
        "frames": [
            {
                "depicts_real_person": True,
                "depicts_face": True,
                "person_status": "historical",
                "ai_generated": True,
                "disclosure": "AI generated, illustrative",
                "illustrative_marker": True,
            }
        ]
    }
    assert a6.check_ai_disclosure(historical)["verdict"] == "pass"
    undisclosed = {
        "frames": [{"ai_generated": True, "disclosure": ""}]
    }
    assert a6.check_ai_disclosure(undisclosed)["verdict"] == "fail"


def test_b1_templates_closed_vocab_and_role_order():
    assert set(b1.list_templates()) == {
        "riddle_concept",
        "dilemma_choice",
        "pain_point_principle",
        "single_thread",
        "gauntlet",
        "six_facet_rotation",
    }
    template = b1.get_template("gauntlet")
    assert template["ok"] is True
    assert template["beat_count"] == 5
    assert b1.get_template("nope")["ok"] is False
    script = {
        "template": "single_thread",
        "beats": [
            {"role": "premise", "text": "p"},
            {"role": "first_link", "text": "a"},
            {"role": "second_link", "text": "b"},
            {"role": "consequence", "text": "c"},
            {"role": "takeaway", "text": "t"},
        ],
    }
    assert b1.check_script_against_template(script)["verdict"] == "pass"
    swapped = dict(script)
    swapped["beats"] = list(reversed(script["beats"]))
    assert b1.check_script_against_template(swapped)["verdict"] == "fail"
    too_long = dict(script)
    too_long["beats"] = [
        dict(beat) for beat in script["beats"]
    ]
    too_long["beats"][0] = {"role": "premise", "text": "x" * 71}
    assert b1.check_script_against_template(too_long)["verdict"] == "fail"


def test_b2_catalog_schema_and_inline_media_refused():
    good = {
        "families": [{"name": "ink"}],
        "styles": [
            {
                "id": "ink-01",
                "family": "ink",
                "fit": ["calm"],
                "templates": ["t1"],
                "verified": False,
                "assets": {
                    "still": {"location": "external", "locator": "s3://x/1.jpg"}
                },
            }
        ],
    }
    assert b2.validate_style_catalog(good)["verdict"] == "pass"
    inline = {
        "families": [{"name": "ink"}],
        "styles": [
            {
                "id": "ink-01",
                "family": "ink",
                "fit": ["calm"],
                "templates": ["t1"],
                "verified": False,
                "assets": {
                    "still": {
                        "location": "bundled",
                        "locator": "data:image/png;base64,AAA",
                    }
                },
            }
        ],
    }
    assert b2.validate_style_catalog(inline)["verdict"] == "fail"
    undeclared = {
        "families": [{"name": "ink"}],
        "styles": [
            {
                "id": "ink-01",
                "family": "other",
                "fit": ["calm"],
                "templates": ["t1"],
                "verified": True,
            }
        ],
    }
    assert b2.validate_style_catalog(undeclared)["verdict"] == "fail"


def _qc_checks(**overrides):
    base = [
        {"kind": "contact_sheet", "executed_here": False},
        {
            "kind": "ocr_readback",
            "executed_here": False,
            "ocr_platform": "macos_vision",
            "ocr_linux_available": False,
        },
        {"kind": "loudness", "executed_here": False},
        {"kind": "freeze_detection", "executed_here": False},
        {"kind": "bgm_correlation", "executed_here": False},
    ]
    for index, patch in overrides.items():
        base[int(index)].update(patch)
    return base


def test_b3_contract_pass_execution_claim_and_linux_lock():
    report = b3.check_qc_contract({"checks": _qc_checks()})
    assert report["verdict"] == "pass"
    assert report["ocr_linux_available"] is False
    claimed = b3.check_qc_contract(
        {"checks": _qc_checks(**{"0": {"executed_here": True}})}
    )
    assert claimed["verdict"] == "fail"
    linux_claim = b3.check_qc_contract(
        {"checks": _qc_checks(**{"1": {"ocr_linux_available": True}})}
    )
    assert linux_claim["verdict"] == "fail"
    incomplete = b3.check_qc_contract({"checks": _qc_checks()[:2]})
    assert incomplete["verdict"] == "fail"
    assert incomplete["missing_kinds"]


def test_b4_tiers_and_generation_confusion():
    base = {"executed_here": False, "mode": "base", "enhanced_shots": []}
    assert b4.check_synthesis_contract(base)["verdict"] == "pass"
    enhanced = {
        "executed_here": False,
        "mode": "enhanced",
        "enhanced_shots": [
            {"shot_id": "s2", "reason": "code cannot do water well"}
        ],
    }
    report = b4.check_synthesis_contract(enhanced)
    assert report["verdict"] == "pass"
    assert report["synthesis_mode"] == "code_composition"
    too_many = {
        "executed_here": False,
        "mode": "enhanced",
        "enhanced_shots": [
            {"shot_id": f"s{i}", "reason": "r"} for i in range(4)
        ],
    }
    assert b4.check_synthesis_contract(too_many)["verdict"] == "fail"
    confused = dict(base)
    confused["frame_grid"] = "5+17k"
    report = b4.check_synthesis_contract(confused)
    assert report["verdict"] == "fail"
    assert any(
        i["code"] == "generation_tier_confusion" for i in report["issues"]
    )
    executed = dict(base)
    executed["executed_here"] = True
    assert b4.check_synthesis_contract(executed)["verdict"] == "fail"


def test_registration_all_ten():
    names = [
        "qa.source_sentence_ledger",
        "qa.premium_composition_gate",
        "qa.duration_complexity_advisor",
        "qa.quote_confirmation_gate",
        "qa.narration_alignment_gate",
        "qa.ai_disclosure_gate",
        "story.knowledge_film_templates",
        "video.style_catalog_schema",
        "qa.knowledge_qc_contract",
        "video.two_tier_synthesis_contract",
    ]
    for name in names:
        assert contains(name), name
    for module, fn in [
        (a1, "register_source_sentence_ledger_capabilities_once"),
        (a2, "register_premium_composition_gate_capabilities_once"),
        (a3, "register_duration_complexity_advisor_capabilities_once"),
        (a4, "register_quote_confirmation_gate_capabilities_once"),
        (a5, "register_narration_alignment_gate_capabilities_once"),
        (a6, "register_ai_disclosure_gate_capabilities_once"),
        (b1, "register_knowledge_film_templates_capabilities_once"),
        (b2, "register_style_catalog_schema_capabilities_once"),
        (b3, "register_knowledge_qc_contract_capabilities_once"),
        (b4, "register_two_tier_synthesis_contract_capabilities_once"),
    ]:
        assert getattr(module, fn)() == []
