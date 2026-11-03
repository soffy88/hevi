"""Offline tests for the clean-room method intake (shuohao-skills methods).

Fixtures are invented for these tests only: a fictional tea house,
invented characters, invented timings and invented file hashes. No
upstream code, text, sample, demo media or prompt is reused. No
network, no paid calls, no rendering, no model call, no image
generation.
"""

from __future__ import annotations

import pytest

import hevi.capabilities as caps
from hevi.capabilities.character_anchor import (
    add_view,
    check_anchor_sheet,
    confirm_anchor,
    description_fingerprint,
    new_sheet,
    set_anchor,
)
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.production_gates import run_production_gates
from hevi.capabilities.stage_opening import (
    build_opening_blocking,
    check_storyboard_opening,
)

NAMES = [
    "story.opening_blocking",
    "qa.storyboard_opening_gate",
    "qa.production_gates",
    "qa.character_anchor_gate",
]


def _staging() -> dict:
    return {
        "locations": [{
            "id": "teahouse", "name": "茶馆",
            "items": [
                {"id": "long_table", "name": "长桌", "can_sit": True},
                {"id": "bench", "name": "条凳", "can_sit": True},
                {"id": "counter", "name": "柜台", "can_sit": False},
            ],
        }],
        "scenes": [{
            "id": "S01", "location_id": "teahouse",
            "cast": [{"id": "C01", "name": "店主"}, {"id": "C02", "name": "客人"}],
            "script_cast": ["C01", "C02"],
            "places": [
                {"character_id": "C01", "present": True, "item_id": "counter",
                 "side": "west", "along": 0.5, "posture": "stand", "facing": "east"},
                {"character_id": "C02", "present": True, "item_id": "long_table",
                 "side": "north", "along": 0.3, "posture": "sit", "facing": "south"},
            ],
            "extras": 0, "extras_where": None,
        }],
    }


def _bundle() -> dict:
    return {
        "outline": {
            "main_line": "店主找回失落的茶谱",
            "sub_lines": ["客人学会品茶"],
            "cut_lines": [{"what": "京城支线", "why": "与主线无关"}],
            "cast": [
                {"id": "C01", "name": "店主", "tier": "lead"},
                {"id": "C02", "name": "客人", "tier": "support"},
            ],
            "scenes": [{"id": "S01"}, {"id": "S02", "reuse_of": "S01"}],
            "beats": [
                {"id": "B1", "episode": 1, "major": True},
                {"id": "B2", "episode": 2, "major": True},
            ],
            "props": [{"id": "P1", "function": "托起找回茶谱的爆点", "beat_ids": ["B1"]}],
            "total_episodes": 4,
        },
        "art": {
            "locations": [{
                "id": "teahouse", "anchor_text": "木质茶馆内景",
                "variants": ["白天"], "scale_reference": "长桌约两米",
            }],
            "props": [{"id": "P1", "name": "茶谱", "anchor_text": "旧线装茶谱"}],
        },
        "script": {
            "target_sec": 8,
            "scenes": [{
                "id": "S01", "location_id": "teahouse",
                "cast": [{"id": "C01", "name": "店主"}, {"id": "C02", "name": "客人"}],
                "beats": [
                    {"kind": "action", "text": "店主推门走进茶馆"},
                    {"kind": "dialogue", "text": "请坐，茶马上就好，先喝一口热茶暖暖身子再慢慢说。",
                     "claims": ["B1"]},
                    {"kind": "cliff", "text": "门外传来一声陌生的敲门声", "is_cliff": True},
                ],
            }],
        },
        "storyboard": {
            "segments": [{
                "scene_id": "S01", "location_id": "teahouse",
                "cuts": [
                    {"id": "c1", "duration_sec": 3.0, "lens": "35mm",
                     "camera_position": "中景", "composition": "居中",
                     "eyeline": "店主", "focus": "店主", "stability": "固定",
                     "video_prompt": "一名穿长衫的人推门走进茶馆"},
                    {"id": "c2", "duration_sec": 3.0, "lens": "50mm",
                     "camera_position": "近景", "composition": "三分法",
                     "eyeline": "客人", "focus": "客人", "stability": "固定",
                     "video_prompt": "一名来客坐下接过茶杯"},
                ],
                "keyframes": [{"time_sec": 0.0}, {"time_sec": 3.0}],
            }],
        },
    }


def _sheet():
    sheet = new_sheet("C01", "店主")
    set_anchor(sheet, file="anchor.png", sha256="a" * 64,
               look_snapshot="青布长衫", description_fingerprint=description_fingerprint("青布长衫店主"))
    confirm_anchor(sheet)
    return sheet


# Registry ----------------------------------------------------------------

def test_capabilities_registered():
    from hevi.capabilities.registry import names
    registered = set(names())
    for name in NAMES:
        assert name in registered


# Opening blocking ----------------------------------------------------------

def test_opening_blocking_pass_and_sentence():
    result = build_opening_blocking(_staging())
    assert result["verdict"] == "pass"
    assert result["issues"] == []
    sentence = result["scenes"][0]["blocking"]
    assert "店主站在柜台西侧，面朝东" in sentence
    assert "客人坐在长桌北侧，面朝南" in sentence
    assert sentence.endswith("没有其他人。")


def test_opening_blocking_absent_character():
    staging = _staging()
    staging["scenes"][0]["places"][1].update(
        {"present": False, "item_id": None, "side": None, "along": None,
         "posture": None, "facing": None})
    result = build_opening_blocking(staging)
    assert result["verdict"] == "pass"
    assert "客人开场不在场" in result["scenes"][0]["blocking"]


@pytest.mark.parametrize("mutate,code", [
    (lambda s: s["locations"][0].update({"items": []}), "LOC_ITEMS"),
    (lambda s: s["scenes"][0].update({"location_id": "nowhere"}), "LOC_KNOWN"),
    (lambda s: s["scenes"][0]["places"].pop(), "CAST_EXACT"),
    (lambda s: [p.update({"present": False, "item_id": None, "side": None,
                          "along": None, "posture": None, "facing": None})
                for p in s["scenes"][0]["places"]], "PRESENT"),
    (lambda s: s["scenes"][0]["places"][0].update({"item_id": "nope"}), "ANCHOR"),
    (lambda s: s["scenes"][0]["places"][0].update({"facing": "up"}), "PLACEMENT"),
    (lambda s: s["scenes"][0]["places"][1].update({"item_id": "counter",
                                                  "side": "west", "along": 0.9,
                                                  "posture": "sit"}), "PLACEMENT"),
    (lambda s: s["scenes"][0]["places"][1].update({"item_id": "counter",
                                                  "side": "west", "along": 0.55,
                                                  "posture": "stand"}), "OVERLAP"),
    (lambda s: s["scenes"][0].update({"extras": 2, "extras_where": None}), "EXTRAS"),
])
def test_opening_blocking_gates(mutate, code):
    staging = _staging()
    mutate(staging)
    result = build_opening_blocking(staging)
    assert result["verdict"] == "fail"
    assert any(i["code"] == code for i in result["issues"])
    assert result["scenes"][0]["blocking"] is None


def test_opening_blocking_bad_document_raises():
    with pytest.raises(CapabilityError):
        build_opening_blocking({"locations": "nope", "scenes": []})
    with pytest.raises(CapabilityError):
        build_opening_blocking("nope")


def test_storyboard_opening_gate_pass_and_mismatch():
    staging = _staging()
    blocking = build_opening_blocking(staging)["scenes"][0]["blocking"]
    board = {"scenes": [{"id": "S01", "segments": [{"opening_blocking": blocking}]}]}
    assert check_storyboard_opening(staging, board)["verdict"] == "pass"
    board_bad = {"scenes": [{"id": "S01", "segments": [{"opening_blocking": "店主站在别处。"}]}]}
    bad = check_storyboard_opening(staging, board_bad)
    assert bad["verdict"] == "fail"
    assert bad["issues"][0]["code"] == "BLOCKING_MISMATCH"
    missing = check_storyboard_opening(staging, {"scenes": []})
    assert missing["issues"][0]["code"] == "SCENE_MISSING"


# Production gates ----------------------------------------------------------

def test_production_gates_all_pass():
    result = run_production_gates(_bundle())
    assert result["verdict"] == "pass", result
    assert result["gate_count"] == 5 + 3 + 5 + 4
    assert result["failed_gates"] == []


def test_production_gates_skipped_section_is_not_a_pass():
    result = run_production_gates({"outline": _bundle()["outline"]})
    assert result["sections"]["art"]["status"] == "skipped"
    assert result["sections"]["script"]["status"] == "skipped"
    assert result["verdict"] == "pass"


@pytest.mark.parametrize("mutate,code", [
    (lambda b: b["outline"].update({"sub_lines": ["a", "b"]}), "outline.OUT_MAIN_LINE"),
    (lambda b: b["outline"]["cast"].extend(
        [{"id": f"X{i}", "name": f"路人{i}", "tier": "lead"} for i in range(6)]),
     "outline.OUT_CAST_TIERS"),
    (lambda b: b["outline"]["props"][0].update({"function": ""}), "outline.OUT_PROP_FUNCTION"),
    (lambda b: b["outline"].update({"beats": [
        {"id": "B1", "episode": 4, "major": True}]}), "outline.OUT_BEAT_SPACING"),
    (lambda b: b["art"]["locations"][0].update({"anchor_text": ""}), "art.ART_LOCATION_COVER"),
    (lambda b: b["script"]["scenes"][0]["beats"][1].update(
        {"text": "这句话故意写得" + "很长" * 20}),
     "script.SCR_LINE_LENGTH"),
    (lambda b: b["script"]["scenes"][0].update({"beats": [
        {"kind": "dialogue", "text": "你好。"}]}), "script.SCR_SCENE_ACTION"),
    (lambda b: b["storyboard"]["segments"][0]["cuts"][0].update({"duration_sec": 9.0}),
     "storyboard.SB_CUT_RANGE"),
    (lambda b: b["storyboard"]["segments"][0].update({"keyframes": [{"time_sec": 0.0}]}),
     "storyboard.SB_KEYFRAME_TIMING"),
    (lambda b: b["storyboard"]["segments"][0]["cuts"][0].update(
        {"video_prompt": "店主推门走进茶馆"}), "storyboard.SB_COMPOSITION_AND_IDENTITY"),
])
def test_production_gates_failures(mutate, code):
    bundle = _bundle()
    mutate(bundle)
    result = run_production_gates(bundle)
    assert result["verdict"] == "fail"
    assert code in result["failed_gates"]


def test_production_gates_bad_bundle_raises():
    with pytest.raises(CapabilityError):
        run_production_gates("nope")
    with pytest.raises(CapabilityError):
        run_production_gates({"outline": "nope"})


# Character anchor ----------------------------------------------------------

def test_anchor_happy_path_and_coverage():
    sheet = _sheet()
    add_view(sheet, view="headshot", file="head.png", sha256="b" * 64)
    add_view(sheet, view="profile", file="side.png", sha256="c" * 64)
    result = check_anchor_sheet(sheet, expected_views=["headshot", "profile"])
    assert result["verdict"] == "pass"
    assert result["current_views"] == ["headshot", "profile"]


def test_anchor_requires_confirmation():
    sheet = new_sheet("C01", "店主")
    set_anchor(sheet, file="anchor.png", sha256="a" * 64,
               look_snapshot="青布长衫", description_fingerprint="fp1")
    with pytest.raises(CapabilityError):
        add_view(sheet, view="headshot", file="head.png", sha256="b" * 64)
    assert check_anchor_sheet(sheet)["verdict"] == "fail"


def test_anchor_chain_reference_rejected():
    sheet = _sheet()
    with pytest.raises(CapabilityError):
        add_view(sheet, view="detail", file="d.png", sha256="d" * 64,
                 derives_from="headshot")


def test_anchor_change_marks_views_stale_not_deleted():
    sheet = _sheet()
    add_view(sheet, view="headshot", file="head.png", sha256="b" * 64)
    set_anchor(sheet, file="anchor2.png", sha256="z" * 64,
               look_snapshot="灰布长衫", description_fingerprint="fp2")
    result = check_anchor_sheet(sheet)
    assert result["stale_views"] == ["headshot"]
    assert len(sheet["views"]) == 1  # flagged, not deleted
    assert result["verdict"] in ("fail", "needs_regeneration")


def test_anchor_readd_supersedes_not_duplicates():
    sheet = _sheet()
    add_view(sheet, view="headshot", file="head.png", sha256="b" * 64)
    add_view(sheet, view="headshot", file="head2.png", sha256="e" * 64)
    result = check_anchor_sheet(sheet)
    assert result["verdict"] == "pass"
    assert [v["status"] for v in sheet["views"]] == ["superseded", "current"]
    assert description_fingerprint("abc") != description_fingerprint("abd")
