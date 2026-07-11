"""Step 3 派发层测试:SeasonPlan → Series + 逐集 VideoTask。
用 fake series_service(记录调用)隔离验证派发逻辑,不触真实 DB/生成管线。
"""

from __future__ import annotations

import pytest

from hevi.season_planner import dispatch_season, episode_brief
from hevi.season_planner.planner import _coerce_season_plan
from hevi.storygraph.schemas import (
    StoryCharacter,
    StoryEvent,
    StoryGraph,
    StoryLocation,
    StoryMeta,
    StoryQuote,
)


def _story() -> StoryGraph:
    return StoryGraph(
        meta=StoryMeta(source="都市短篇·翻身", char_count=2000),
        characters=[
            StoryCharacter(
                char_id="C001", name="林夏", description="冷峻干练的白领", role="protagonist"
            ),
            StoryCharacter(
                char_id="C002", name="陈默", description="沉默的发小", role="supporting"
            ),
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
            StoryLocation(location_id="L001", name="公司", events=["E001", "E002", "E005"]),
            StoryLocation(location_id="L002", name="咖啡馆", events=["E003", "E006"]),
        ],
        quotes=[
            StoryQuote(
                quote_id="Q001",
                speaker="C003",
                original="你被开除了。",
                modern="你被开除了。",
                event_id="E002",
                emotion="傲慢",
            ),
        ],
    )


_SPLIT = {
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


def _plan():
    return _coerce_season_plan(_SPLIT, _story(), target_episodes=3)


class _FakeSeriesService:
    """记录 create_series / create_episode 调用的假实现。"""

    def __init__(self) -> None:
        self.created_series: dict | None = None
        self.episode_calls: list[dict] = []

    async def create_series(self, **kwargs):
        self.created_series = kwargs
        return {"id": "series-uuid-123"}

    async def create_episode(self, series_id, *, topic, task_service=None, overrides=None):
        idx = len(self.episode_calls)
        self.episode_calls.append({"series_id": series_id, "topic": topic, "overrides": overrides})
        return {"id": f"task-{idx}", "series_id": series_id, "episode_index": idx}


# ── episode_brief 降维 ───────────────────────────────────────────────────


def test_episode_brief_synthesizes_narrative_text():
    plan = _plan()
    brief = episode_brief(plan.episodes[0], _story())
    assert "第1集 · 谷底" in brief
    assert "压抑→爆发" in brief
    assert "林夏" in brief and "冷峻干练的白领" in brief  # 角色描述带入(喂 Subject/Director)
    assert "林夏被裁员" in brief and "林夏与赵总当众冲突" in brief  # 事件按序
    assert "[冲突]" in brief  # 节拍标注
    assert "赵总:「你被开除了。」" in brief  # 本集台词沿用原文对白


def test_episode_brief_only_includes_own_episode_quotes():
    plan = _plan()
    # E002 的台词只应出现在第 1 集(含 E002),不应出现在第 2/3 集
    brief2 = episode_brief(plan.episodes[1], _story())
    assert "你被开除了" not in brief2


# ── dispatch_season 端到端 ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dispatch_season_creates_series_and_all_episodes():
    svc = _FakeSeriesService()
    plan = _plan()
    result = await dispatch_season(
        plan,
        _story(),
        series_service=svc,
        subject_id_map={"C001": "subj-linxia", "C002": "subj-chenmo"},
        style_pack_id="pack-1",
    )

    # 建了一个 Series,角色组来自 subject_id_map,StylePack 锁定
    assert svc.created_series["name"] == "都市短篇·翻身"
    assert svc.created_series["subject_ids"] == ["subj-linxia", "subj-chenmo"]
    assert svc.created_series["style_pack_id"] == "pack-1"

    # 逐集建任务:3 集,topic 是各集简报
    assert len(svc.episode_calls) == 3
    assert all(c["series_id"] == "series-uuid-123" for c in svc.episode_calls)
    assert "谷底" in svc.episode_calls[0]["topic"]
    assert "翻身" in svc.episode_calls[2]["topic"]

    # 返回结构 + season=series 回填
    assert result["series_id"] == "series-uuid-123"
    assert len(result["episodes"]) == 3
    assert plan.season_id == "series-uuid-123"

    # 幕级结构塞进 config_json["episode_plan"](经 overrides round-trip),供看板幕级视图
    ov0 = svc.episode_calls[0]["overrides"]
    assert ov0["episode_plan"]["beats"] == ["铺垫", "冲突"]
    assert ov0["episode_plan"]["event_ids"] == ["E001", "E002"]


@pytest.mark.asyncio
async def test_dispatch_season_without_subjects_leaves_group_empty():
    """无 subject 绑定(骨架/dry-run):Series 角色组为空,Director 走 t2v。"""
    svc = _FakeSeriesService()
    result = await dispatch_season(_plan(), _story(), series_service=svc)
    assert svc.created_series["subject_ids"] == []
    assert len(result["episodes"]) == 3
