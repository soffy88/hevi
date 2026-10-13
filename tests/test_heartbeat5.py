"""Tests for the 5-segment heartbeat narrative structure (oskill).

Contract under test (DIRSTYLE_TASK_ADD1):
- N clips where N = duration / 10 (min 1).
- The Stage-1 golden hook lands inside the required 2–5 s window
  for short videos (15/30/60 s) and inside 5–15 s for 3 min.
- The structure only re-organises / rewrites the source; it never
  invents numbers, names, or quotations.
- Every clip carries three timed beats [0-3s][3-7s][7-10s].
- Visual continuity: segment i's ending frame == segment i+1's
  opening frame (named explicitly, not "same as before").
"""
from __future__ import annotations

import re

import pytest

from hevi.layer4_legacy.dirstyle.oskill_impl.heartbeat5 import (
    FactualError,
    HeartbeatPlan,
    clip_count_for_duration,
    hook_time_s,
    hook_window_s,
    plan_heartbeat5,
    validate_no_invented_numbers,
)

# A real, self-contained Chinese source text.  It contains one number
# (the word "三" written as a numeral-free word, plus one digit "3"
# we add intentionally to exercise fact preservation).
SOURCE_TEXT = (
    "猫为什么总爱把桌上的东西推下去？背后有三个原因。"
    "首先，猫的脚垫非常敏感，触碰物体是在测试猎物。"
    "轻轻一推，如果物体会动或逃跑，就意味着可能是活物。"
    "其次，高处跌落产生的声音和运动轨迹，对猫的神经系统是强烈刺激。"
    "最后，猫咪发现只要东西掉地，主人就会立刻冲过来，"
    "哪怕被责备两句也是极好的互动。"
)

# A source with explicit digits so we can assert they are preserved
# (and that no new digits are invented).
SOURCE_WITH_DIGITS = "地球绕太阳一圈大约365天。一天有24小时。"


class TestClipAllocation:
    def test_n_equals_duration_over_10(self):
        assert clip_count_for_duration(15) == 2
        assert clip_count_for_duration(30) == 3
        assert clip_count_for_duration(60) == 6
        assert clip_count_for_duration(180) == 18

    def test_minimum_one_clip(self):
        assert clip_count_for_duration(1) == 1
        assert clip_count_for_duration(0.5) == 1

    @pytest.mark.parametrize("duration", [15, 30, 60, 180])
    def test_plan_has_n_segments(self, duration):
        plan = plan_heartbeat5(source_text=SOURCE_TEXT, duration_s=duration)
        assert plan.clip_count == clip_count_for_duration(duration)
        assert len(plan.segments) == plan.clip_count
        for seg in plan.segments:
            assert seg.duration_s == 10.0


class TestHookWindow:
    """Hook must land inside 2–5 s for short videos."""

    @pytest.mark.parametrize("duration", [15, 30, 60])
    def test_hook_inside_2_to_5_seconds(self, duration):
        plan = plan_heartbeat5(source_text=SOURCE_TEXT, duration_s=duration)
        assert plan.hook_timing is not None
        # hook_time_s returns the start of the window for short videos
        assert hook_time_s(duration) == 2.0
        assert plan.hook_timing.hook_start_s == 2.0
        assert plan.hook_timing.within_window() is True
        # The hook flag is only set on the first clip
        assert plan.segments[0].hook is True
        for seg in plan.segments[1:]:
            assert seg.hook is False

    def test_180s_hook_inside_5_to_15_seconds(self):
        plan = plan_heartbeat5(source_text=SOURCE_TEXT, duration_s=180)
        assert plan.hook_timing is not None
        assert plan.hook_timing.hook_start_s == 5.0
        assert plan.hook_timing.window_start_s == 5.0
        assert plan.hook_timing.window_end_s == 15.0
        assert plan.hook_timing.within_window() is True

    @pytest.mark.parametrize("duration", [15, 30, 60])
    def test_hook_beat_is_first_clip(self, duration):
        plan = plan_heartbeat5(source_text=SOURCE_TEXT, duration_s=duration)
        assert plan.segments[0].hook_time_s == hook_time_s(duration)
        # The hook sits inside clip 1's [0-3s] beat window
        assert plan.segments[0].beats.get("0-3s")


class TestThreeBeatsPerClip:
    @pytest.mark.parametrize("duration", [15, 30, 60, 180])
    def test_every_clip_has_three_beats(self, duration):
        plan = plan_heartbeat5(source_text=SOURCE_TEXT, duration_s=duration)
        for seg in plan.segments:
            assert set(seg.beats.keys()) == {"0-3s", "3-7s", "7-10s"}
            for beat in seg.beats.values():
                assert beat.strip()

    @pytest.mark.parametrize("duration", [15, 30, 60])
    def test_all_five_stages_present(self, duration):
        """Across the plan, all 5 heartbeat stages must appear."""
        plan = plan_heartbeat5(source_text=SOURCE_TEXT, duration_s=duration)
        stages = {seg.stage_zh for seg in plan.segments}
        assert "黄金钩子" in stages
        assert "升华互动" in stages
        # Stage 0 always on clip 0, stage 4 always on last clip
        assert plan.segments[0].stage_zh == "黄金钩子"
        assert plan.segments[-1].stage_zh == "升华互动"


class TestFactPreservation:
    """No invented numbers, names, or quotations."""

    def test_source_digits_preserved(self):
        plan = plan_heartbeat5(source_text=SOURCE_WITH_DIGITS, duration_s=30)
        # All narration must only contain digits present in source
        assert validate_no_invented_numbers(
            source_text=SOURCE_WITH_DIGITS, plan=plan
        ) is True
        # The digits themselves appear somewhere in the narration
        all_narr = "".join(seg.narration for seg in plan.segments)
        assert "365" in all_narr
        assert "24" in all_narr

    def test_no_invented_numbers_when_source_has_none(self):
        plan = plan_heartbeat5(source_text=SOURCE_TEXT, duration_s=60)
        # Source has no digits -> narration must have no digits either
        for seg in plan.segments:
            digits = re.findall(r"\d+(?:\.\d+)?%?", seg.narration)
            assert digits == [], (
                f"segment {seg.clip_index} invented digits {digits}"
            )

    def test_validator_raises_on_invented_number(self):
        plan = plan_heartbeat5(source_text=SOURCE_TEXT, duration_s=30)
        # Mutate a narration to inject a fake number
        plan.segments[1].narration = "这个现象有42个原因。"
        with pytest.raises(FactualError):
            validate_no_invented_numbers(
                source_text=SOURCE_TEXT, plan=plan
            )

    def test_no_invented_quotes_or_names(self):
        plan = plan_heartbeat5(source_text=SOURCE_TEXT, duration_s=30)
        all_narr = "".join(seg.narration for seg in plan.segments)
        # Source has no quotation marks; output must not invent any
        assert '"' not in all_narr
        assert '"' not in all_narr
        # Source has no English proper names; output must not invent any
        assert not re.search(r"\b[A-Z][a-z]+\b", all_narr)


class TestContinuityHandoff:
    """Segment i's ending frame == segment i+1's opening frame."""

    @pytest.mark.parametrize("duration", [15, 30, 60, 180])
    def test_end_state_matches_next_start_state(self, duration):
        plan = plan_heartbeat5(source_text=SOURCE_TEXT, duration_s=duration)
        for i in range(1, len(plan.segments)):
            prev = plan.segments[i - 1]
            cur = plan.segments[i]
            assert cur.visual_state_start == prev.visual_state_end, (
                f"Continuity broken between clip {i-1} and clip {i}: "
                f"{prev.visual_state_end!r} != {cur.visual_state_start!r}"
            )

    def test_continuity_states_nonempty(self):
        plan = plan_heartbeat5(source_text=SOURCE_TEXT, duration_s=60)
        for seg in plan.segments:
            assert seg.visual_state_start.strip()
            assert seg.visual_state_end.strip()
        # The first clip must state its opening frame explicitly
        assert "white background" in plan.segments[0].visual_state_start


class TestPlanSerialization:
    def test_to_dict_roundtrip(self):
        plan = plan_heartbeat5(source_text=SOURCE_TEXT, duration_s=30)
        d = plan.to_dict()
        assert d["clip_count"] == 3
        assert len(d["segments"]) == 3
        assert d["hook_timing"] is not None
        assert d["hook_timing"]["hook_start_s"] == 2.0
        for seg in d["segments"]:
            assert set(seg["beats"].keys()) == {"0-3s", "3-7s", "7-10s"}
            assert "visual_state_start" in seg
            assert "visual_state_end" in seg


class TestEdgeCases:
    def test_invalid_duration_raises(self):
        with pytest.raises(ValueError):
            plan_heartbeat5(source_text=SOURCE_TEXT, duration_s=0)
        with pytest.raises(ValueError):
            plan_heartbeat5(source_text=SOURCE_TEXT, duration_s=-5)

    def test_empty_source_uses_first_sentence(self):
        plan = plan_heartbeat5(source_text="", duration_s=10)
        assert plan.clip_count == 1
        # Falls back to a single empty narration, but structure intact
        assert len(plan.segments) == 1

    def test_single_sentence_source(self):
        plan = plan_heartbeat5(
            source_text="猫推杯子是因为好奇。", duration_s=30
        )
        assert plan.clip_count == 3
        # Hook clip gets the only sentence
        assert plan.segments[0].narration == "猫推杯子是因为好奇。"
