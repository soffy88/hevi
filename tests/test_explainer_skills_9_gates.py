"""Tests for the explainer-skills-9 graft (A1-A6 gates, B1-B5 compilers).

Clean-room: only the disciplines restated in the graft modules are
judged here -- the anatomy mapping/audit, voice-first timing,
whiteboard isolation, script-first pacing, deterministic reset,
markdown pagination, GSAP vocabulary, whiteboard mask contract,
knowledge layouts, Manim scene planning, and structured prompt
compilation. No template text is copied, no scaffold or kit code is
used, no image API is called, no key or GPU is needed, and the
HyperFrames engine is never claimed to be connected.
"""

import pytest

from hevi.capabilities.anatomy_audit_vocabulary import check_anatomy_audit
from hevi.capabilities.deterministic_reset_gate import check_deterministic_reset
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.gsap_choreography_vocabulary import (
    compile_choreography,
    get_move,
    list_moves,
    render_fake as gsap_render_fake,
)
from hevi.capabilities.knowledge_layout_pack import (
    build_layout,
    get_layout,
    list_layouts,
    render_layout_fake,
)
from hevi.capabilities.manim_scene_plan_gate import check_manim_scene_plan
from hevi.capabilities.markdown_pagination_gate import check_markdown_pagination
from hevi.capabilities.registry import get as registry_get
from hevi.capabilities.script_first_pacing_gate import check_script_first_pacing
from hevi.capabilities.structured_prompt_compiler import compile_structured_prompt
from hevi.capabilities.vo_first_timing_gate import check_vo_first_timing
from hevi.capabilities.whiteboard_element_isolation_gate import (
    check_whiteboard_elements,
)
from hevi.capabilities.whiteboard_mask_contract import (
    check_reveal_contract,
    reveal_fake,
)


def _anatomy_plan(**overrides):
    plan = {
        "mapping": [
            {"part": "piston", "geometry": "cylinder", "label": "Piston"},
            {"part": "valve", "geometry": "disc", "label": "Valve"},
        ],
        "audit": {
            "no_penetration": {"evidence": "frame sweep shows clearances"},
            "seated_ends": {"evidence": "both ends land on mounts"},
            "depth_order": {"evidence": "overlap ordered by depth"},
        },
    }
    plan.update(overrides)
    return plan


def test_a1_anatomy_pass():
    report = check_anatomy_audit(_anatomy_plan())
    assert report["verdict"] == "pass"
    assert report["ok"] is True


def test_a1_anatomy_missing_audit_check_fails():
    plan = _anatomy_plan()
    del plan["audit"]["depth_order"]
    report = check_anatomy_audit(plan)
    assert report["verdict"] == "fail"
    assert any(i["code"] == "audit_check_missing" for i in report["issues"])


def test_a1_anatomy_duplicate_part_fails():
    plan = _anatomy_plan()
    plan["mapping"].append(
        {"part": "piston", "geometry": "rod", "label": "Piston rod"}
    )
    report = check_anatomy_audit(plan)
    assert report["verdict"] == "fail"
    assert any(i["code"] == "mapping_part_duplicate" for i in report["issues"])


def _vo_plan(**overrides):
    plan = {
        "narration": {"measured_duration_s": 6.0, "evidence_id": "asr-ev-1"},
        "beats": [
            {"id": "b1", "start_s": 0.0, "end_s": 2.5, "derived_from": "narration"},
            {"id": "b2", "start_s": 2.5, "end_s": 6.0, "derived_from": "narration"},
        ],
    }
    plan.update(overrides)
    return plan


def test_a2_vo_first_pass():
    assert check_vo_first_timing(_vo_plan())["verdict"] == "pass"


def test_a2_vo_first_estimated_fails():
    plan = _vo_plan()
    plan["narration"]["estimated_duration_s"] = 6.0
    report = check_vo_first_timing(plan)
    assert report["verdict"] == "fail"
    assert any(i["code"] == "estimated_timing" for i in report["issues"])


def test_a2_vo_first_gap_fails():
    plan = _vo_plan()
    plan["beats"][1]["start_s"] = 3.0
    report = check_vo_first_timing(plan)
    assert report["verdict"] == "fail"
    assert any(i["code"] == "beat_gap_or_overlap" for i in report["issues"])


def _whiteboard_plan(**overrides):
    plan = {
        "elements": [
            {"id": "e1", "asset_id": "a1"},
            {"id": "e2", "asset_id": "a2"},
        ],
        "mask": {"pen_width": 12, "row_spacing": 10, "snake_inset": 6},
    }
    plan.update(overrides)
    return plan


def test_a3_whiteboard_pass():
    assert check_whiteboard_elements(_whiteboard_plan())["verdict"] == "pass"


def test_a3_whiteboard_shared_undeclared_fails():
    plan = _whiteboard_plan()
    plan["elements"][1]["asset_id"] = "a1"
    report = check_whiteboard_elements(plan)
    assert report["verdict"] == "fail"
    assert any(i["code"] == "shared_asset_undeclared" for i in report["issues"])


def test_a3_whiteboard_spacing_fails():
    plan = _whiteboard_plan()
    plan["mask"]["row_spacing"] = 14
    report = check_whiteboard_elements(plan)
    assert report["verdict"] == "fail"
    assert any(i["code"] == "row_spacing_exceeds_pen_width" for i in report["issues"])


def _pacing_plan(**overrides):
    plan = {
        "script": {
            "text": "The resolver asks the root, then the TLD, then the authority.",
            "word_count": 23,
            "words_per_second": 2.3,
        },
        "analogies": ["postal sorting office"],
        "beats": [
            {"id": "b1", "start_s": 0.0, "end_s": 5.0, "sentence": "The resolver asks."},
            {"id": "b2", "start_s": 5.0, "end_s": 10.0, "sentence": "Then the authority."},
        ],
    }
    plan.update(overrides)
    return plan


def test_a4_script_first_pass():
    assert check_script_first_pacing(_pacing_plan())["verdict"] == "pass"


def test_a4_script_first_missing_rate_fails():
    plan = _pacing_plan()
    del plan["script"]["words_per_second"]
    report = check_script_first_pacing(plan)
    assert report["verdict"] == "fail"
    assert any(i["code"] == "speaking_rate_missing" for i in report["issues"])


def test_a4_script_first_analogy_switch_fails():
    plan = _pacing_plan()
    plan["analogies"] = ["postal sorting office", "library catalogue"]
    report = check_script_first_pacing(plan)
    assert report["verdict"] == "fail"
    assert any(i["code"] == "analogy_switched" for i in report["issues"])


def _reset_plan(**overrides):
    plan = {
        "scenes": [
            {
                "id": "s1",
                "has_loops": True,
                "reset": {
                    "restored_properties": ["x", "y", "scale"],
                    "covers_loops": True,
                },
                "overlaps": [
                    {"a": "t1", "b": "t2", "exemption_reason": "intentional stack"},
                ],
            }
        ],
        "overlap_audit": {"sweep_resolution_s": 0.5},
    }
    plan.update(overrides)
    return plan


def test_a5_reset_pass():
    assert check_deterministic_reset(_reset_plan())["verdict"] == "pass"


def test_a5_reset_missing_fails():
    plan = _reset_plan()
    del plan["scenes"][0]["reset"]
    report = check_deterministic_reset(plan)
    assert report["verdict"] == "fail"
    assert any(i["code"] == "reset_missing" for i in report["issues"])


def test_a5_overlap_without_exemption_fails():
    plan = _reset_plan()
    del plan["scenes"][0]["overlaps"][0]["exemption_reason"]
    report = check_deterministic_reset(plan)
    assert report["verdict"] == "fail"
    assert any(i["code"] == "overlap_without_exemption" for i in report["issues"])


def _pagination_doc(**overrides):
    doc = {
        "pages": [
            {
                "layout": "Title",
                "params": {"title": "DNS"},
                "duration_s": 4.0,
            },
            {
                "layout": "CustomOrbit",
                "params": {"items": 3},
                "duration_s": 6.0,
                "custom": True,
                "component": "CustomOrbit",
            },
        ]
    }
    doc.update(overrides)
    return doc


def test_a6_pagination_pass():
    report = check_markdown_pagination(_pagination_doc())
    assert report["verdict"] == "pass"
    assert report["total_duration_s"] == 10.0


def test_a6_pagination_custom_mismatch_fails():
    doc = _pagination_doc()
    doc["pages"][1]["component"] = "OtherName"
    report = check_markdown_pagination(doc)
    assert report["verdict"] == "fail"
    assert any(i["code"] == "custom_component_mismatch" for i in report["issues"])


def test_a6_pagination_missing_duration_fails():
    doc = _pagination_doc()
    del doc["pages"][0]["duration_s"]
    report = check_markdown_pagination(doc)
    assert report["verdict"] == "fail"
    assert any(i["code"] == "page_duration_missing" for i in report["issues"])


def test_b1_gsap_vocabulary_and_fake():
    assert list_moves() == [
        "weighted_drop",
        "morph_fuse",
        "forced_collision",
        "quantity_as_character",
    ]
    assert get_move("morph_fuse")["beats"] == ["source", "blend", "target"]
    with pytest.raises(CapabilityError):
        get_move("spin_around")
    plan = {
        "motion_library": {"supply": "vendored"},
        "moves": [
            {
                "name": "weighted_drop",
                "params": {
                    "drop_height": 200,
                    "squash_amount": 0.3,
                    "settle_duration_s": 0.4,
                },
            }
        ],
    }
    compiled = compile_choreography(plan)
    assert compiled["move_count"] == 1
    first = gsap_render_fake(plan, frames=3)
    second = gsap_render_fake(plan, frames=3)
    assert first == second
    assert len({f["sha256"] for f in first["frames"]}) == 3
    assert all(f["backend"] == "fake" for f in first["frames"])


def test_b1_gsap_missing_vendor_raises():
    plan = {"moves": [{"name": "morph_fuse", "params": {}}]}
    with pytest.raises(CapabilityError):
        compile_choreography(plan)


def test_b1_gsap_network_source_raises():
    plan = {
        "motion_library": {
            "supply": "vendored",
            "source_url": "https://cdn.example.invalid/gsap.js",
        },
        "moves": [
            {
                "name": "morph_fuse",
                "params": {
                    "source_shape": "circle",
                    "target_shape": "square",
                    "blend_duration_s": 1.0,
                },
            }
        ],
    }
    with pytest.raises(CapabilityError):
        compile_choreography(plan)


def _reveal_plan(**overrides):
    plan = {
        "elements": [
            {
                "id": "e1",
                "area": 100.0,
                "reveal_start_s": 0.0,
                "reveal_end_s": 2.0,
                "hand": "visible_during_stroke_only",
            },
            {
                "id": "e2",
                "area": 50.0,
                "reveal_start_s": 2.0,
                "reveal_end_s": 3.5,
                "hand": "visible_during_stroke_only",
            },
        ],
        "word_times": [
            {"word": "the", "t_s": 0.1},
            {"word": "resolver", "t_s": 0.6},
        ],
        "camera_moves": [{"at_s": 4.0, "during_reveal": False}],
    }
    plan.update(overrides)
    return plan


def test_b2_whiteboard_contract_fake():
    report = check_reveal_contract(_reveal_plan())
    assert report["verdict"] == "pass"
    assert report["hyperframes_connected"] is False
    assert report["hyperframes_not_connected"] is True
    record = reveal_fake(_reveal_plan())
    assert record["backend"] == "fake"
    assert record["coverage"] == 1.0
    assert record["total_area"] == 150.0
    assert record["hyperframes_connected"] is False


def test_b2_whiteboard_camera_during_reveal_fails():
    plan = _reveal_plan()
    plan["camera_moves"] = [{"at_s": 1.0, "during_reveal": True}]
    report = check_reveal_contract(plan)
    assert report["verdict"] == "fail"
    assert any(i["code"] == "camera_during_reveal" for i in report["issues"])
    with pytest.raises(CapabilityError):
        reveal_fake(plan)


def test_b3_knowledge_layouts_fake_frames():
    assert list_layouts() == [
        "title",
        "content_card",
        "two_column",
        "triangle",
        "before_after",
        "outro",
    ]
    hashes = set()
    for name in list_layouts():
        spec = get_layout(name)
        content = {zone["name"]: f"content for {zone['name']}" for zone in spec["zones"]}
        built = build_layout(name, content)
        record = render_layout_fake(built)
        assert record["backend"] == "fake"
        assert len(record["frames"]) == 1
        hashes.add(record["frames"][0]["sha256"])
    assert len(hashes) == 6
    again = render_layout_fake(
        build_layout(
            "title",
            {"headline": "content for headline", "subtitle": "content for subtitle"},
        )
    )
    assert again["frames"][0]["sha256"] in hashes


def test_b3_knowledge_custom_out_of_page_raises():
    with pytest.raises(CapabilityError):
        build_layout(
            {
                "custom_name": "CustomWide",
                "zones": [{"name": "big", "x": 0, "y": 0, "w": 2000, "h": 100}],
            },
            {"big": "x"},
        )


def _manim_plan(**overrides):
    plan = {
        "engine": "manimce",
        "aha_moment": "The derivative is a local slope.",
        "misconception": "A derivative is a formula to memorise.",
        "audience": "First-year calculus students.",
        "latex_required": True,
        "scenes": [
            {
                "id": "s1",
                "goal": "Show slope at a point.",
                "duration_s": 8.0,
                "dwell_reason": "Learners need time to read the secant line.",
                "imports": ["from manim import *"],
            }
        ],
    }
    plan.update(overrides)
    return plan


def test_b4_manim_plan_pass():
    assert check_manim_scene_plan(_manim_plan())["verdict"] == "pass"


def test_b4_manim_plan_missing_engine_fails():
    plan = _manim_plan()
    del plan["engine"]
    report = check_manim_scene_plan(plan)
    assert report["verdict"] == "fail"
    assert any(i["code"] == "engine_missing" for i in report["issues"])


def test_b4_manim_plan_import_mismatch_fails():
    plan = _manim_plan()
    plan["scenes"][0]["imports"] = ["from manimlib import *"]
    report = check_manim_scene_plan(plan)
    assert report["verdict"] == "fail"
    assert any(i["code"] == "engine_import_mismatch" for i in report["issues"])


def _brief(**overrides):
    brief = {
        "concept": "how DNS resolution works",
        "relations": "client asks resolver, resolver asks root, TLD, authoritative servers",
        "visual_metaphor": "a postal sorting office routing letters",
        "layout_strategy": "left to right pipeline with four stations",
        "draw_level": "normal",
    }
    brief.update(overrides)
    return brief


def test_b5_structured_prompt_in_range_and_must_verify():
    record = compile_structured_prompt(_brief())
    assert 400 <= record["word_count"] <= 800
    assert record["within_range"] is True
    assert record["model"]["model_string"] is None
    assert record["model"]["must_verify"] is True
    assert record["model"]["verified"] is False


def test_b5_structured_prompt_caller_model_recorded_unverified():
    record = compile_structured_prompt(
        _brief(model_string="some-vendor-model-string")
    )
    assert record["model"]["model_string"] == "some-vendor-model-string"
    assert record["model"]["verified"] is False
    assert record["model"]["must_verify"] is True
    assert record["model"]["source"] == "caller_supplied"


def test_b5_structured_prompt_missing_analysis_raises():
    with pytest.raises(CapabilityError):
        compile_structured_prompt({"concept": "DNS"})


def test_registry_resolves_all_new_capabilities():
    names = [
        "qa.anatomy_audit_vocabulary",
        "qa.vo_first_timing_gate",
        "qa.whiteboard_element_isolation_gate",
        "qa.script_first_pacing_gate",
        "qa.deterministic_reset_gate",
        "qa.markdown_pagination_gate",
        "video.gsap_choreography_vocabulary",
        "video.whiteboard_mask_contract",
        "video.knowledge_layout_pack",
        "qa.manim_scene_plan_gate",
        "image.structured_prompt_compiler",
    ]
    for name in names:
        assert registry_get(name) is not None, name
