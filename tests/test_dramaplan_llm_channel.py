"""DRAMAPLAN LLM 通道解析测试（不调网络）。"""

from __future__ import annotations

import pytest

from hevi.providers import free_llm
from hevi.providers.free_llm import (
    FREE_CHANNEL_ORDER,
    available_channels,
    build_channel_caller,
    probe_channel,
    resolve_free_llm,
)


def _all_none() -> dict:
    return {name: (lambda: None) for name in FREE_CHANNEL_ORDER}


def test_resolve_explicit_channel_unavailable_raises(monkeypatch):
    monkeypatch.setattr(free_llm, "_BUILDERS", _all_none())
    with pytest.raises(ValueError, match="不可用"):
        resolve_free_llm("nim")


def test_resolve_auto_picks_first_available(monkeypatch):
    builders = _all_none()
    builders["ollama"] = lambda: "OLLAMA_CALLER"
    monkeypatch.setattr(free_llm, "_BUILDERS", builders)
    name, caller = resolve_free_llm("auto")
    assert name == "ollama"
    assert caller == "OLLAMA_CALLER"


def test_resolve_auto_raises_when_nothing_available(monkeypatch):
    monkeypatch.setattr(free_llm, "_BUILDERS", _all_none())
    with pytest.raises(RuntimeError):
        resolve_free_llm("auto")


def test_available_channels_and_build(monkeypatch):
    builders = _all_none()
    builders["nim"] = lambda: "NIM"
    monkeypatch.setattr(free_llm, "_BUILDERS", builders)
    assert available_channels() == ["nim"]
    assert build_channel_caller("nim") == "NIM"
    assert build_channel_caller("unknown") is None


def test_channel_order_puts_nim_first_and_never_paid():
    # 免费通道优先序：NIM 实测最稳，排第一；不含任何付费端点名。
    assert FREE_CHANNEL_ORDER[0] == "nim"
    assert "qwen_cloud" not in FREE_CHANNEL_ORDER
    assert FREE_CHANNEL_ORDER[-1] == "default"


@pytest.mark.asyncio
async def test_probe_channel_not_configured(monkeypatch):
    monkeypatch.setattr(free_llm, "_BUILDERS", _all_none())
    result = await probe_channel("nim")
    assert result["available"] is False
    assert result["reason"] == "not_configured"


def test_resolve_planning_llm_uses_free_resolver(monkeypatch):
    from hevi.shortdrama import llm_channel

    monkeypatch.setattr(free_llm, "resolve_free_llm", lambda channel=None: ("fake", "CALLER"))
    name, caller = llm_channel.resolve_planning_llm("nim")
    assert (name, caller) == ("fake", "CALLER")
