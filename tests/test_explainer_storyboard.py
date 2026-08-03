from __future__ import annotations

import json

import pytest

from hevi.explainer.storyboard import (
    StoryboardGenerationError,
    gate_storyboard,
    generate_storyboard,
)


def _draft() -> dict:
    return {
        "topic": "测试选题",
        "segments": [
            {
                "id": "hook", "sceneType": "hook", "narration": "钩子内容足够长",
                "keywords": ["钩子"],
                "props": {
                    "title": "测试", "subtitle": "提醒",
                    "items": [{"emoji": "💡", "label": "例子"}],
                },
            },
            {
                "id": "definition", "sceneType": "definition", "narration": "定义内容足够长",
                "keywords": ["定义"],
                "props": {
                    "question": "什么是测试？", "formulaHead": "测试", "formulaLines": ["= 定义"],
                    "splitLeft": {"emoji": "A", "title": "左侧", "sub": "说明"},
                    "splitRight": {"emoji": "B", "title": "右侧", "sub": "说明"},
                },
            },
            {
                "id": "examples", "sceneType": "cards", "narration": "案例内容足够长",
                "keywords": ["案例"],
                "props": {
                    "header": "案例",
                    "cards": [{"emoji": "📌", "title": "案例", "desc": "说明"}],
                },
            },
            {
                "id": "reason", "sceneType": "reason", "narration": "原因内容足够长",
                "keywords": ["原因"],
                "props": {
                    "question": "为什么？", "brainLine": "大脑原因", "bubbleText": "原来如此",
                    "leftLabel": {"title": "错误", "sub": "后果"},
                    "rightLabel": {"title": "正确", "sub": "收益"},
                },
            },
            {
                "id": "method", "sceneType": "method", "narration": "方法内容足够长",
                "keywords": ["方法"],
                "props": {
                    "header": "方法",
                    "points": [{"num": "1", "title": "做法", "sub": "说明"}],
                },
            },
            {
                "id": "outro", "sceneType": "outro", "narration": "结尾内容足够长",
                "keywords": ["结尾"],
                "props": {
                    "setupLine1": "过渡", "setupLine2": "过渡",
                    "quoteLine1": "金句", "quoteLine2": "金句",
                    "ctaText": "点赞关注", "byline": "下期见",
                },
            },
        ],
    }


class _LLM:
    def __init__(self, content: str):
        self.content = content

    async def __call__(self, **kwargs):
        return {"content": self.content}


class _SequenceLLM:
    def __init__(self, contents: list[str]):
        self.contents = iter(contents)

    async def __call__(self, **kwargs):
        return {"content": next(self.contents)}


@pytest.mark.asyncio
async def test_generate_storyboard_valid_qwen_draft_passes_gate():
    content = json.dumps(_draft(), ensure_ascii=False)
    storyboard = await generate_storyboard("测试选题", llm=_LLM(content))
    result = gate_storyboard(storyboard)
    assert [segment.scene_type for segment in storyboard.segments] == [
        "hook", "definition", "cards", "reason", "method", "outro",
    ]
    assert result.passed is True


@pytest.mark.asyncio
async def test_generate_storyboard_empty_response_is_e0_failure():
    with pytest.raises(StoryboardGenerationError, match="空正文"):
        await generate_storyboard("测试选题", llm=_LLM(""))


@pytest.mark.asyncio
async def test_generate_storyboard_invalid_json_is_e0_failure():
    with pytest.raises(StoryboardGenerationError, match="有效 JSON"):
        await generate_storyboard("测试选题", llm=_LLM("不是 JSON"))


@pytest.mark.asyncio
async def test_generate_storyboard_retries_invalid_first_attempt():
    content = json.dumps(_draft(), ensure_ascii=False)
    storyboard = await generate_storyboard("测试选题", llm=_SequenceLLM(["不是 JSON", content]))
    assert len(storyboard.segments) == 6


@pytest.mark.asyncio
async def test_generate_storyboard_tolerates_stringified_visual_config():
    """本地小模型把 visualConfig 整体序列化成字符串时,E0 不应校验失败重试。"""
    draft = _draft()
    for segment in draft["segments"]:
        segment["visualConfig"] = json.dumps(
            {"assetUrl": "/b.mp4", "chart_data": {"values": [1]}},
            ensure_ascii=False,
        )
    content = json.dumps(draft, ensure_ascii=False)
    storyboard = await generate_storyboard("测试选题", llm=_LLM(content))
    assert len(storyboard.segments) == 6
    config = storyboard.segments[0].visual_config
    assert isinstance(config, dict)
    assert config["assetUrl"] == "/b.mp4"
    assert config["chart_data"] == {"values": [1]}


@pytest.mark.asyncio
async def test_generate_storyboard_tolerates_stringified_chart_data():
    """visualConfig 是 dict、但 chart_data 字段是 JSON 字符串时,也要还原。"""
    draft = _draft()
    for segment in draft["segments"]:
        segment["visualConfig"] = {
            "chart_data": '{"type": "bar", "values": [1, 2]}',
        }
    content = json.dumps(draft, ensure_ascii=False)
    storyboard = await generate_storyboard("测试选题", llm=_LLM(content))
    assert storyboard.segments[0].visual_config["chart_data"] == {
        "type": "bar",
        "values": [1, 2],
    }
