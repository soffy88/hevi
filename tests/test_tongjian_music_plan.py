"""L7 音乐与音效 + G7 校验门测试。真实曲库(assets/audio 下的占位素材),
不 mock BGMLibrary——纯文件系统操作,足够快也足够真实。"""

from __future__ import annotations

from pathlib import Path

import pytest

from hevi.audio.bgm_library import BGMLibrary
from hevi.tongjian.music_plan import (
    _act_time_ranges,
    _map_mood_to_dir,
    _match_sfx_name,
    build_music_plan,
    gate_music_plan,
    generate_music_plan,
)
from hevi.tongjian.schemas import (
    Act,
    AudioSegment,
    Constitution,
    Shot,
    ShotList,
    Timeline,
    TimelineGap,
)


def _make_constitution(
    acts: list[dict] | None = None, bgm_mood_arc: list[str] | None = None
) -> Constitution:
    if acts is None:
        acts = [
            {"act": 1, "title": "索地", "events": ["E001"], "emotion_curve": "压抑,肃杀"},
            {"act": 2, "title": "围城", "events": ["E002"], "emotion_curve": "紧张,攀升"},
        ]
    return Constitution(
        act_structure=[Act(**a) for a in acts],
        bgm_mood_arc=bgm_mood_arc or [],
    )


def _make_timeline_two_acts() -> Timeline:
    return Timeline(
        audio_segments=[
            AudioSegment(line_id="LN001", duration_ms=3000, t_start_ms=0, t_end_ms=3000),
            AudioSegment(line_id="LN002", duration_ms=2000, t_start_ms=3000, t_end_ms=5000),
            AudioSegment(line_id="LN003", duration_ms=2000, t_start_ms=6500, t_end_ms=8500),
        ],
        total_duration_ms=8500,
        gaps=[TimelineGap(after_line="LN002", duration_ms=1500, purpose="act_transition")],
    )


# ── 关键词映射 ────────────────────────────────────────────────────────────


class TestMapMoodToDir:
    def test_known_keywords(self):
        assert _map_mood_to_dir("压抑,肃杀") == "tense"
        assert _map_mood_to_dir("激昂攀升") == "epic"
        assert _map_mood_to_dir("余韵悠长") == "warm"
        assert _map_mood_to_dir("悬疑诡谲") == "mystery"

    def test_first_matching_keyword_wins_when_mixed(self):
        # "紧张"(tense)在映射表里排在"攀升"(epic)前面 —— 混合情绪词没有优先级
        # 系统,谁先命中算谁,这是当前设计的已知行为而非 bug。
        assert _map_mood_to_dir("紧张,攀升") == "tense"

    def test_unknown_keyword_falls_back_to_default(self):
        assert _map_mood_to_dir("完全没见过的情绪词") == "warm"


class TestMatchSfxName:
    def test_matches_known_keyword(self):
        assert _match_sfx_name("战鼓擂动,烟尘四起") == "impact"
        assert _match_sfx_name("钟声悠远") == "ding"
        assert _match_sfx_name("竹简缓缓展开") == "whoosh"

    def test_no_match_returns_none(self):
        assert _match_sfx_name("远景,宫殿大堂") is None


# ── 幕时间范围反推 ────────────────────────────────────────────────────────


class TestActTimeRanges:
    def test_two_acts_split_at_gap(self):
        # 幕2 从 5000ms(幕1最后一句结束)开始,把 1500ms 的转场静音包含在开头——
        # 让音乐交叉淡入淡出正好覆盖这段叙事停顿,而不是先出现一段死寂。
        timeline = _make_timeline_two_acts()
        ranges = _act_time_ranges(timeline, 2)
        assert ranges == [(0, 5000), (5000, 8500)]

    def test_single_act_spans_whole_timeline(self):
        timeline = _make_timeline_two_acts()
        ranges = _act_time_ranges(timeline, 1)
        assert ranges == [(0, 8500)]

    def test_zero_acts_returns_empty(self):
        assert _act_time_ranges(_make_timeline_two_acts(), 0) == []

    def test_no_audio_segments_returns_zero_ranges(self):
        assert _act_time_ranges(Timeline(), 2) == [(0, 0), (0, 0)]


# ── generate_music_plan ───────────────────────────────────────────────────


class TestGenerateMusicPlan:
    def test_one_cue_per_act_with_real_bgm_path(self):
        constitution = _make_constitution()
        timeline = _make_timeline_two_acts()
        plan = generate_music_plan(ShotList(), timeline, constitution)

        assert len(plan.cues) == 2
        assert plan.cues[0].act == 1
        assert plan.cues[0].t_start_ms == 0
        assert plan.cues[0].t_end_ms == 5000
        assert Path(plan.cues[0].bgm_path).exists()
        assert plan.cues[1].t_start_ms == 5000

    def test_bgm_mood_arc_supplements_emotion_curve(self):
        # emotion_curve 本身查不到关键词,但同位置 bgm_mood_arc 能查到 → 应采用
        constitution = _make_constitution(
            acts=[{"act": 1, "title": "x", "events": [], "emotion_curve": "未知情绪词"}],
            bgm_mood_arc=["低沉肃杀的弦乐"],
        )
        plan = generate_music_plan(ShotList(), Timeline(total_duration_ms=1000), constitution)
        assert "tense" in plan.cues[0].bgm_path

    def test_sfx_cues_matched_from_visual_prompt(self):
        shotlist = ShotList(
            shots=[
                Shot(
                    shot_id="SH001",
                    scene_id="E001",
                    t_start_ms=0,
                    t_end_ms=1000,
                    visual_prompt="战鼓擂动",
                ),
                Shot(
                    shot_id="SH002",
                    scene_id="E001",
                    t_start_ms=1000,
                    t_end_ms=2000,
                    visual_prompt="远景宫殿",
                ),
            ]
        )
        plan = generate_music_plan(shotlist, Timeline(total_duration_ms=2000), _make_constitution())

        assert len(plan.sfx) == 1
        assert plan.sfx[0].shot_id == "SH001"
        assert plan.sfx[0].sfx_name == "impact"
        assert Path(plan.sfx[0].sfx_path).exists()

    def test_missing_bgm_mood_dir_yields_empty_path(self, tmp_path):
        empty_lib = BGMLibrary(root_dir=tmp_path)
        constitution = _make_constitution()
        plan = generate_music_plan(
            ShotList(),
            Timeline(total_duration_ms=1000),
            constitution,
            bgm_lib=empty_lib,
        )
        assert all(c.bgm_path == "" for c in plan.cues)


# ── gate_music_plan / build_music_plan ────────────────────────────────────


class TestGateMusicPlan:
    @pytest.mark.asyncio
    async def test_passes_with_real_bgm(self):
        constitution = _make_constitution()
        plan, result = await build_music_plan(ShotList(), _make_timeline_two_acts(), constitution)
        assert result.passed
        assert result.coverage == 1.0

    @pytest.mark.asyncio
    async def test_fails_when_act_has_no_bgm(self, tmp_path):
        empty_lib = BGMLibrary(root_dir=tmp_path)
        constitution = _make_constitution()
        plan = generate_music_plan(
            ShotList(),
            _make_timeline_two_acts(),
            constitution,
            bgm_lib=empty_lib,
        )
        result = await gate_music_plan(plan, constitution)
        assert not result.passed
        assert any("未匹配到任何 BGM" in e for e in result.errors)
        assert result.coverage == 0.0

    @pytest.mark.asyncio
    async def test_warns_when_no_sfx_matched(self):
        constitution = _make_constitution()
        # 没有 shot 提供关键词 → 无 SFX
        plan = generate_music_plan(ShotList(), _make_timeline_two_acts(), constitution)
        result = await gate_music_plan(plan, constitution)
        assert result.passed
        assert any("没有匹配到任何音效" in w for w in result.warnings)
