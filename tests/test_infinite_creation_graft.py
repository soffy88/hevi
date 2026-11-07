"""Tests for the Infinite Creation graft (A1-A6 gates, B1-B4 fake contracts)."""

import pytest

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import contains

from hevi.capabilities import (
    storyboard_fidelity_gate as a1,
    shot_hard_constraints_gate as a2,
    scene_blocking_schema as a3,
    wardrobe_age_variant_gate as a4,
    resume_ledger_gate as a5,
    workflow_spec_self_check as a6,
    h3_storyboard_adapter as b1,
    mcp_bridge_contract as b2,
    code_film_style_contract as b3,
    candidate_selection_ledger as b4,
)


def _beats():
    return [
        {"start_s": 0.0, "end_s": 2.0, "text": "Mei opens the shop door.", "source": "original"},
        {"start_s": 2.0, "end_s": 5.0, "text": "A bell rings above the door.", "source": "added"},
    ]


def test_a1_pass_and_gap_and_pronoun_and_tbd():
    plan = {"beats": _beats(), "total_duration_s": 5.0}
    assert a1.check_storyboard_fidelity(plan)["verdict"] == "pass"
    gap = {"beats": _beats(), "total_duration_s": 6.0}
    assert a1.check_storyboard_fidelity(gap)["verdict"] == "fail"
    pronoun = {
        "beats": [
            {"start_s": 0.0, "end_s": 2.0, "text": "She opens the door.", "source": "original"},
        ],
        "total_duration_s": 2.0,
    }
    report = a1.check_storyboard_fidelity(pronoun)
    assert report["verdict"] == "fail"
    assert any(i["code"] == "pronoun_in_beat" for i in report["issues"])
    tbd = {
        "beats": [
            {"start_s": 0.0, "end_s": 2.0, "text": "Mei opens the door.", "source": "tbd"},
        ],
        "total_duration_s": 2.0,
    }
    assert a1.check_storyboard_fidelity(tbd)["verdict"] == "fail"
    tbd["strict_fidelity"] = False
    assert a1.check_storyboard_fidelity(tbd)["verdict"] == "not_checked"
    duplicate = {
        "beats": [
            {"start_s": 0.0, "end_s": 2.0, "text": "Mei opens the door.", "source": "original"},
            {"start_s": 2.0, "end_s": 4.0, "text": "Mei opens the door.", "source": "original"},
        ],
        "total_duration_s": 4.0,
    }
    assert a1.check_storyboard_fidelity(duplicate)["verdict"] == "fail"


def test_a2_limits_grid_and_dual_lora():
    good = {
        "duration_s": 5.0,
        "dialogue_text": "Short line here.",
        "speakers": ["Mei"],
        "reference_audio_segments": ["a1"],
        "reference_images": ["p1"],
        "fps": 24.0,
    }
    # 5s at 24fps = 120 frames: off-grid, must fail.
    assert a2.check_shot_constraints(good)["verdict"] == "fail"
    # On-grid frame count: 311 frames at 24fps is 12.9583s, within 2-15s.
    on_grid = dict(good, duration_s=311 / 24.0, fps=24.0)
    report = a2.check_shot_constraints(on_grid)
    assert report["verdict"] == "pass", report
    assert report["frame_count"] == 311
    long_dialogue = dict(on_grid, dialogue_text="x" * 200)
    assert a2.check_shot_constraints(long_dialogue)["verdict"] == "fail"
    three_speakers = dict(on_grid, speakers=["A", "B", "C"])
    assert a2.check_shot_constraints(three_speakers)["verdict"] == "fail"
    dual = dict(on_grid, loras=[{"name": "turbo"}, {"name": "mystic"}])
    report = a2.check_shot_constraints(dual)
    assert report["verdict"] == "fail"
    assert any(i["code"] == "dual_lora_series" for i in report["issues"])
    too_long = dict(on_grid, duration_s=16.0)
    assert a2.check_shot_constraints(too_long)["verdict"] == "fail"


def test_a3_blocking_axis_and_props():
    blocking = {
        "scene_id": "sc1",
        "spatial_anchor": "shop counter",
        "characters": [
            {"name": "Mei", "screen_position": "left", "facing": "right", "depth": "foreground"},
        ],
        "props": [{"name": "bell", "anchor": "above door"}],
        "axis_side": "left",
        "camera_side": "left",
    }
    assert a3.check_scene_blocking(blocking)["verdict"] == "pass"
    crossed = dict(blocking, camera_side="right")
    assert a3.check_scene_blocking(crossed)["verdict"] == "fail"
    undeclared = dict(blocking, transitions=[{"crosses_axis": True}])
    assert a3.check_scene_blocking(undeclared)["verdict"] == "fail"
    declared = dict(
        blocking, transitions=[{"crosses_axis": True, "explicit_transition": True}]
    )
    assert a3.check_scene_blocking(declared)["verdict"] == "pass"
    no_anchor = dict(blocking, props=[{"name": "bell"}])
    assert a3.check_scene_blocking(no_anchor)["verdict"] == "fail"


def test_a4_variants_parent_event_and_usage():
    record = {
        "characters": ["mei"],
        "events": ["e1", "e2"],
        "variants": [
            {"id": "mei-coat", "parent_id": "mei", "kind": "wardrobe", "first_use_event": "e2"},
        ],
        "usages": [
            {"variant_id": "mei-coat", "event": "e2", "scene_characters_present": ["mei"]},
        ],
    }
    assert a4.check_wardrobe_age_variants(record)["verdict"] == "pass"
    early = dict(
        record,
        usages=[{"variant_id": "mei-coat", "event": "e1", "scene_characters_present": ["mei"]}],
    )
    report = a4.check_wardrobe_age_variants(early)
    assert report["verdict"] == "fail"
    assert any(i["code"] == "variant_used_before_introduction" for i in report["issues"])
    orphan = dict(
        record,
        variants=[
            {"id": "mei-coat", "parent_id": "ghost", "kind": "wardrobe", "first_use_event": "e2"},
        ],
    )
    assert a4.check_wardrobe_age_variants(orphan)["verdict"] == "fail"
    absent_parent = dict(
        record,
        usages=[{"variant_id": "mei-coat", "event": "e2", "scene_characters_present": ["other"]}],
    )
    assert a4.check_wardrobe_age_variants(absent_parent)["verdict"] == "fail"


def test_a5_resume_done_force_and_selection():
    ledger = {
        "segments": [
            {
                "id": "s1",
                "status": "done",
                "artifact_sha": "abc",
                "completed_at": "2026-11-03",
                "candidates": [{"id": "c1", "selected": True}],
            },
            {"id": "s2", "status": "pending", "candidates": []},
        ],
        "plan": {"generate": ["s2"]},
    }
    assert a5.check_resume_ledger(ledger)["verdict"] == "pass"
    regenerate = dict(ledger, plan={"generate": ["s1", "s2"]})
    assert a5.check_resume_ledger(regenerate)["verdict"] == "fail"
    forced = dict(
        ledger,
        plan={"generate": ["s1"], "force": [{"segment_id": "s1", "reason": "artifact corrupt"}]},
    )
    assert a5.check_resume_ledger(forced)["verdict"] == "pass"
    force_no_reason = dict(
        ledger, plan={"generate": ["s1"], "force": [{"segment_id": "s1"}]}
    )
    assert a5.check_resume_ledger(force_no_reason)["verdict"] == "fail"
    two_selected = dict(
        ledger,
        segments=[
            {
                "id": "s1",
                "status": "done",
                "artifact_sha": "abc",
                "completed_at": "2026-11-03",
                "candidates": [{"id": "c1", "selected": True}, {"id": "c2", "selected": True}],
            }
        ],
        plan={"generate": []},
    )
    assert a5.check_resume_ledger(two_selected)["verdict"] == "fail"


def test_a6_spec_roles_and_unknown_class():
    spec = {
        "nodes": [
            {"id": "1", "class": "CLIPTextEncode"},
            {"id": "2", "class": "KSampler"},
            {"id": "3", "class": "SaveImage"},
        ],
        "roles": {"text_prompt": "1", "sampler": "2", "output": "3"},
    }
    assert a6.check_workflow_spec(spec)["verdict"] == "pass"
    assert a6.guess_node_role({"class": "CLIPTextEncode"}) == "text_prompt"
    dangling = dict(spec, roles={"text_prompt": "99"})
    assert a6.check_workflow_spec(dangling)["verdict"] == "fail"
    unroled = dict(spec, roles={"text_prompt": "1", "sampler": "2"})
    assert a6.check_workflow_spec(unroled)["verdict"] == "fail"
    unknown = {
        "nodes": [{"id": "1", "class": "SomethingEntirelyNew"}],
        "roles": {},
    }
    assert a6.check_workflow_spec(unknown)["verdict"] == "not_checked"
    duplicate = {
        "nodes": [
            {"id": "1", "class": "KSampler"},
            {"id": "1", "class": "KSampler"},
        ],
        "roles": {"sampler": "1"},
    }
    assert a6.check_workflow_spec(duplicate)["verdict"] == "fail"


def test_b1_adapter_grid_and_continuation():
    # 5.1667s at 24fps = 124 frames: on the 5+17k grid (5+17*7=124).
    board = {
        "fps": 24.0,
        "segments": [
            {"id": "s1", "duration_s": 124 / 24.0, "prompt": "Mei opens the door."},
            {
                "id": "s2",
                "duration_s": 124 / 24.0,
                "prompt": "The bell rings.",
                "references": {"images": ["p1"]},
            },
        ],
    }
    plan = b1.compile_storyboard(board)
    assert plan["segment_count"] == 2
    assert plan["segments"][0]["continuation"] is None
    assert plan["segments"][1]["continuation"]["source_segment_id"] == "s1"
    assert plan["segments"][1]["frame_count"] == 124
    assert plan["executed_here"] is False
    off_grid = {"fps": 24.0, "segments": [{"id": "s1", "duration_s": 5.0, "prompt": "x"}]}
    with pytest.raises(CapabilityError):
        b1.compile_storyboard(off_grid)
    dual = {
        "fps": 24.0,
        "segments": [
            {
                "id": "s1",
                "duration_s": 124 / 24.0,
                "prompt": "x",
                "loras": [{"name": "a"}, {"name": "b"}],
            }
        ],
    }
    with pytest.raises(CapabilityError):
        b1.compile_storyboard(dual)


def test_b2_mcp_frames_and_transcript():
    init = b2.handle_mcp_frame(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    )
    assert init["result"]["protocolVersion"] == "2024-11-05"
    listing = b2.handle_mcp_frame(
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
    )
    names = {tool["name"] for tool in listing["result"]["tools"]}
    assert "set_storyboard" in names
    call = b2.handle_mcp_frame(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "get_project", "arguments": {"project_id": "p1"}},
        }
    )
    assert "executed_here" in call["result"]["content"][0]["text"]
    unknown = b2.handle_mcp_frame(
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "nope"}}
    )
    assert unknown["error"]["code"] == -32602
    bad_method = b2.handle_mcp_frame({"jsonrpc": "2.0", "id": 5, "method": "explode"})
    assert bad_method["error"]["code"] == -32601
    transcript = [
        {
            "request": {"jsonrpc": "2.0", "id": 1, "method": "initialize"},
            "response": {"jsonrpc": "2.0", "id": 1, "result": {}},
        },
        {
            "request": {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            "response": {"jsonrpc": "2.0", "id": 2, "result": {}},
        },
    ]
    assert b2.check_mcp_transcript(transcript)["verdict"] == "pass"
    wrong_order = list(reversed(transcript))
    assert b2.check_mcp_transcript(wrong_order)["verdict"] == "fail"


def _index():
    return {
        "styles": [
            {
                "id": "news-package",
                "category": "editing_documentary",
                "folder": "news-package",
                "render_contract": {"browser_render": True, "webgl_required": True},
            },
            {
                "id": "watercolor",
                "category": "hand_drawn",
                "folder": "watercolor",
                "render_contract": {"browser_render": True, "webgl_required": False},
            },
        ]
    }


def test_b3_style_index_and_frame_record():
    assert b3.validate_style_index(_index())["verdict"] == "pass"
    assert b3.validate_style_index(_index())["style_count"] == 2
    bad_category = {
        "styles": [
            {
                "id": "x",
                "category": "nope",
                "folder": "x",
                "render_contract": {"browser_render": True, "webgl_required": False},
            }
        ]
    }
    assert b3.validate_style_index(bad_category)["verdict"] == "fail"
    record = {
        "style_id": "news-package",
        "width": 1920,
        "height": 1080,
        "frame_count": 90,
        "fps": 30,
        "rendered_here": False,
        "webgl_used": True,
    }
    assert b3.check_style_frame_record(_index(), record)["verdict"] == "pass"
    claimed = dict(record, rendered_here=True)
    assert b3.check_style_frame_record(_index(), claimed)["verdict"] == "fail"
    no_webgl = dict(record, webgl_used=False)
    assert b3.check_style_frame_record(_index(), no_webgl)["verdict"] == "fail"


def test_b4_candidate_ledger_selection_and_reselection():
    ledger = {
        "segments": [
            {
                "id": "s1",
                "candidates": [
                    {"id": "c1", "sha256": "aa"},
                    {"id": "c2", "sha256": "bb"},
                ],
                "selected_id": "c1",
                "selection_reason": "cleanest motion",
                "retained_ids": ["c2"],
            }
        ]
    }
    assert b4.check_candidate_ledger(ledger)["verdict"] == "pass"
    dropped = {
        "segments": [
            {
                "id": "s1",
                "candidates": [
                    {"id": "c1", "sha256": "aa"},
                    {"id": "c2", "sha256": "bb"},
                ],
                "selected_id": "c1",
                "selection_reason": "cleanest motion",
                "retained_ids": [],
            }
        ]
    }
    report = b4.check_candidate_ledger(dropped)
    assert report["verdict"] == "fail"
    assert any(i["code"] == "unselected_candidate_dropped" for i in report["issues"])
    reselection = {
        "segments": [
            {
                "id": "s1",
                "candidates": [
                    {"id": "c1", "sha256": "aa"},
                    {"id": "c2", "sha256": "bb"},
                ],
                "selected_id": "c2",
                "selection_reason": "better face",
                "supersedes": "c1",
                "previous_reason": "cleanest motion",
                "retained_ids": ["c1"],
            }
        ]
    }
    assert b4.check_candidate_ledger(reselection)["verdict"] == "pass"
    same_reason = dict(
        reselection,
        segments=[
            dict(
                reselection["segments"][0],
                selection_reason="cleanest motion",
            )
        ],
    )
    assert b4.check_candidate_ledger(same_reason)["verdict"] == "fail"
    unknown_selection = dict(
        ledger,
        segments=[dict(ledger["segments"][0], selected_id="c9")],
    )
    assert b4.check_candidate_ledger(unknown_selection)["verdict"] == "fail"


def test_registry_contains_all_ten():
    for name in (
        "qa.storyboard_fidelity_gate",
        "qa.shot_hard_constraints_gate",
        "qa.scene_blocking_schema",
        "qa.wardrobe_age_variant_gate",
        "qa.resume_ledger_gate",
        "qa.workflow_spec_self_check",
        "video.h3_storyboard_adapter",
        "qa.mcp_bridge_contract",
        "video.code_film_style_contract",
        "qa.candidate_selection_ledger",
    ):
        assert contains(name), name
