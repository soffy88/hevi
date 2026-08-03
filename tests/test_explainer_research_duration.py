"""精准目标时长(target_duration)与动态字数/Cue 约束。

覆盖:
- ExplainerResearchRequest.target_duration 校验(范围档 / 单个分钟数 / 非法值)
- _duration_bounds / _duration_constraints 按约 250 字/分钟动态计算字数与 Cue 数
- _build_research_prompt 把动态约束追加到基础 JSON 契约末尾
- research_and_generate 把 target_duration 透传给注入的脚本生成器
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hevi.explainer.contracts import ExplainerResearchRequest
from hevi.explainer.research import (
    _build_research_prompt,
    _duration_bounds,
    _duration_constraints,
    research_and_generate,
)


def test_target_duration_defaults_to_1_3() -> None:
    request = ExplainerResearchRequest(topic_or_url="测试")
    assert request.target_duration == "1-3"


def test_target_duration_accepts_range_and_single_number() -> None:
    request = ExplainerResearchRequest(topic_or_url="x", target_duration="3-6")
    assert request.target_duration == "3-6"
    assert (
        ExplainerResearchRequest(topic_or_url="x", target_duration=" 10-15 ").target_duration
        == "10-15"
    )
    assert ExplainerResearchRequest(topic_or_url="x", target_duration="8").target_duration == "8"
    assert ExplainerResearchRequest(topic_or_url="x", target_duration="20").target_duration == "20"


@pytest.mark.parametrize(
    "value",
    ["", "abc", "3-x", "5-2", "0", "1-3-5", "-3", "3-", "61"],
)
def test_target_duration_rejects_invalid_values(value: str) -> None:
    with pytest.raises(ValidationError):
        ExplainerResearchRequest(topic_or_url="x", target_duration=value)


def test_duration_bounds_parses_range_and_number() -> None:
    assert _duration_bounds("1-3") == (1.0, 3.0)
    assert _duration_bounds("8") == (8.0, 8.0)
    assert _duration_bounds(" 6-10 ") == (6.0, 10.0)


def test_duration_constraints_compute_word_and_cue_bounds() -> None:
    constraints = _duration_constraints("1-3")
    assert "1-3 分钟" in constraints
    assert "250 到 750 字" in constraints
    assert "至少需要 2 个独立的视觉 Cue" in constraints

    long_constraints = _duration_constraints("10-15")
    assert "2500 到 3750 字" in long_constraints
    assert "至少需要 20 个独立的视觉 Cue" in long_constraints

    single = _duration_constraints("8")
    assert "2000 到 2000 字" in single
    assert "至少需要 16 个独立的视觉 Cue" in single


def test_build_research_prompt_appends_dynamic_constraints() -> None:
    prompt = _build_research_prompt("测试主题", "6-10")
    assert "选题或材料：测试主题" in prompt
    assert "【强制字数与时长要求】" in prompt
    assert "6-10 分钟" in prompt
    assert "1500 到 2500 字" in prompt
    assert "至少需要 12 个独立的视觉 Cue" in prompt


class _Researcher:
    async def research(self, _topic: str) -> dict:
        return {"facts": []}


class _CapturingGenerator:
    def __init__(self) -> None:
        self.seen: dict[str, object] = {}

    async def generate(self, _topic: str, research: dict) -> dict:
        self.seen.update(research)
        return {
            "facts": [{"claim": "事实", "confidence": 0.9}],
            "hooks": [{"hook_id": "H1", "text": "钩子"}],
            "scripts": [
                {
                    "id": "A",
                    "title": "版本 A",
                    "viewpoint": "数据",
                    "hook": "钩子",
                    "cues": [
                        {
                            "time_range": "00:00-00:05",
                            "visual_type": "voiceover",
                            "text": "旁白",
                        }
                    ],
                }
            ],
        }


@pytest.mark.asyncio
async def test_research_and_generate_injects_target_duration_to_generator() -> None:
    generator = _CapturingGenerator()
    result = await research_and_generate(
        ExplainerResearchRequest(topic_or_url="x", target_duration="6-10"),
        researcher=_Researcher(),
        script_generator=generator,
    )
    assert generator.seen.get("target_duration") == "6-10"
    assert result.scripts[0].cues[0].text == "旁白"
