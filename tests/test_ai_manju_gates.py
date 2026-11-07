"""Tests for the ai-manju graft (A1-A5 gates, B1-B2 compilers).

Clean-room: only the season-pack schema, the reference-use
discipline, the status-card monotonicity, the dialogue timeline
arithmetic, the genre scale table, the genre rhythm windows, and
the handbook compilation discipline are judged here. No template
text is copied, no generator runs, no key or GPU is needed. Real
generation waits on a channel, a key, and a budget, and is not
covered here.
"""

import pytest

from hevi.capabilities.dialogue_timeline_gate import check_dialogue_timeline
from hevi.capabilities.director_handbook_compiler import compile_handbook_block
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.genre_rhythm_pack import (
    check_episode_rhythm,
    get_genre_rhythm,
    list_genres,
)
from hevi.capabilities.genre_scale_table_gate import check_genre_scale
from hevi.capabilities.reference_use_gate import check_reference_use
from hevi.capabilities.registry import get as registry_get
from hevi.capabilities.season_pack_gate import check_season_pack
from hevi.capabilities.status_card_monotonic_gate import check_status_cards

_SHA = "a" * 64


def _numbering_plan():
    return {
        "route": "generation",
        "numbering_convention": "identity-first",
        "pictures": [
            {"number": 1, "role": "identity", "file": "pic1.png",
             "sha256": _SHA, "duty": "identity"},
            {"number": 2, "role": "camera_composition", "file": "pic2.png",
             "sha256": "b" * 64, "duty": "composition",
             "composition_only": True},
            {"number": 3, "role": "scene", "file": "pic3.png",
             "sha256": "c" * 64, "duty": "scene"},
        ],
    }


def _shot(shot_no, *, side="left", props=None, outgoing=None, incoming=None,
          duration=6.0, still="开场静帧：人物立于庭中"):
    beats = [{"t_start_s": 0.0, "t_end_s": duration,
              "action": "人物抬手", "camera_move": "保持机位"}]
    shot = {
        "shot_no": shot_no,
        "segment_a": {"still_text": still},
        "segment_b": {
            "style": "水墨风",
            "characters": ["主角"],
            "beats": beats,
            "duration_s": duration,
            "aspect": "9:16",
        },
        "references": _numbering_plan(),
        "camera_side": side,
    }
    if props is not None:
        shot["props"] = props
    if outgoing is not None:
        shot["outgoing"] = outgoing
    if incoming is not None:
        shot["incoming"] = incoming
    return shot


_MATCH_OUT = {"direction": "left-to-right", "speed": 1.0,
              "end_state": "arm raised", "handoff_kind": "gesture",
              "gesture": "wave"}
_MATCH_IN = {"direction": "left-to-right", "speed": 1.0,
             "start_state": "arm raised", "handoff_kind": "gesture",
             "gesture": "wave"}


# ---- A1 season pack ----

def _pack(**overrides):
    pack = {
        "season_no": 1,
        "duration_tier_provider": "pixstag",
        "foreshadow_ledger": ["伏笔一"],
        "clue_ledger": ["线索一"],
        "episodes": [
            {"episode_no": 1, "duration_s": 240.0, "scenes": 5,
             "hook": "钩子一"},
            {"episode_no": 2, "duration_s": 240.0, "scenes": 5,
             "hook": "钩子二"},
        ],
    }
    pack.update(overrides)
    return pack


def test_a1_pass():
    report = check_season_pack(_pack())
    assert report["verdict"] == "pass", report["issues"]


def test_a1_later_episode_shorter_fails():
    pack = _pack()
    pack["episodes"][1]["duration_s"] = 200.0
    report = check_season_pack(pack)
    assert report["verdict"] == "fail"
    assert any(i["code"] == "later_episode_shorter_than_first"
               for i in report["issues"])


def test_a1_missing_ledger_and_unknown_tier_fail():
    pack = _pack(foreshadow_ledger=None, duration_tier_provider="nope")
    report = check_season_pack(pack)
    codes = {i["code"] for i in report["issues"]}
    assert "ledger_missing" in codes
    assert "duration_tier_unresolved" in codes


def test_a1_hook_synopsis_mismatch_fails():
    pack = _pack(episode_synopses={"1": "完全不相关的内容"})
    report = check_season_pack(pack)
    assert any(i["code"] == "hook_synopsis_mismatch" for i in report["issues"])


# ---- A2 reference use ----

def _ref_plan(**overrides):
    plan = {
        "numbering_convention": "identity-first",
        "references": [
            {"ref_number": 1, "role": "identity", "kind": "character",
             "asset_id": "hero", "takes": ["likeness"], "view": "front"},
            {"ref_number": 2, "role": "camera_composition", "kind": "scene",
             "asset_id": "hall", "takes": ["structure"], "view": "wide"},
            {"ref_number": 3, "role": "scene", "kind": "prop",
             "asset_id": "sword", "takes": ["form"],
             "front_back_consistent": True, "view": "front"},
        ],
    }
    plan.update(overrides)
    return plan


def test_a2_pass():
    report = check_reference_use(_ref_plan())
    assert report["verdict"] == "pass", report["issues"]


def test_a2_character_overreach_fails():
    plan = _ref_plan()
    plan["references"][0]["takes"] = ["likeness", "pose"]
    report = check_reference_use(plan)
    assert any(i["code"] == "character_reference_overreach"
               for i in report["issues"])


def test_a2_mixed_n_and_role_mismatch_fail():
    plan = _ref_plan()
    plan["references"][0]["asset_id"] = "Mixed 1"
    plan["references"][0]["role"] = "scene"
    report = check_reference_use(plan)
    codes = {i["code"] for i in report["issues"]}
    assert "mixed_n_notation" in codes
    assert "numbering_role_mismatch" in codes


def test_a2_duplicate_view_and_prop_inconsistent_fail():
    plan = _ref_plan()
    plan["references"].append(
        {"ref_number": 4, "role": "scene", "kind": "prop",
         "asset_id": "sword", "takes": ["form"], "view": "front"})
    plan["references"][2]["front_back_consistent"] = False
    report = check_reference_use(plan)
    codes = {i["code"] for i in report["issues"]}
    assert "duplicate_view" in codes
    assert "prop_front_back_inconsistent" in codes


# ---- A3 status card monotonicity ----

def _status_plan(**overrides):
    plan = {
        "subjects": [
            {"subject_id": "hero", "state_order": ["LOOK-A", "LOOK-B", "LOOK-C"],
             "declarations": [
                 {"state": "LOOK-A", "episode_no": 1},
                 {"state": "LOOK-B", "episode_no": 2},
                 {"state": "LOOK-C", "episode_no": 3},
             ]},
        ]
    }
    plan.update(overrides)
    return plan


def test_a3_pass_and_stay_allowed():
    plan = _status_plan()
    plan["subjects"][0]["declarations"].append(
        {"state": "LOOK-C", "episode_no": 4})
    report = check_status_cards(plan)
    assert report["verdict"] == "pass", report["issues"]


def test_a3_regression_fails():
    plan = _status_plan()
    plan["subjects"][0]["declarations"].append(
        {"state": "LOOK-A", "episode_no": 4})
    report = check_status_cards(plan)
    assert any(i["code"] == "state_regression" for i in report["issues"])


def test_a3_excused_regression_recorded():
    plan = _status_plan()
    plan["subjects"][0]["declarations"].append(
        {"state": "LOOK-A", "episode_no": 4, "justification": "rest",
         "justification_note": "休养一集后恢复旧装"})
    report = check_status_cards(plan)
    assert report["verdict"] == "pass", report["issues"]
    assert len(report["excused_regressions"]) == 1


def test_a3_unknown_state_fails():
    plan = _status_plan()
    plan["subjects"][0]["declarations"][0]["state"] = "LOOK-Z"
    report = check_status_cards(plan)
    assert any(i["code"] == "unknown_state" for i in report["issues"])


# ---- A4 dialogue timeline ----

def _timeline(**overrides):
    plan = {
        "total_duration_s": 10.0,
        "chars_per_second": 4.0,
        "segments": [
            {"t_start_s": 0.0, "t_end_s": 5.0, "dialogue_chars": 20},
            {"t_start_s": 5.0, "t_end_s": 10.0, "dialogue_chars": 18},
        ],
    }
    plan.update(overrides)
    return plan


def test_a4_pass():
    report = check_dialogue_timeline(_timeline())
    assert report["verdict"] == "pass", report["issues"]


def test_a4_rate_undeclared_fails():
    plan = _timeline()
    del plan["chars_per_second"]
    report = check_dialogue_timeline(plan)
    assert any(i["code"] == "rate_undeclared" for i in report["issues"])


def test_a4_overflow_and_split():
    plan = _timeline()
    plan["segments"][0]["dialogue_chars"] = 30
    report = check_dialogue_timeline(plan)
    assert any(i["code"] == "dialogue_overflows_budget"
               for i in report["issues"])
    plan["segments"][0] = {
        "t_start_s": 0.0, "t_end_s": 5.0, "dialogue_chars": 30,
        "subsegments": [
            {"part": "a", "t_start_s": 0.0, "t_end_s": 2.5,
             "dialogue_chars": 10},
            {"part": "b", "t_start_s": 2.5, "t_end_s": 5.0,
             "dialogue_chars": 20},
        ],
    }
    # part b: 20 chars in 2.5s at 4/s = budget 10 -> still overflows.
    report = check_dialogue_timeline(plan)
    assert report["verdict"] == "fail"
    plan["segments"][0]["subsegments"][1]["dialogue_chars"] = 10
    plan["segments"][0]["dialogue_chars"] = 20
    report = check_dialogue_timeline(plan)
    assert report["verdict"] == "pass", report["issues"]


def test_a4_gap_fails():
    plan = _timeline()
    plan["segments"][1]["t_start_s"] = 6.0
    report = check_dialogue_timeline(plan)
    assert any(i["code"] == "timeline_not_tiled" for i in report["issues"])


# ---- A5 genre scale table ----

def _scale_plan(**overrides):
    plan = {
        "genre": "xiaoyuan",
        "scale_table": {
            "min_character_age": 18,
            "boundaries": ["校园角色均为大学生"],
            "min_character_age_18_or_above": True,
            "university_setting": True,
            "no_middle_school_elements": True,
        },
    }
    plan.update(overrides)
    return plan


def test_a5_pass():
    report = check_genre_scale(_scale_plan())
    assert report["verdict"] == "pass", report["issues"]
    assert report["scope"] == "plan_text_only_not_execution_block"


def test_a5_missing_table_fails():
    report = check_genre_scale({"genre": "xuanyi"})
    assert any(i["code"] == "scale_table_missing" for i in report["issues"])


def test_a5_genre_boundary_and_prohibited_flag_fail():
    plan = _scale_plan(
        genre="xuanyi",
        scale_table={"min_character_age": 18,
                     "boundaries": ["悬疑边界"],
                     "no_crimes_against_minors": True},
        content_flags=["ritual_tutorial"],
    )
    report = check_genre_scale(plan)
    codes = {i["code"] for i in report["issues"]}
    assert "genre_boundary_undeclared" in codes  # no_imitable_methods missing
    assert "declared_prohibited_content" in codes


# ---- B1 genre rhythm pack ----

def test_b1_all_21_genres_parse():
    genres = list_genres()
    assert len(genres) == 21
    for spec in genres:
        assert spec["shots_min"] <= spec["shots_max"]
        assert spec["dialogue_min"] <= spec["dialogue_max"]
        assert spec["scenes_min"] == 4 and spec["scenes_max"] == 7
        assert spec["verified"] is False


def test_b1_check_and_override():
    assert check_episode_rhythm("xuanhuan", 40, 300, 5)["verdict"] == "pass"
    report = check_episode_rhythm("xuanhuan", 60, 300, 5)
    assert report["verdict"] == "fail"
    overridden = check_episode_rhythm(
        "xuanhuan", 60, 300, 5, overrides={"shots_max": 60})
    assert overridden["verdict"] == "pass"
    assert overridden["overrides"] == {"shots_max": 60}
    assert get_genre_rhythm("悬疑")["genre"] == "xuanyi"
    with pytest.raises(CapabilityError):
        get_genre_rhythm("不存在的题材")


# ---- B2 handbook compiler ----

def test_b2_pass_two_shots():
    block = {
        "episode_no": 1,
        "provider": "pixstag",
        "shots": [
            _shot(1, props=[{"prop_id": "sword", "state": "sheathed"}],
                  outgoing=_MATCH_OUT),
            _shot(2, props=[{"prop_id": "sword", "state": "sheathed"}],
                  incoming=_MATCH_IN),
        ],
    }
    report = compile_handbook_block(block)
    assert report["verdict"] == "pass", report["issues"]
    assert report["continuity"]["segment_match"] == "pass"
    assert "[静图瞬间]" in report["shots"][0]["compiled_text"]
    assert "0.000" in report["shots"][0]["compiled_text"]  # millisecond timecode


def test_b2_axis_crossing_fails():
    block = {
        "episode_no": 1,
        "shots": [_shot(1, side="left"), _shot(2, side="right")],
    }
    report = compile_handbook_block(block)
    assert any(i["code"] == "axis_crossing_unjustified"
               for i in report["issues"])
    block["shots"][1]["axis_crossing_justified"] = True
    # Still fails: no match declarations on a multi-shot block.
    report = compile_handbook_block(block)
    assert any(i["code"] == "missing_match_declarations"
               for i in report["issues"])


def test_b2_prop_break_fails():
    block = {
        "episode_no": 1,
        "shots": [
            _shot(1, props=[{"prop_id": "sword", "state": "sheathed"}],
                  outgoing=_MATCH_OUT),
            _shot(2, props=[{"prop_id": "sword", "state": "drawn"}],
                  incoming=_MATCH_IN),
        ],
    }
    report = compile_handbook_block(block)
    assert any(i["code"] == "prop_state_break" for i in report["issues"])
    block["shots"][1]["prop_transitions"] = ["sword"]
    report = compile_handbook_block(block)
    assert report["verdict"] == "pass", report["issues"]


def test_b2_prop_vanish_and_tier_cap_fail():
    block = {
        "episode_no": 1,
        "provider": "pixstag",
        "shots": [
            _shot(1, props=[{"prop_id": "sword", "state": "sheathed"}],
                  outgoing=_MATCH_OUT, duration=40.0),
            _shot(2, incoming=_MATCH_IN),
        ],
    }
    report = compile_handbook_block(block)
    codes = {i["code"] for i in report["issues"]}
    assert "shot_exceeds_tier_cap" in codes
    assert "prop_disappears_undeclared" in codes


# ---- registry ----

@pytest.mark.parametrize("name", [
    "qa.season_pack_gate",
    "qa.reference_use_gate",
    "qa.status_card_monotonic_gate",
    "qa.dialogue_timeline_gate",
    "qa.genre_scale_table_gate",
    "story.genre_rhythm_pack",
    "story.director_handbook_compiler",
])
def test_registry_resolves(name):
    assert registry_get(name) is not None
