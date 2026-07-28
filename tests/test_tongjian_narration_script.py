"""SPEC-005 §1.2/§2.2 讲解稿模板测试。"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from hevi.tongjian.narration_script import DIAGRAM_MARKER_RE, generate_narration_script
from hevi.tongjian.schemas import EventUnit, Segment


def _mock_llm(json_text: str) -> AsyncMock:
    llm = AsyncMock()
    llm.return_value = {"content": json_text}
    return llm


def _make_event_unit() -> EventUnit:
    return EventUnit(
        event_unit_id="EU001",
        source_ref="史记·商君列传",
        title="商鞅立木",
        era="战国·秦",
        year=-359,
        summary="商鞅立木南门,悬赏取信于民",
        segments=[
            Segment(type="narration", source_text="令既具，未布，恐民之不信，", order=0),
            Segment(type="drama", source_text="乃立三丈之木於國都市南門", order=1),
            Segment(type="narration", source_text="民怪之，莫敢徙。", order=2),
        ],
    )


@pytest.mark.asyncio
async def test_generate_narration_script_only_uses_narration_segments():
    draft = {
        "lines": [
            {
                "text": "秦孝公任用商鞅变法，新法拟定却迟迟未公布，商鞅担心百姓不信任新法。",
                "visual_type": "scene",
                "visual_hint": "咸阳城,新法竹简",
            },
            {
                "text": "百姓对朝廷的新政心存疑虑，没有人敢站出来响应。",
                "visual_type": "scene",
                "visual_hint": "南门围观百姓",
            },
        ]
    }
    llm = _mock_llm(json.dumps(draft, ensure_ascii=False))
    event_unit = _make_event_unit()

    script = await generate_narration_script(event_unit, llm=llm)

    # 只有 narration 段的原文进了 prompt —— drama 段("乃立三丈之木...")不应出现
    prompt = llm.call_args.kwargs["messages"][0]["content"]
    assert "令既具" in prompt
    assert "民怪之" in prompt
    assert "乃立三丈之木" not in prompt

    assert len(script.lines) == 2
    for i, ln in enumerate(script.lines, start=1):
        assert ln.line_id == f"LN{i:03d}"
        assert ln.type == "narration"
        assert ln.speaker == "NARRATOR"
        assert ln.visual_type == "scene"


@pytest.mark.asyncio
async def test_generate_narration_script_tags_diagram_marker_for_non_scene_visual_type():
    draft = {
        "lines": [
            {
                "text": "此事发生于战国中期，秦国正处变法关口。",
                "visual_type": "timeline",
                "visual_hint": "战国秦变法时间线",
            }
        ]
    }
    llm = _mock_llm(json.dumps(draft, ensure_ascii=False))
    event_unit = _make_event_unit()

    script = await generate_narration_script(event_unit, llm=llm)

    assert len(script.lines) == 1
    line = script.lines[0]
    assert line.visual_type == "timeline"
    m = DIAGRAM_MARKER_RE.match(line.visual_hint)
    assert m is not None
    assert m.group(1) == "timeline"


@pytest.mark.asyncio
async def test_generate_narration_script_invalid_visual_type_falls_back_to_scene():
    draft = {"lines": [{"text": "讲解文本", "visual_type": "bogus", "visual_hint": ""}]}
    llm = _mock_llm(json.dumps(draft, ensure_ascii=False))
    script = await generate_narration_script(_make_event_unit(), llm=llm)
    assert script.lines[0].visual_type == "scene"
    assert DIAGRAM_MARKER_RE.match(script.lines[0].visual_hint) is None


@pytest.mark.asyncio
async def test_generate_narration_script_empty_when_no_narration_segments():
    event_unit = EventUnit(
        event_unit_id="EU001",
        segments=[Segment(type="drama", source_text="全是演绎段", order=0)],
    )
    llm = AsyncMock()
    script = await generate_narration_script(event_unit, llm=llm)
    assert script.lines == []
    llm.assert_not_called()


@pytest.mark.asyncio
async def test_generate_narration_script_degrades_on_llm_failure():
    llm = AsyncMock(side_effect=RuntimeError("network down"))
    script = await generate_narration_script(_make_event_unit(), llm=llm)
    assert script.lines == []
