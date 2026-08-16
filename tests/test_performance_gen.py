"""INC-002 生成器测试:LLM → performance_track,含时间窗自动归一化 + tier 门控 + inert。零真网络。"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

from hevi.director.performance_gen import (
    enrich_shot_list_with_performance,
    generate_performance_track,
)
from hevi.director.performance_track import lint_performance_track
from hevi.director.pipeline_schemas import ShotListItem


def _llm(content: str) -> AsyncMock:
    return AsyncMock(return_value={"content": content})


# 故意给"有缝隙 + 末段不到时长"的时间窗,验证归一化把它钉成无缝。
_GAPPED = json.dumps(
    {
        "total_duration_s": 12.0,
        "phases": [
            {
                "order": 1,
                "t_start_s": 0,
                "t_end_s": 3,
                "label": "克制",
                "eyeline_track": {"state": "locked", "direction": "center"},
                "emotional_state": {"primary": "强忍", "intensity": 0.4},
            },
            {
                "order": 2,
                "t_start_s": 4,
                "t_end_s": 7,
                "label": "断裂",  # 3→4 有缝隙
                "eyeline_track": {"state": "breaking", "direction": "down"},
                "emotional_state": {"primary": "崩溃", "intensity": 0.8},
            },
            {
                "order": 3,
                "t_start_s": 7,
                "t_end_s": 9,
                "label": "回避",  # 末段 9 ≠ 12
                "eyeline_track": {"state": "averted", "direction": "down_left"},
                "emotional_state": {"primary": "羞愤", "intensity": 0.9},
            },
        ],
    },
    ensure_ascii=False,
)


async def test_generate_normalizes_time_windows_p1_clean():
    """LLM 给有缝隙的时间窗 → 归一化成无缝,P1 恒过;相对节奏保住。"""
    shot = ShotListItem(shot_id="SH001", scene_no=1, duration_s=12.0, visual_prompt="特写")
    track = await generate_performance_track(shot=shot, tier="L1", llm=_llm(_GAPPED))
    assert track is not None and len(track.phases) == 3
    assert track.total_duration_s == 12.0
    assert track.phases[0].t_start_s == 0.0
    # 段段相接、末段到 12
    for a, b in zip(track.phases, track.phases[1:], strict=False):
        assert a.t_end_s == b.t_start_s
    assert track.phases[-1].t_end_s == 12.0
    assert [f for f in lint_performance_track(track) if f.rule == "P1"] == []


async def test_l0_tier_generates_nothing():
    """L0(默认档)→ 不生成(None,inert)。"""
    shot = ShotListItem(shot_id="SH001", scene_no=1, duration_s=5.0)
    assert await generate_performance_track(shot=shot, tier="L0", llm=_llm(_GAPPED)) is None


async def test_malformed_llm_output_returns_none():
    """LLM 输出无 phases → None,不炸(走 action_beats 老路)。"""
    shot = ShotListItem(shot_id="SH001", scene_no=1, duration_s=5.0)
    assert await generate_performance_track(shot=shot, tier="L1", llm=_llm("no json here")) is None
    assert (
        await generate_performance_track(shot=shot, tier="L1", llm=_llm('{"phases": []}')) is None
    )


async def test_enrich_writes_back_and_l0_inert():
    """enrich 就地写回 performance_track;L0 → 保持 None(inert)。"""
    shots = [
        ShotListItem(shot_id="SH001", scene_no=1, duration_s=12.0, visual_prompt="a"),
        ShotListItem(shot_id="SH002", scene_no=1, duration_s=12.0, visual_prompt="b"),
    ]
    await enrich_shot_list_with_performance(shots, tier="L1", llm=_llm(_GAPPED))
    assert all(
        s.performance_track is not None and len(s.performance_track.phases) == 3 for s in shots
    )

    inert = [ShotListItem(shot_id="SH003", scene_no=1, duration_s=5.0)]
    await enrich_shot_list_with_performance(inert, tier="L0", llm=_llm(_GAPPED))
    assert inert[0].performance_track is None
