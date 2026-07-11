"""剧集规划器测试:LLM 切集 + 确定性组装 + G_SEASON 自我批判门。
门用直接构造的 SeasonPlan 单测(隔离);build 主入口用 mock LLM 测端到端。
约定对齐 tests/test_tongjian_constitution.py。
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from hevi.season_planner import (
    EpisodePlan,
    SeasonPlan,
    build_season_plan,
    gate_season_plan,
    generate_season_plan,
)
from hevi.season_planner.planner import _build_continuity
from hevi.storygraph.schemas import (
    StoryCharacter,
    StoryEvent,
    StoryGraph,
    StoryLocation,
    StoryMeta,
)


def _story() -> StoryGraph:
    """6 事件 / 3 角色 / 2 地点,意图切成 3 集,每集含一个冲突/转折/高潮。"""
    return StoryGraph(
        meta=StoryMeta(source="都市短篇·翻身", char_count=2000),
        characters=[
            StoryCharacter(char_id="C001", name="林夏", role="protagonist"),
            StoryCharacter(char_id="C002", name="陈默", role="supporting"),
            StoryCharacter(char_id="C003", name="赵总", role="antagonist"),
        ],
        events=[
            StoryEvent(
                event_id="E001",
                summary="林夏被裁员",
                actors=["C001"],
                beat_type="铺垫",
                dramatic_weight=2,
            ),
            StoryEvent(
                event_id="E002",
                summary="林夏与赵总当众冲突",
                actors=["C001", "C003"],
                beat_type="冲突",
                dramatic_weight=4,
            ),
            StoryEvent(
                event_id="E003",
                summary="陈默暗中相助转机",
                actors=["C001", "C002"],
                beat_type="转折",
                dramatic_weight=4,
            ),
            StoryEvent(
                event_id="E004",
                summary="过渡日常",
                actors=["C001"],
                beat_type="过场",
                dramatic_weight=2,
            ),
            StoryEvent(
                event_id="E005",
                summary="林夏反击赵总高潮对决",
                actors=["C001", "C003"],
                beat_type="高潮",
                dramatic_weight=5,
            ),
            StoryEvent(
                event_id="E006",
                summary="林夏与陈默和解收束",
                actors=["C001", "C002"],
                beat_type="收束",
                dramatic_weight=4,
            ),
        ],
        locations=[
            StoryLocation(
                location_id="L001", name="公司", type="职场", events=["E001", "E002", "E005"]
            ),
            StoryLocation(location_id="L002", name="咖啡馆", type="街景", events=["E003", "E006"]),
        ],
    )


# 一份合法的三集切分(每集正好两个事件,每集都含冲突/转折/高潮)。
_GOOD_SPLIT = {
    "episodes": [
        {
            "ep_number": 1,
            "title": "谷底",
            "event_ids": ["E001", "E002"],
            "target_emotion_arc": "压抑→爆发",
        },
        {
            "ep_number": 2,
            "title": "转机",
            "event_ids": ["E003", "E004"],
            "target_emotion_arc": "希望→蓄力",
        },
        {
            "ep_number": 3,
            "title": "翻身",
            "event_ids": ["E005", "E006"],
            "target_emotion_arc": "决战→释然",
        },
    ]
}


def _mock_llm(json_text: str) -> AsyncMock:
    llm = AsyncMock()
    llm.return_value = {"content": json_text}
    return llm


# ── build_season_plan 端到端 ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_build_season_plan_passes_and_assembles_deterministically():
    llm = _mock_llm(json.dumps(_GOOD_SPLIT, ensure_ascii=False))
    plan, result = await build_season_plan(_story(), target_episodes=3, llm=llm, n=1)

    assert result.passed is True
    assert result.errors == []
    assert len(plan.episodes) == 3

    ep1 = plan.episodes[0]
    assert ep1.event_ids == ["E001", "E002"]
    # 角色/场景/节拍由代码从 StoryGraph 派生,不信 LLM 自填
    assert ep1.characters_present == ["C001", "C003"]  # actors 并集,保序
    assert ep1.locations == ["公司"]
    assert ep1.beats == ["铺垫", "冲突"]

    # subject_refs = 全季角色组(subject_id 尚未回填)
    assert {s.char_id for s in plan.subject_refs} == {"C001", "C002", "C003"}
    assert all(s.subject_id is None for s in plan.subject_refs)

    # continuity:林夏(C001)三集全在场
    c001 = next(c for c in plan.continuity_constraints if c.char_id == "C001")
    assert c001.present_in_episodes == [1, 2, 3]


@pytest.mark.asyncio
async def test_generate_season_plan_degrades_on_llm_failure():
    llm = AsyncMock(side_effect=RuntimeError("network down"))
    plan = await generate_season_plan(_story(), target_episodes=3, llm=llm)
    assert plan.episodes == []
    assert plan.target_episodes == 3


# ── gate_season_plan 隔离单测(SPEC §3.4 自我批判)────────────────────────


def _plan_from_split(split: dict) -> SeasonPlan:
    from hevi.season_planner.planner import _coerce_season_plan

    return _coerce_season_plan(split, _story(), target_episodes=len(split["episodes"]))


def test_gate_passes_on_good_split():
    result = gate_season_plan(_plan_from_split(_GOOD_SPLIT), _story())
    assert result.passed is True
    assert result.coverage == 1.0


def test_gate_fails_on_missing_event_coverage():
    split = {
        "episodes": [
            {"ep_number": 1, "title": "a", "event_ids": ["E001", "E002"], "target_emotion_arc": ""},
            {"ep_number": 2, "title": "b", "event_ids": ["E003"], "target_emotion_arc": ""},
            {"ep_number": 3, "title": "c", "event_ids": ["E005"], "target_emotion_arc": ""},
        ]
    }  # 缺 E004, E006
    result = gate_season_plan(_plan_from_split(split), _story())
    assert result.passed is False
    assert any("遗漏" in e for e in result.errors)


def test_gate_fails_on_duplicate_event():
    split = {
        "episodes": [
            {"ep_number": 1, "title": "a", "event_ids": ["E001", "E002"], "target_emotion_arc": ""},
            {
                "ep_number": 2,
                "title": "b",
                "event_ids": ["E002", "E003", "E004"],
                "target_emotion_arc": "",
            },
            {"ep_number": 3, "title": "c", "event_ids": ["E005", "E006"], "target_emotion_arc": ""},
        ]
    }  # E002 重复
    result = gate_season_plan(_plan_from_split(split), _story())
    assert result.passed is False
    assert any("重复" in e for e in result.errors)


def test_gate_fails_on_episode_without_conflict():
    split = {
        "episodes": [
            {"ep_number": 1, "title": "a", "event_ids": ["E002"], "target_emotion_arc": ""},
            {
                "ep_number": 2,
                "title": "b",
                "event_ids": ["E001", "E004"],
                "target_emotion_arc": "",
            },  # 全是铺垫/过场
            {
                "ep_number": 3,
                "title": "c",
                "event_ids": ["E003", "E005", "E006"],
                "target_emotion_arc": "",
            },
        ]
    }
    result = gate_season_plan(_plan_from_split(split), _story())
    assert result.passed is False
    assert any("铺垫/过场" in e for e in result.errors)


def test_gate_fails_on_wrong_episode_count():
    plan = _plan_from_split(_GOOD_SPLIT)
    plan.target_episodes = 5  # 声称 5 集但只切了 3 集
    result = gate_season_plan(plan, _story())
    assert result.passed is False
    assert any("集数" in e for e in result.errors)


def test_gate_fails_on_character_discontinuity():
    # 手工构造:C002 第 1 集出场,消失到第 4 集才重现(gap=2 > _MAX_ABSENCE_GAP... 需 gap>2)
    story = _story()
    episodes = [
        EpisodePlan(ep_number=1, event_ids=["E001"], characters_present=["C001", "C002"]),
        EpisodePlan(ep_number=2, event_ids=["E002"], characters_present=["C001"]),
        EpisodePlan(ep_number=3, event_ids=["E004"], characters_present=["C001"]),
        EpisodePlan(ep_number=4, event_ids=["E003"], characters_present=["C001"]),
        EpisodePlan(ep_number=5, event_ids=["E005", "E006"], characters_present=["C001", "C002"]),
    ]  # C002 在第1集后消失 3 集(2,3,4)才于第5集重现
    plan = SeasonPlan(
        story_source=story.meta.source,
        target_episodes=5,
        episodes=episodes,
        continuity_constraints=_build_continuity(episodes, story),
    )
    result = gate_season_plan(plan, story)
    assert result.passed is False
    assert any("角色断裂" in e for e in result.errors)
