"""Tests for story.prompt_compiler (beat schema + five gates).

Positive fixture: E1 script v2 encoded as the beat schema
(tests/fixtures/e1_prompt_compiler_v2.json): 11 shots, 300s,
28 moving lines, plus one shot-level voiceover line (S10, counted
in de-duplication but not in the 28) and one shot-level subtitle
(S11, not spoken, not de-duplicated). Every gate has its own
negative case, built by mutating a copy of the positive fixture,
and each failure message must name the offending item.
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
    result = compile_episode(load_fixture())
    assert result["shot_count"] == 11
    assert result["total_duration_s"] == 300
    assert result["moving_line_count"] == 28
    assert result["spoken_line_count"] == 29  # 28 moving + 1 S10 voiceover
    assert result["tier"]["status"] == "unknown"
    assert len(result["prompts"]) == 11
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


def test_movement_table_is_hevis_own_40() -> None:
    table = _load_movement_table()
    assert len(table) == 40
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
    # Shrink beat 1 to 4s (line needs ~5.13s) while keeping the tiling
    # intact, so gate 1 still passes and gate 2 is the one that fires.
    beats[0]["t_end_s"] = 4
    beats[1]["t_start_s"] = 4
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
    # Reuse S03 beat 5 (7s span, fits the stolen line's ~5.13s) so
    # gate 2 still passes and gate 3 is the one that fires.
    beat = shot_of(episode, "S03")["beats"][4]
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
    episode = load_fixture()
    with pytest.raises(PromptCompilerError) as excinfo:
        compile_episode(episode, {"provider": "test", "max_shot_s": 30})
    message = str(excinfo.value)
    assert "gate 5" in message
    assert "S04" in message  # 35s shot breaches a 30s cap
    assert "30" in message


def test_gate5_tier_cap_passes_when_shots_fit() -> None:
    result = compile_episode(load_fixture(), {"max_shot_s": 35})
    assert result["tier"]["status"] == "checked"


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
