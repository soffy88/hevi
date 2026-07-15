"""主线情绪配音(SPEC-002 B1)台词逐行情绪标注测试。"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from hevi.prompt.emotion_inference import infer_line_emotions


def _llm(content: str) -> AsyncMock:
    return AsyncMock(return_value={"content": content})


async def test_empty_lines_returns_empty():
    emotions = await infer_line_emotions([], llm=AsyncMock())
    assert emotions == []


async def test_no_llm_call_when_lines_empty():
    llm = AsyncMock()
    await infer_line_emotions([], llm=llm)
    llm.assert_not_called()


async def test_matching_length_returns_aligned_emotions():
    llm = _llm('{"emotions": ["倨傲", "惊惧", "平静"]}')
    emotions = await infer_line_emotions(["要地予我", "城破在即", "三家终于罢兵"], llm=llm)
    assert emotions == ["倨傲", "惊惧", "平静"]


async def test_length_mismatch_falls_back_to_neutral():
    """LLM 漏标/多标(数组长度跟台词行数对不上)→ 整批退化为空字符串,不能错位对应。"""
    llm = _llm('{"emotions": ["倨傲"]}')
    emotions = await infer_line_emotions(["行1", "行2", "行3"], llm=llm)
    assert emotions == ["", "", ""]


async def test_malformed_llm_response_falls_back_to_neutral():
    llm = _llm("not json at all")
    emotions = await infer_line_emotions(["行1", "行2"], llm=llm)
    assert emotions == ["", ""]


async def test_llm_exception_falls_back_to_neutral():
    llm = AsyncMock(side_effect=RuntimeError("llm down"))
    emotions = await infer_line_emotions(["行1", "行2"], llm=llm)
    assert emotions == ["", ""]


async def test_no_llm_provided_degrades_gracefully_when_registry_has_none():
    with patch("obase.provider_registry.ProviderRegistry.get") as mock_get:
        mock_get.return_value.llm.side_effect = RuntimeError("no llm registered")
        emotions = await infer_line_emotions(["行1", "行2"])
    assert emotions == ["", ""]


async def test_prefers_qwen_cloud_over_default():
    """结构化 JSON 输出优先用 qwen_cloud(本地 ollama 对这类任务不可靠)。"""
    seen_names: list[str] = []

    class _FakeRegistry:
        def llm(self, name: str):
            seen_names.append(name)
            if name == "qwen_cloud":
                return _llm('{"emotions": ["平静"]}')
            raise AssertionError("不该退回 default,qwen_cloud 应该可用")

    with patch("obase.provider_registry.ProviderRegistry.get", return_value=_FakeRegistry()):
        emotions = await infer_line_emotions(["行1"])
    assert emotions == ["平静"]
    assert seen_names == ["qwen_cloud"]


async def test_falls_back_to_default_when_qwen_cloud_unregistered():
    class _FakeRegistry:
        def llm(self, name: str):
            if name == "qwen_cloud":
                raise RuntimeError("qwen_cloud not registered")
            return _llm('{"emotions": ["平静"]}')

    with patch("obase.provider_registry.ProviderRegistry.get", return_value=_FakeRegistry()):
        emotions = await infer_line_emotions(["行1"])
    assert emotions == ["平静"]
