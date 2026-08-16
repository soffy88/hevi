"""prompt_language:base SDXL 偏英文,sdxl_local_generate 漏斗把中文 prompt 自动译成英文。

已验证事实(G-S1 2026-07-16):中文人物 prompt("白胡子老道士")→ base SDXL 渲成通用少女,
英文正常。此处测漏斗翻译逻辑本身(不真跑 GPU/不真调云端 LLM)。
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from hevi.image import sdxl_local_service as svc


@pytest.fixture(autouse=True)
def _clear_cache():
    svc._EN_PROMPT_CACHE.clear()
    yield
    svc._EN_PROMPT_CACHE.clear()


def _fake_registry(content: str | Exception):
    """伪 ProviderRegistry.get():.llm('qwen_cloud') 返回一个同步 callable。"""
    reg = MagicMock()
    if isinstance(content, Exception):
        reg.llm.return_value = MagicMock(side_effect=content)
    else:
        reg.llm.return_value = MagicMock(return_value={"content": content})
    getter = MagicMock(return_value=reg)
    return getter, reg


def test_has_chinese():
    assert svc._has_chinese("白胡子老道士")
    assert svc._has_chinese("old 老 man")
    assert not svc._has_chinese("an old Taoist priest")
    assert not svc._has_chinese("")


@pytest.mark.asyncio
async def test_english_prompt_passes_through_untouched():
    """无中文 → 原样返回,根本不调 LLM(英文 prompt 零开销)。"""
    getter, reg = _fake_registry("should not be called")
    with patch("obase.provider_registry.ProviderRegistry.get", getter):
        out = await svc._ensure_english_prompt("an elderly Taoist priest, white beard")
    assert out == "an elderly Taoist priest, white beard"
    reg.llm.assert_not_called()


@pytest.mark.asyncio
async def test_chinese_prompt_translated_and_cached():
    """含中文 → 调 LLM 译成英文;同一 prompt 第二次走缓存,不再调 LLM。"""
    getter, reg = _fake_registry("an elderly Chinese Taoist priest with a long white beard")
    with patch("obase.provider_registry.ProviderRegistry.get", getter):
        out1 = await svc._ensure_english_prompt("白胡子老道士,灰道袍")
        out2 = await svc._ensure_english_prompt("白胡子老道士,灰道袍")  # 缓存命中
    assert "Taoist" in out1 and not svc._has_chinese(out1)
    assert out2 == out1
    assert reg.llm.call_count == 1  # 第二次没再调


@pytest.mark.asyncio
async def test_translation_failure_falls_back_to_original():
    """翻译失败(LLM 抛)→ 用原文,绝不阻断出图。"""
    getter, _ = _fake_registry(RuntimeError("qwen down"))
    with patch("obase.provider_registry.ProviderRegistry.get", getter):
        out = await svc._ensure_english_prompt("白胡子老道士")
    assert out == "白胡子老道士"  # 原样返回


@pytest.mark.asyncio
async def test_translation_that_still_has_chinese_is_rejected():
    """LLM 返回里还含中文(没真译)→ 不采用,回退原文(避免把坏结果缓存)。"""
    getter, _ = _fake_registry("老道士 an old priest")  # 混了中文 = 没译干净
    with patch("obase.provider_registry.ProviderRegistry.get", getter):
        out = await svc._ensure_english_prompt("白胡子老道士")
    assert out == "白胡子老道士"
    assert "白胡子老道士" not in svc._EN_PROMPT_CACHE  # 坏结果没进缓存
