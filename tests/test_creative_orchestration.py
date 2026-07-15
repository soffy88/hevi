"""创意工具动态编排测试(HEVI 路线图 Phase4 #45)。"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from hevi.director.creative_orchestration import (
    CREATIVE_TOOL_IDS,
    apply_three_view_if_recommended,
    recommend_creative_tools,
)


def _llm(content: str) -> AsyncMock:
    return AsyncMock(return_value={"content": content})


async def test_empty_topic_returns_empty_list():
    assert await recommend_creative_tools("", llm=AsyncMock()) == []


async def test_no_recommendation_for_generic_topic():
    llm = _llm("[]")
    assert await recommend_creative_tools("一段风景延时摄影", llm=llm) == []


async def test_recommends_three_view_for_character_topic():
    llm = _llm('[{"tool_id": "three-view", "reason": "题材需要角色多视角一致性"}]')
    recs = await recommend_creative_tools("一个骑士角色需要正侧背三视图保持一致", llm=llm)
    assert recs == [{"tool_id": "three-view", "reason": "题材需要角色多视角一致性"}]


async def test_unknown_tool_id_filtered_out():
    llm = _llm('[{"tool_id": "not-a-real-tool", "reason": "x"}]')
    assert await recommend_creative_tools("x", llm=llm) == []


async def test_malformed_response_returns_empty_list():
    assert await recommend_creative_tools("x", llm=_llm("not json")) == []


async def test_llm_exception_returns_empty_list():
    llm = AsyncMock(side_effect=RuntimeError("llm down"))
    assert await recommend_creative_tools("x", llm=llm) == []


async def test_non_list_response_returns_empty_list():
    assert await recommend_creative_tools("x", llm=_llm('{"tool_id": "three-view"}')) == []


def test_all_nine_tool_ids_present():
    assert len(CREATIVE_TOOL_IDS) == 9


# ── three-view 自动调用(唯一参数可干净推导的工具)────────────────────────────


async def test_apply_three_view_skips_without_assist_service():
    recs = [{"tool_id": "three-view", "reason": "x"}]
    assert await apply_three_view_if_recommended(recs, topic="t", style="s") is None


async def test_apply_three_view_skips_when_not_recommended():
    assist = AsyncMock()
    result = await apply_three_view_if_recommended(
        [{"tool_id": "storyboard", "reason": "x"}], topic="t", style="s", assist_service=assist
    )
    assert result is None
    assist.gen_three_view.assert_not_called()


async def test_apply_three_view_invokes_and_returns_result():
    from types import SimpleNamespace

    assist = AsyncMock()
    assist.gen_three_view.return_value = SimpleNamespace(
        model_dump=lambda: {
            "front_prompt": "a knight facing forward",
            "side_prompt": "",
            "back_prompt": "",
        }
    )
    recs = [{"tool_id": "three-view", "reason": "needs consistency"}]
    result = await apply_three_view_if_recommended(
        recs, topic="a knight", style="cinematic", assist_service=assist
    )
    assert result["front_prompt"] == "a knight facing forward"
    assist.gen_three_view.assert_awaited_once_with(
        character_description="a knight", style="cinematic"
    )


async def test_apply_three_view_failure_returns_none():
    assist = AsyncMock()
    assist.gen_three_view.side_effect = RuntimeError("service down")
    recs = [{"tool_id": "three-view", "reason": "x"}]
    result = await apply_three_view_if_recommended(
        recs, topic="t", style="s", assist_service=assist
    )
    assert result is None
