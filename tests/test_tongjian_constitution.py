"""L1 constitution 生成 + G1 门测试。"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from hevi.tongjian.constitution import build_constitution, gate_constitution, generate_constitution
from hevi.tongjian.schemas import ChapterIR, ChapterMeta, EventIR

CHAPTER_IR = ChapterIR(
    meta=ChapterMeta(source="test", char_count=100),
    events=[
        EventIR(event_id="E001", summary="智伯索地于韩", dramatic_weight=3),
        EventIR(event_id="E002", summary="智伯索地于魏", dramatic_weight=3),
        EventIR(event_id="E003", summary="智伯索地于赵被拒,退守晋阳", dramatic_weight=5),
    ],
)

_GOOD_CONSTITUTION_DRAFT = {
    "thesis": "礼崩乐坏,始于名分之破",
    "logline": "一场索地引发的时代终结",
    "narrative_stance": "上帝视角旁白",
    "tone": ["肃杀", "克制"],
    "visual_style": {
        "art_direction": "水墨质感历史插画",
        "palette": ["#2b2b2b", "#8b0000"],
        "aspect_ratio": "16:9",
        "negative_style": ["动漫"],
    },
    "act_structure": [
        {"act": 1, "title": "名分之争", "events": ["E001", "E002"], "emotion_curve": "压抑铺垫"},
        {"act": 2, "title": "智伯之亡", "events": ["E003"], "emotion_curve": "冲突爆发"},
    ],
    "forbidden": ["现代梗", "戏说腔"],
    "target_duration_sec": 90,  # 3 事件 * 30s/事件,落在 [10,45] 区间
    "bgm_mood_arc": ["低沉弦乐", "孤箫收尾"],
}


def _mock_llm(json_text: str) -> AsyncMock:
    llm = AsyncMock()
    llm.return_value = {"content": json_text}
    return llm


# ── generate_constitution ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_generate_constitution_parses_draft():
    llm = _mock_llm(json.dumps(_GOOD_CONSTITUTION_DRAFT, ensure_ascii=False))
    c = await generate_constitution(CHAPTER_IR, llm=llm)

    assert c.thesis == "礼崩乐坏,始于名分之破"
    assert len(c.act_structure) == 2
    assert c.act_structure[0].events == ["E001", "E002"]
    assert c.visual_style.palette == ["#2b2b2b", "#8b0000"]
    assert c.target_duration_sec == 90


@pytest.mark.asyncio
async def test_generate_constitution_degrades_on_llm_failure():
    llm = AsyncMock(side_effect=RuntimeError("network down"))
    c = await generate_constitution(CHAPTER_IR, llm=llm)
    assert c.thesis == ""
    assert c.act_structure == []


# ── gate_constitution ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_gate_constitution_passes_on_good_draft():
    llm = _mock_llm(json.dumps(_GOOD_CONSTITUTION_DRAFT, ensure_ascii=False))
    c = await generate_constitution(CHAPTER_IR, llm=llm)
    result = gate_constitution(c, CHAPTER_IR)

    assert result.passed is True
    assert result.coverage == 1.0
    assert result.errors == []


@pytest.mark.asyncio
async def test_gate_constitution_fails_on_unknown_event_ref():
    draft = {
        **_GOOD_CONSTITUTION_DRAFT,
        "act_structure": [{"act": 1, "title": "x", "events": ["E999"]}],
    }
    llm = _mock_llm(json.dumps(draft, ensure_ascii=False))
    c = await generate_constitution(CHAPTER_IR, llm=llm)
    result = gate_constitution(c, CHAPTER_IR)

    assert result.passed is False
    assert any("不存在的 event_id" in e for e in result.errors)


@pytest.mark.asyncio
async def test_gate_constitution_fails_on_missing_critical_event():
    # E003 (dramatic_weight=5) 未被任何一幕收录
    draft = {
        **_GOOD_CONSTITUTION_DRAFT,
        "act_structure": [{"act": 1, "title": "名分之争", "events": ["E001", "E002"]}],
        "target_duration_sec": 60,
    }
    llm = _mock_llm(json.dumps(draft, ensure_ascii=False))
    c = await generate_constitution(CHAPTER_IR, llm=llm)
    result = gate_constitution(c, CHAPTER_IR)

    assert result.passed is False
    assert any("关键事件未被任何一幕收录" in e for e in result.errors)
    assert result.coverage == 0.0


@pytest.mark.asyncio
async def test_gate_constitution_fails_on_duration_mismatch():
    draft = {**_GOOD_CONSTITUTION_DRAFT, "target_duration_sec": 5}  # 5s / 3 事件,远低于 10s 门槛
    llm = _mock_llm(json.dumps(draft, ensure_ascii=False))
    c = await generate_constitution(CHAPTER_IR, llm=llm)
    result = gate_constitution(c, CHAPTER_IR)

    assert result.passed is False
    assert any("不匹配" in e for e in result.errors)


# ── build_constitution (best-of-N + judge) ───────────────────────────────


@pytest.mark.asyncio
async def test_build_constitution_picks_judge_choice():
    bad_draft = {
        **_GOOD_CONSTITUTION_DRAFT,
        "act_structure": [{"act": 1, "title": "x", "events": ["E999"]}],
    }

    call_count = 0

    async def fake_llm(*, messages, max_tokens=None):
        nonlocal call_count
        call_count += 1
        content = messages[0]["content"]
        if "best_index" in content:
            return {"content": '{"best_index": 2}'}
        # 前两次生成返回坏草稿,第三次返回好草稿;judge 明确选第三个(index 2)
        if call_count <= 2:
            return {"content": json.dumps(bad_draft, ensure_ascii=False)}
        return {"content": json.dumps(_GOOD_CONSTITUTION_DRAFT, ensure_ascii=False)}

    best, result = await build_constitution(CHAPTER_IR, llm=fake_llm, n=3)

    assert best.thesis == _GOOD_CONSTITUTION_DRAFT["thesis"]
    assert result.passed is True


@pytest.mark.asyncio
async def test_build_constitution_degrades_when_judge_call_fails():
    """judge LLM 调用失败 → 按 gate 结果确定性挑最优(通过优先于不通过)。"""
    good_json = json.dumps(_GOOD_CONSTITUTION_DRAFT, ensure_ascii=False)
    bad_draft = {
        **_GOOD_CONSTITUTION_DRAFT,
        "act_structure": [{"act": 1, "title": "x", "events": ["E999"]}],
    }
    bad_json = json.dumps(bad_draft, ensure_ascii=False)

    call_count = 0

    async def fake_llm(*, messages, max_tokens=None):
        nonlocal call_count
        call_count += 1
        content = messages[0]["content"]
        if "best_index" in content:
            raise RuntimeError("judge network down")
        call_count_local = call_count
        return {"content": bad_json if call_count_local == 1 else good_json}

    best, result = await build_constitution(CHAPTER_IR, llm=fake_llm, n=2)

    assert result.passed is True
    assert best.thesis == _GOOD_CONSTITUTION_DRAFT["thesis"]
