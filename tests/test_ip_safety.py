"""IP 安全改写 pass 测试(HEVI 路线图 Phase2 #36)。"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from hevi.prompt.ip_safety import rewrite_for_ip_safety


def _llm(content: str) -> AsyncMock:
    return AsyncMock(return_value={"content": content})


async def test_empty_text_returns_unchanged():
    text, flagged = await rewrite_for_ip_safety("", llm=AsyncMock())
    assert text == ""
    assert flagged == []


async def test_no_llm_call_when_text_empty():
    llm = AsyncMock()
    await rewrite_for_ip_safety("   ", llm=llm)
    llm.assert_not_called()


async def test_unflagged_text_returned_unchanged():
    llm = _llm('{"flagged": [], "rewritten": "一个年轻人在雪地里散步"}')
    text, flagged = await rewrite_for_ip_safety("一个年轻人在雪地里散步", llm=llm)
    assert text == "一个年轻人在雪地里散步"
    assert flagged == []


async def test_flagged_text_gets_rewritten():
    llm = _llm('{"flagged": ["蜘蛛侠"], "rewritten": "一个戴面具的原创英雄在城市里荡绳摆动"}')
    text, flagged = await rewrite_for_ip_safety("蜘蛛侠在城市里荡绳摆动", llm=llm)
    assert text == "一个戴面具的原创英雄在城市里荡绳摆动"
    assert flagged == ["蜘蛛侠"]


async def test_malformed_llm_response_falls_back_to_original():
    llm = _llm("not json at all")
    text, flagged = await rewrite_for_ip_safety("原文不变", llm=llm)
    assert text == "原文不变"
    assert flagged == []


async def test_llm_exception_falls_back_to_original():
    llm = AsyncMock(side_effect=RuntimeError("llm down"))
    text, flagged = await rewrite_for_ip_safety("原文不变", llm=llm)
    assert text == "原文不变"
    assert flagged == []


async def test_flagged_without_rewritten_field_keeps_original_text():
    """LLM 标了 flagged 但没给 rewritten(响应不完整)—— 不能返回 None/空文本,
    宁可保留原文也不能让下游拿到坏数据。"""
    llm = _llm('{"flagged": ["某明星"], "rewritten": null}')
    text, flagged = await rewrite_for_ip_safety("某明星出镜", llm=llm)
    assert text == "某明星出镜"
    assert flagged == ["某明星"]


async def test_no_llm_provided_degrades_gracefully_when_registry_has_none():
    """不传 llm 时会去 ProviderRegistry 找默认 LLM;显式模拟"没注册"这个场景
    (而不是依赖测试机当时是否真的注册了本地 LLM——那样测试会变慢且不确定),
    应该优雅降级为原文返回,不是抛异常。"""
    with patch("obase.provider_registry.ProviderRegistry.get") as mock_get:
        mock_get.return_value.llm.side_effect = RuntimeError("no llm registered")
        text, flagged = await rewrite_for_ip_safety("任意文本")
    assert text == "任意文本"
    assert flagged == []
