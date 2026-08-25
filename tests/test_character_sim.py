# 测试数据长行
"""v9.1 角色权威推演(novel-studio 世界推演移植)单测。"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from hevi.tongjian.character_sim import (
    _extract_json,
    dump_character_states,
    gate_character_states,
    simulate_character_states,
)
from hevi.tongjian.schemas import ChapterIR, CharacterIR, EventIR, QuoteIR


def _chapter_ir() -> ChapterIR:
    return ChapterIR(
        meta={"source": "资治通鉴·周纪一", "year_range": (0, 0), "char_count": 100},
        characters=[
            CharacterIR(
                character_id="c_zhihu", canonical_name="智伯", role_in_chapter="antagonist"
            ),
            CharacterIR(
                character_id="c_xiangzi", canonical_name="赵襄子", role_in_chapter="protagonist"
            ),
        ],
        events=[
            EventIR(
                event_id="E1", summary="智伯向赵襄子索地",
                actors=["c_zhihu", "c_xiangzi"], dramatic_weight=5,
            ),
        ],
        quotes=[
            QuoteIR(quote_id="Q1", speaker="c_zhihu", original="吾欲地于赵", event_id="E1"),
        ],
    )


@pytest.mark.asyncio
async def test_simulate_parses_llm_json() -> None:
    llm = AsyncMock(
        return_value={
            "content": """```json
{"characters": [
  {"character_id": "c_zhihu", "goal": "吞并赵氏土地", "pressure": "晋卿环伺",
   "resources": ["智氏六卿之众"],
   "knowledge_boundary": ["知道: 赵氏势弱", "不能提前知道: 赵襄子已联魏韩"],
   "offscreen_action": "联络魏韩二卿", "decision_model": "强权优先"}
]}
```"""
        }
    )
    states = await simulate_character_states(_chapter_ir(), llm)
    assert len(states) == 1
    assert states[0]["character_id"] == "c_zhihu"
    assert states[0]["goal"] == "吞并赵氏土地"
    assert any("不能提前知道" in k for k in states[0]["knowledge_boundary"])


@pytest.mark.asyncio
async def test_simulate_filters_unknown_characters() -> None:
    llm = AsyncMock(
        return_value={
            "content": """{"characters": [
              {"character_id": "c_zhihu", "goal": "g", "pressure": "p", "knowledge_boundary": ["k"], "offscreen_action": "o"},
              {"character_id": "unrelated", "goal": "g", "pressure": "p", "knowledge_boundary": ["k"], "offscreen_action": "o"}]}"""
        }
    )
    states = await simulate_character_states(_chapter_ir(), llm)
    assert {s["character_id"] for s in states} == {"c_zhihu"}


@pytest.mark.asyncio
async def test_simulate_degrades_on_llm_failure() -> None:
    llm = AsyncMock(side_effect=RuntimeError("llm down"))
    states = await simulate_character_states(_chapter_ir(), llm)
    assert states == []


def test_gate_requires_coverage_and_boundaries() -> None:
    ir = _chapter_ir()
    # 完整档案 → 通过。
    full = [
        {"character_id": "c_zhihu", "goal": "g", "pressure": "p", "resources": ["r"],
         "knowledge_boundary": ["知道: x", "不能提前知道: y"], "offscreen_action": "o", "decision_model": "d"},
        {"character_id": "c_xiangzi", "goal": "g", "pressure": "p", "resources": ["r"],
         "knowledge_boundary": ["知道: x", "不能提前知道: y"], "offscreen_action": "o", "decision_model": "d"},
    ]
    g = gate_character_states(full, ir)
    assert g.passed is True

    # 缺档案 → 不通过(但 coverage 反映覆盖)。
    g2 = gate_character_states([full[0]], ir)
    assert g2.passed is False
    assert any("缺少推演档案" in e for e in g2.errors)
    assert g2.coverage < 1.0

    # knowledge_boundary 空 → 不通过。
    g3 = gate_character_states(
        [
            {"character_id": "c_zhihu", "knowledge_boundary": [], "offscreen_action": "o"},
            {"character_id": "c_xiangzi", "knowledge_boundary": ["k"], "offscreen_action": "o"},
        ],
        ir,
    )
    assert g3.passed is False
    assert any("knowledge_boundary 为空" in e for e in g3.errors)


def test_dump_load_roundtrip(tmp_path: pytest.TempPathFactory) -> None:
    states = [{"character_id": "c_zhihu", "goal": "g"}]
    path = tmp_path / "L2" / "character_sim.json"
    dump_character_states(states, path)
    loaded = __import__("hevi.tongjian.character_sim", fromlist=["load_character_states"]).load_character_states(path)
    assert loaded == states
    assert __import__("hevi.tongjian.character_sim", fromlist=["load_character_states"]).load_character_states(
        tmp_path / "missing.json"
    ) is None


def test_extract_json_strips_markdown() -> None:
    assert _extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert _extract_json('{"a": 1}') == {"a": 1}
    assert _extract_json("not json") == {}
