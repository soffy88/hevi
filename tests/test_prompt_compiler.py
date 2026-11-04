"""Tests for story.prompt_compiler (beat schema + five gates).

Positive fixture: E1 script v2 encoded as the beat schema
(tests/fixtures/e1_prompt_compiler_v2.json) -- the E1 v2 production
encoding (recut version): 11 shots, 300s, 92 beats, 19 explicit clips
(8-12s each), 28 moving lines, plus one shot-level voiceover line
(S10, counted in de-duplication but not in the 28) and one shot-level
subtitle (S11, not spoken, not de-duplicated). Dialogue beats run
4-6s, silent motion beats 2-3s, still beats <=4s; pure-still shots
carry clips == [] (no generation call) and are not tier-checked.
Every gate has its own negative case, built by mutating a copy of
the positive fixture, and each failure message must name the
offending item.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from hevi.capabilities.prompt_compiler import (
    PromptCompilerError,
    _load_movement_table,
    compile_episode,
    estimate_min_line_duration_s,
    load_duration_tiers,
    resolve_provider_caps,
)

FIXTURE = (
    Path(__file__).resolve().parent / "fixtures" / "e1_prompt_compiler_v2.json"
)


def load_fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def shot_of(episode: dict, shot_no: str) -> dict:
    for shot in episode["shots"]:
        if shot["shot_no"] == shot_no:
            return shot
    raise AssertionError(f"no shot {shot_no}")


# ---------------------------------------------------------------------------
# Positive case
# ---------------------------------------------------------------------------


def test_e1_fixture_compiles_clean() -> None:
    episode = load_fixture()
    result = compile_episode(episode)
    assert result["shot_count"] == 11
    assert result["total_duration_s"] == 300
    assert result["moving_line_count"] == 28
    assert result["spoken_line_count"] == 29  # 28 moving + 1 S10 voiceover
    assert result["tier"]["status"] == "unknown"
    assert len(result["prompts"]) == 11
    # Recut production encoding: 92 beats, 19 explicit clips.
    assert sum(len(s["beats"]) for s in episode["shots"]) == 92
    assert sum(len(s["clips"]) for s in episode["shots"]) == 19
    # Q5: S10 location is the inferred 塾内, annotated as inferred.
    s10 = shot_of(episode, "S10")
    assert s10["continuity"]["entry_state"]["空间锚点"] == "京师私塾塾内"
    assert "推断" in s10["location_note"] and "编剧可改" in s10["location_note"]
    # Q5: S10/S11 continuity entries carry no 人物 (VO bridge / subtitle
    # card); S10's deletions of the S09 characters are declared nulls.
    assert s10["continuity"]["entry_state"]["人物"] == {}
    assert s10["continuity"]["new_changes"]["人物.青年"] is None
    assert s10["continuity"]["new_changes"]["人物.问话者"] is None
    assert shot_of(episode, "S11")["continuity"]["entry_state"]["人物"] == {}
    # Q4 clears the old fixture's invented motion: S01/S11 are pure
    # still shots with static shot-level movement.
    assert shot_of(episode, "S01")["camera"]["movement"] == "static_shot"
    assert shot_of(episode, "S11")["camera"]["movement"] == "static_shot"
    assert shot_of(episode, "S01")["clips"] == []
    assert shot_of(episode, "S11")["clips"] == []
    # Q4 clears the old fixture's accumulated state: S06 entry carries
    # only the hall's own characters, not the school's.
    assert set(shot_of(episode, "S06")["continuity"]["entry_state"]["人物"]) == {
        "王华", "守仁",
    }
    subtitle = "下集《格竹之败》"
    prompts = {p["shot_no"]: p["prompt"] for p in result["prompts"]}
    # The subtitle is a post-production note only, never picture text.
    assert "[字幕·后期叠加，不进画面生成]" in prompts["S11"]
    assert subtitle in prompts["S11"]
    assert subtitle not in prompts["S06"]
    # S10 voiceover is rendered, but as narration, not as lip-sync dialogue.
    assert "人人都可以成为尧舜。" in prompts["S10"]
    assert "不对口型" in prompts["S10"]


def test_s06_prompt_carries_verbatim_lines_and_bans() -> None:
    result = compile_episode(load_fixture())
    prompt = next(
        p["prompt"] for p in result["prompts"] if p["shot_no"] == "S06"
    )
    for line in (
        "今天先生问什么了？",
        "问我们为什么读书。",
        "我说想做圣贤……全班都笑我。",
        "笑就笑吧。",
        "别人笑，不代表你错了。",
        "你的志气，自己拿稳了。",
    ):
        assert line in prompt
    assert prompt.startswith("[风格]")
    assert "[时长]35秒" in prompt
    assert "[入口状态]" in prompt
    assert "[出口状态]" in prompt
    assert "[约束]" in prompt
    assert "只说本提示词里逐字写出的台词" in prompt
    assert "画面里不许出现任何文字、字幕、水印" in prompt
    assert "禁叠化" in prompt


def test_movement_table_is_hevis_own_46() -> None:
    table = _load_movement_table()
    assert len(table) == 46
    assert table["dolly_in"]["zh"] == "前推轨道"
    assert table["slow_zoom_in"]["en"] == "Slow zoom in"


def test_line_duration_estimator() -> None:
    # 2 chars at normal 3/s + 1 punct * 0.4 + 1.0 margin.
    assert estimate_min_line_duration_s("你好。", "normal") == pytest.approx(
        2 / 3 + 0.4 + 1.0
    )
    assert estimate_min_line_duration_s("你好。", "fast") == pytest.approx(
        2 / 4 + 0.4 + 1.0
    )
    assert estimate_min_line_duration_s("你好。", "slow") == pytest.approx(
        2 / 2 + 0.4 + 1.0
    )
    assert estimate_min_line_duration_s("你好。") == pytest.approx(
        2 / 4 + 0.4 + 1.0
    )
    assert estimate_min_line_duration_s("") == 0.0
    assert estimate_min_line_duration_s("   ") == 0.0


def test_capability_registered_on_package_import() -> None:
    import hevi.capabilities as caps

    assert "story.prompt_compiler" in caps.names()


# ---------------------------------------------------------------------------
# Vocabulary interception
# ---------------------------------------------------------------------------


def test_unknown_movement_rejected_naming_shot() -> None:
    episode = load_fixture()
    shot_of(episode, "S01")["camera"]["movement"] = "飞天遁地"
    with pytest.raises(PromptCompilerError) as excinfo:
        compile_episode(episode)
    assert "S01" in str(excinfo.value)
    assert "飞天遁地" in str(excinfo.value)


def test_unknown_shot_size_rejected() -> None:
    episode = load_fixture()
    shot_of(episode, "S01")["camera"]["shot_size"] = "显微镜"
    with pytest.raises(PromptCompilerError) as excinfo:
        compile_episode(episode)
    assert "S01" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Gate 1: beat coverage
# ---------------------------------------------------------------------------


def test_gate1_beat_gap_fails_naming_shot() -> None:
    episode = load_fixture()
    beat = shot_of(episode, "S02")["beats"][1]
    beat["t_start_s"] = 7  # was 6: leaves a 6-7s gap after beat 1
    with pytest.raises(PromptCompilerError) as excinfo:
        compile_episode(episode)
    assert "S02" in str(excinfo.value)
    assert "gate 1" in str(excinfo.value)


def test_gate1_beat_sum_mismatch_fails() -> None:
    episode = load_fixture()
    shot_of(episode, "S02")["beats"][-1]["t_end_s"] = 24  # was 25
    with pytest.raises(PromptCompilerError) as excinfo:
        compile_episode(episode)
    assert "S02" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Gate 2: line duration fits its beat
# ---------------------------------------------------------------------------


def test_gate2_line_too_long_for_beat_fails_naming_line() -> None:
    episode = load_fixture()
    beats = shot_of(episode, "S02")["beats"]
    # Shrink S02 beat 3 (dialogue, 4.5s) to 4s -- its line needs 4.30s --
    # while keeping the tiling intact, so gate 1 still passes and
    # gate 2 is the one that fires.
    beats[2]["t_end_s"] = 10
    beats[3]["t_start_s"] = 10
    with pytest.raises(PromptCompilerError) as excinfo:
        compile_episode(episode)
    message = str(excinfo.value)
    assert "gate 2" in message
    assert "S02" in message
    assert "都说说，读书是为了什么？" in message


# ---------------------------------------------------------------------------
# Gate 3: one line in exactly one place
# ---------------------------------------------------------------------------


def test_gate3_duplicate_line_fails_naming_both_places() -> None:
    episode = load_fixture()
    stolen = "都说说，读书是为了什么？"
    # Reuse S03 beat 3 (4.5s span, fits the stolen line's 4.30s) so
    # gate 2 still passes and gate 3 is the one that fires.
    beat = shot_of(episode, "S03")["beats"][2]
    beat["line"] = stolen
    beat["speaker"] = "塾师"
    beat["line_mode"] = "dialogue"
    with pytest.raises(PromptCompilerError) as excinfo:
        compile_episode(episode)
    message = str(excinfo.value)
    assert "gate 3" in message
    assert stolen in message
    assert "S02" in message and "S03" in message


def test_gate3_voiceover_duplicating_dialogue_fails() -> None:
    episode = load_fixture()
    shot_of(episode, "S10")["voiceover_line"] = "都说说，读书是为了什么？"
    with pytest.raises(PromptCompilerError) as excinfo:
        compile_episode(episode)
    assert "gate 3" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Gate 4: continuity chain + start-frame trigger state
# ---------------------------------------------------------------------------


def test_gate4_chain_break_fails_naming_shot_and_item() -> None:
    episode = load_fixture()
    shot = shot_of(episode, "S03")
    shot["continuity"]["entry_state"]["人物"]["守仁"] = "竹林"
    with pytest.raises(PromptCompilerError) as excinfo:
        compile_episode(episode)
    message = str(excinfo.value)
    assert "gate 4" in message
    assert "S03" in message
    assert "人物.守仁" in message


def test_gate4_completed_start_frame_fails_naming_shot() -> None:
    episode = load_fixture()
    shot_of(episode, "S02")["camera"]["start_frame"]["state_kind"] = "completed"
    with pytest.raises(PromptCompilerError) as excinfo:
        compile_episode(episode)
    message = str(excinfo.value)
    assert "gate 4" in message
    assert "S02" in message


def test_gate4_missing_start_frame_marker_fails() -> None:
    episode = load_fixture()
    del shot_of(episode, "S02")["camera"]["start_frame"]["state_kind"]
    with pytest.raises(PromptCompilerError):
        compile_episode(episode)


# ---------------------------------------------------------------------------
# Gate 5: episode total + supplier tier
# ---------------------------------------------------------------------------


def test_gate5_total_mismatch_fails() -> None:
    episode = load_fixture()
    episode["target_duration_s"] = 299
    with pytest.raises(PromptCompilerError) as excinfo:
        compile_episode(episode)
    message = str(excinfo.value)
    assert "gate 5" in message
    assert "300" in message and "299" in message


def test_gate5_tier_cap_breach_fails_naming_shot_and_cap() -> None:
    # Legacy unit: a shot without a "clips" key is one generation call,
    # so a 35s clip-less shot still breaches a 30s cap.
    episode = _mini_episode([_mini_beat(1, 0, 16, "")])
    episode["target_duration_s"] = 35
    episode["shots"][0]["duration_s"] = 35
    episode["shots"][0]["beats"][0]["t_end_s"] = 35
    with pytest.raises(PromptCompilerError) as excinfo:
        compile_episode(episode, {"provider": "test", "max_shot_s": 30})
    message = str(excinfo.value)
    assert "gate 5" in message
    assert "T01" in message  # 35s shot breaches a 30s cap
    assert "30" in message


def test_gate5_tier_cap_passes_when_shots_fit() -> None:
    result = compile_episode(load_fixture(), {"max_shot_s": 35})
    assert result["tier"]["status"] == "checked"
    assert result["tier"]["tier_scope"] == "clip"


# ---------------------------------------------------------------------------
# Long-line split rule
# ---------------------------------------------------------------------------


def _mini_episode(beats: list[dict]) -> dict:
    return {
        "episode_no": "T01",
        "title": "split-rule probe",
        "target_duration_s": 16,
        "aspect": "16:9",
        "style": "测试风格",
        "shots": [
            {
                "shot_no": "T01",
                "scene": "测试间",
                "time_of_day": "日光",
                "duration_s": 16,
                "characters": ["甲"],
                "props": [],
                "camera": {
                    "shot_size": "中景",
                    "angle": "平视",
                    "movement": "static_shot",
                    "start_frame": {
                        "description": "甲正要开口",
                        "state_kind": "trigger_in_progress",
                    },
                    "end_frame": {"description": "甲说完"},
                },
                "beats": beats,
                "continuity": {
                    "entry_state": {"人物": {"甲": "室内"}},
                    "exit_state": {"人物": {"甲": "室内"}},
                    "new_changes": {},
                },
            }
        ],
    }


def _mini_beat(no: int, t0: float, t1: float, line: str, **extra: object) -> dict:
    beat: dict = {
        "beat_no": no,
        "t_start_s": t0,
        "t_end_s": t1,
        "action": "甲说话",
        "gaze_target": "前方",
        "camera_move": "static_shot",
        "speaker": "甲",
        "line": line,
        "line_function": "陈述",
        "line_mode": "dialogue",
        "sound": "室内安静",
        "pace": "normal",
        "landing": "甲说完",
    }
    beat.update(extra)
    return beat


def test_long_line_without_split_fails_naming_line() -> None:
    long_line = "这是一个超过二十个字的长句子需要拆分才行啊"  # 21 chars
    assert len(long_line) == 21
    episode = _mini_episode([_mini_beat(1, 0, 16, long_line)])
    with pytest.raises(PromptCompilerError) as excinfo:
        compile_episode(episode)
    message = str(excinfo.value)
    assert long_line in message
    assert "line_group" in message


def test_long_line_split_across_grouped_beats_passes() -> None:
    full = "这是一个超过二十个字的长句子需要拆分才行啊"
    episode = _mini_episode(
        [
            _mini_beat(
                1, 0, 8, "这是一个超过二十个字的长句子",
                line_group="g1", line_full=full,
            ),
            _mini_beat(2, 8, 16, "需要拆分才行啊", line_group="g1"),
        ]
    )
    result = compile_episode(episode)
    assert result["moving_line_count"] == 1


# ---------------------------------------------------------------------------
# Duration tier table (residual 1) + S10/S11 coverage (residual 4)
# ---------------------------------------------------------------------------


def test_duration_tier_table_values_are_cited() -> None:
    tiers = load_duration_tiers()
    assert tiers["fasth3_local"]["max_shot_s"] == 15.0
    assert tiers["fasth3_local"]["source"].startswith(
        "hevi/capabilities/fasth3_local.py"
    )
    assert tiers["pixstag"]["max_shot_s"] == 30.0
    assert tiers["pixstag"]["min_shot_s"] == 4
    assert tiers["veo3"]["max_shot_s"] == 8.0
    assert tiers["gemini_api"]["max_shot_s"] is None
    assert tiers["gemini_api"]["max_total_s"] is None
    # No episode-total cap is verified anywhere: null, never invented.
    assert all(t.get("max_total_s") is None for t in tiers.values())
    assert resolve_provider_caps("fasth3_local")["max_shot_s"] == 15.0
    assert resolve_provider_caps("no_such_provider") is None


def test_gate5_table_cap_passes_fasth3_local_on_clip_level() -> None:
    # Q3: the tier is checked per clip, not per shot. The recut
    # fixture's clips are all 8-12s, inside fasth3_local 5.1667-15s,
    # so it passes -- and pure-still shots (S01 20s, S07 25s, S11 25s)
    # are not tier-checked at all, since they are no generation call.
    episode = load_fixture()
    assert shot_of(episode, "S01")["duration_s"] == 20
    assert shot_of(episode, "S07")["duration_s"] == 25
    assert shot_of(episode, "S11")["duration_s"] == 25
    result = compile_episode(episode, provider="fasth3_local")
    assert result["tier"]["status"] == "checked"
    assert result["tier"]["tier_scope"] == "clip"
    assert result["tier"]["max_shot_s"] == 15.0
    assert result["tier"]["min_shot_s"] == 5.1667


def test_gate5_table_cap_passes_when_shots_fit() -> None:
    episode = _mini_episode([_mini_beat(1, 0, 15, "短句。")])
    episode["target_duration_s"] = 15
    episode["shots"][0]["duration_s"] = 15
    result = compile_episode(episode, provider="fasth3_local")
    assert result["tier"]["status"] == "checked"
    assert result["tier"]["max_shot_s"] == 15.0


def test_gate5_unknown_provider_key_is_unknown_not_blocking() -> None:
    result = compile_episode(load_fixture(), provider="no_such_provider")
    assert result["tier"]["status"] == "unknown"
    assert "no_such_provider" in result["tier"]["reason"]


def test_gate5_null_cap_provider_is_unknown_not_blocking() -> None:
    result = compile_episode(load_fixture(), provider="gemini_api")
    assert result["tier"]["status"] == "unknown"
    assert "no verified cap" in result["tier"]["reason"]


def test_gate5_explicit_caps_win_over_table() -> None:
    result = compile_episode(
        load_fixture(), {"max_shot_s": 40}, provider="fasth3_local"
    )
    assert result["tier"]["status"] == "checked"
    assert result["tier"]["max_shot_s"] == 40


def test_gate5_total_mismatch_still_fails_when_tier_unknown() -> None:
    episode = load_fixture()
    episode["target_duration_s"] = 299
    with pytest.raises(PromptCompilerError) as excinfo:
        compile_episode(episode, provider="gemini_api")
    message = str(excinfo.value)
    assert "gate 5" in message
    assert "300" in message and "299" in message


def test_gate2_voiceover_too_long_for_shot_fails() -> None:
    episode = load_fixture()
    base = "这是一个故意写得很长的画外音句子用来验证时长门禁是否覆盖画外音"
    shot_of(episode, "S10")["voiceover_line"] = base + base  # 62 chars > 15s shot
    with pytest.raises(PromptCompilerError) as excinfo:
        compile_episode(episode)
    message = str(excinfo.value)
    assert "gate 2" in message
    assert "voiceover" in message


def test_gate3_subtitle_text_matching_dialogue_does_not_trip_dedup() -> None:
    episode = load_fixture()
    shot_of(episode, "S11")["subtitle"] = "今天先生问什么了？"
    result = compile_episode(episode)
    assert result["spoken_line_count"] == 29
    assert result["moving_line_count"] == 28


# ---------------------------------------------------------------------------
# Gate 4 null removal (Q2 fix) + S10 A/B probes (Q5) + clip grouping (Q3)
# ---------------------------------------------------------------------------


def _two_shot_null_episode(x2_entry: dict, x2_changes: dict) -> dict:
    def _shot(no: str, entry: dict, exit_state: dict, changes: dict) -> dict:
        return {
            "shot_no": no,
            "scene": "测试间",
            "duration_s": 5,
            "camera": {
                "shot_size": "中景",
                "angle": "平视",
                "movement": "static_shot",
                "start_frame": {
                    "description": "起",
                    "state_kind": "trigger_in_progress",
                },
                "end_frame": {"description": "收"},
            },
            "beats": [
                {
                    "beat_no": 1,
                    "t_start_s": 0.0,
                    "t_end_s": 5.0,
                    "action": "静",
                    "sound": "静",
                }
            ],
            "continuity": {
                "entry_state": entry,
                "exit_state": exit_state,
                "new_changes": changes,
            },
        }

    x1_state = {"人物": {"A": "在场", "B": "在场"}}
    return {
        "episode_no": "T",
        "title": "探针",
        "target_duration_s": 10,
        "aspect": "16:9",
        "style": "测",
        "shots": [
            _shot("X1", x1_state, x1_state, {}),
            _shot("X2", x2_entry, x2_entry, x2_changes),
        ],
    }


def test_gate4_null_removal_passes() -> None:
    # Audit minimal repro: X1 exit has 人物.A, X2 entry only 人物.B,
    # new_changes declares 人物.A null. Pre-Q2 this failed (null was
    # stringified to "None"); post-fix it passes.
    episode = _two_shot_null_episode(
        {"人物": {"B": "在场"}}, {"人物.A": None}
    )
    result = compile_episode(episode)
    assert result["shot_count"] == 2


def test_gate4_null_removal_but_carried_fails() -> None:
    episode = _two_shot_null_episode(
        {"人物": {"A": "在场", "B": "在场"}}, {"人物.A": None}
    )
    with pytest.raises(PromptCompilerError) as excinfo:
        compile_episode(episode)
    message = str(excinfo.value)
    assert "gate 4" in message
    assert "人物.A" in message


def test_gate4_s10_strict_anchor_omitted_fails() -> None:
    # Probe A (strict): S10 entry drops the anchor key and declares
    # nothing about it -- gate 4 must now reach S10 and fail there.
    episode = load_fixture()
    s10 = shot_of(episode, "S10")
    del s10["continuity"]["entry_state"]["空间锚点"]
    s10["continuity"]["new_changes"].pop("空间锚点", None)
    with pytest.raises(PromptCompilerError) as excinfo:
        compile_episode(episode)
    message = str(excinfo.value)
    assert "gate 4" in message
    assert "S10" in message
    assert "空间锚点" in message


def test_gate4_s10_undeclared_deletions_fail() -> None:
    # S10 entry人物 is empty; strip its null declarations and gate 4
    # must fail on the dropped S09 characters.
    episode = load_fixture()
    s10 = shot_of(episode, "S10")
    s10["continuity"]["new_changes"] = {
        k: v
        for k, v in s10["continuity"]["new_changes"].items()
        if v is not None
    }
    with pytest.raises(PromptCompilerError) as excinfo:
        compile_episode(episode)
    message = str(excinfo.value)
    assert "gate 4" in message
    assert "S10" in message
    assert "人物.青年" in message


def _clip_mini_episode() -> dict:
    def _silent(no: int, t0: float, t1: float) -> dict:
        return {
            "beat_no": no,
            "t_start_s": t0,
            "t_end_s": t1,
            "action": "静",
            "speaker": "",
            "line": "",
            "sound": "静",
        }

    return {
        "episode_no": "T",
        "title": "探针",
        "target_duration_s": 16,
        "aspect": "16:9",
        "style": "测",
        "shots": [
            {
                "shot_no": "T01",
                "scene": "测试间",
                "duration_s": 16,
                "camera": {
                    "shot_size": "中景",
                    "angle": "平视",
                    "movement": "static_shot",
                    "start_frame": {
                        "description": "起",
                        "state_kind": "trigger_in_progress",
                    },
                    "end_frame": {"description": "收"},
                },
                "beats": [_silent(1, 0, 8), _silent(2, 8, 16)],
                "clips": [{"clip_id": "c1", "beats": [1, 2]}],
                "continuity": {
                    "entry_state": {"人物": {"甲": "室内"}},
                    "exit_state": {"人物": {"甲": "室内"}},
                    "new_changes": {},
                },
            }
        ],
    }


def test_gate5_clip_breach_fails_naming_shot_and_clip() -> None:
    # One 16s clip breaches fasth3_local's 15s cap, naming shot+clip.
    with pytest.raises(PromptCompilerError) as excinfo:
        compile_episode(_clip_mini_episode(), provider="fasth3_local")
    message = str(excinfo.value)
    assert "gate 5" in message
    assert "T01" in message
    assert "c1" in message
    assert "16" in message and "15" in message


def test_gate5_clip_min_breach_fails() -> None:
    episode = _clip_mini_episode()
    episode["shots"][0]["beats"] = [
        {
            "beat_no": 1,
            "t_start_s": 0.0,
            "t_end_s": 4.0,
            "action": "静",
            "speaker": "",
            "line": "",
            "sound": "静",
        }
    ]
    episode["shots"][0]["duration_s"] = 4
    episode["target_duration_s"] = 4
    episode["shots"][0]["clips"] = [{"clip_id": "c1", "beats": [1]}]
    with pytest.raises(PromptCompilerError) as excinfo:
        compile_episode(episode, {"provider": "t", "min_shot_s": 5.1667})
    message = str(excinfo.value)
    assert "gate 5" in message
    assert "c1" in message


def test_clip_group_duplicate_beat_fails() -> None:
    episode = load_fixture()
    shot_of(episode, "S02")["clips"][0]["beats"] = [3, 3]
    with pytest.raises(PromptCompilerError) as excinfo:
        compile_episode(episode)
    assert "repeats beat_no 3" in str(excinfo.value)


def test_clip_group_non_consecutive_beats_fail() -> None:
    episode = load_fixture()
    shot_of(episode, "S02")["clips"][0]["beats"] = [3, 5]
    with pytest.raises(PromptCompilerError) as excinfo:
        compile_episode(episode)
    assert "not consecutive" in str(excinfo.value)


def test_clip_group_unknown_beat_fails() -> None:
    episode = load_fixture()
    shot_of(episode, "S02")["clips"][0]["beats"] = [3, 99]
    with pytest.raises(PromptCompilerError) as excinfo:
        compile_episode(episode)
    assert "unknown beat_no 99" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Clip-level rendering (production clip format)
# ---------------------------------------------------------------------------

RECUT_STYLE = (
    "Ming dynasty Chinese realistic film texture, warm candlelight "
    "interiors, warm morning light exteriors, warm evening light in "
    "the family hall, natural skin and real fabrics. No on-screen "
    "text, no subtitles, no watermark, no extra people. Speak only "
    "the lines written below, each line exactly once, in modern "
    "standard Mandarin at natural speed; only one person speaks at "
    "a time; silent beats are truly silent, no humming, no singing."
)


def test_clip_prompts_render_19_clips_verbatim_lines() -> None:
    from hevi.capabilities.prompt_compiler import compile_clip_prompts

    episode = load_fixture()
    prompts = compile_clip_prompts(episode, RECUT_STYLE)
    assert len(prompts) == 19
    for shot in episode["shots"]:
        beats = {b["beat_no"]: b for b in shot["beats"]}
        for clip in shot.get("clips", []):
            text = prompts[clip["clip_id"]]
            assert text.startswith(RECUT_STYLE + " Scene: ")
            for beat_no in clip["beats"]:
                beat = beats[beat_no]
                assert f"Beat: {beat['action']}" in text
                if beat.get("line"):
                    assert f"Line ({beat['speaker']}): {beat['line']}" in text


def test_clip_scene_first_clip_full_later_clips_first_sentence() -> None:
    from hevi.capabilities.prompt_compiler import (
        clip_scene_sentence,
        compile_clip_prompts,
    )

    episode = load_fixture()
    prompts = compile_clip_prompts(episode, RECUT_STYLE)
    for shot in episode["shots"]:
        full = str(shot["camera"]["start_frame"]["description"]).strip()
        first_sentence = full.split(". ")[0].strip()
        if not first_sentence.endswith("."):
            first_sentence += "."
        for index, clip in enumerate(shot.get("clips", [])):
            scene = prompts[clip["clip_id"]].split("Scene: ", 1)[1].split(" Beat: ", 1)[0]
            if index == 0:
                assert scene == full
            else:
                assert scene == first_sentence
            assert clip_scene_sentence(shot, index) == scene


def test_s03c3_scene_no_longer_claims_boy_sits() -> None:
    from hevi.capabilities.prompt_compiler import compile_clip_prompts

    prompts = compile_clip_prompts(load_fixture(), RECUT_STYLE)
    scene = prompts["S03c3"].split("Scene: ", 1)[1].split(" Beat: ", 1)[0]
    assert scene == "Medium shot of the same classroom, warm candlelight."
    assert "sits" not in scene
    assert "standing" not in scene


def test_s06c3_scene_no_longer_claims_son_enters() -> None:
    from hevi.capabilities.prompt_compiler import compile_clip_prompts

    prompts = compile_clip_prompts(load_fixture(), RECUT_STYLE)
    scene = prompts["S06c3"].split("Scene: ", 1)[1].split(" Beat: ", 1)[0]
    assert scene == (
        "Medium shot of a Ming family hall in the evening, warm evening light, "
        "a top-scholar plaque hanging high on the wall."
    )
    assert "enters" not in scene


def test_s09c2_scene_no_longer_claims_students_pass() -> None:
    from hevi.capabilities.prompt_compiler import compile_clip_prompts

    prompts = compile_clip_prompts(load_fixture(), RECUT_STYLE)
    scene = prompts["S09c2"].split("Scene: ", 1)[1].split(" Beat: ", 1)[0]
    assert scene == (
        "Medium shot of a modern Chinese city in daytime, "
        "outside a modern exam hall."
    )
    assert "Students pass" not in scene
