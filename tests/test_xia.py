"""Xia 对话式制片助理测试(对标 DramaClaw Xia)。

确定性意图路由 + 工具分发 + 会话上下文保持。纯逻辑(mock 工具/问答)。
"""

from __future__ import annotations

import pytest

from hevi.creative.xia import XiaAssistant, route_intent


def test_route_intent_keywords():
    assert route_intent("帮我生成三视图") == "three_view"
    assert route_intent("这个剧本分镜怎么出") == "storyboard"
    assert route_intent("后续剧情会怎样") == "story_predict"
    assert route_intent("给这个视频配情感配音") == "dub"
    assert route_intent("任务到哪一步了") == "progress"
    assert route_intent("今天天气怎么样") == "ask"  # 兜底


@pytest.mark.asyncio
async def test_chat_routes_to_tool():
    calls: list[str] = []

    async def fake_storyboard(params):
        calls.append("storyboard")
        return {"summary": "已生成 6 个分镜", "shots": ["a", "b"]}

    xia = XiaAssistant(tools={"storyboard": fake_storyboard})
    out = await xia.chat("帮我出分镜")
    assert out["intent"] == "storyboard"
    assert out["tool"] == "storyboard"
    assert "6 个分镜" in out["reply"]
    assert calls == ["storyboard"]


@pytest.mark.asyncio
async def test_chat_session_persistence():
    """同 session_id 多轮 → 上下文保持(消息累积)。"""
    xia = XiaAssistant()
    r1 = await xia.chat("帮我出分镜", session_id="s1")
    r2 = await xia.chat("再帮我查进度", session_id="s1")
    assert r1["session_id"] == r2["session_id"]
    session = xia.get_session("s1")
    assert len(session.messages) == 4  # 2 user + 2 assistant


@pytest.mark.asyncio
async def test_chat_tool_failure_graceful():
    async def boom(params):
        raise RuntimeError("显卡忙")

    xia = XiaAssistant(tools={"storyboard": boom})
    out = await xia.chat("帮我出分镜")
    assert "显卡忙" in out["reply"]  # 工具失败转自然语言,不崩


@pytest.mark.asyncio
async def test_chat_fallback_ask():
    async def fake_fallback(text, session):
        return f"制片问答:{text}"

    xia = XiaAssistant(fallback=fake_fallback)
    out = await xia.chat("什么是蒙太奇")  # 不含任何工具关键词 → ask
    assert out["intent"] == "ask"
    assert "制片问答" in out["reply"]
