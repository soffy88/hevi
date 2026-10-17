"""SPEC-005 §1.1 选段(chunking)+ T1 版权 lint 测试。原文取自《史记·商君列传》
"商鞅立木"段落(公版古籍)。"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from hevi.tongjian.event_unit import extract_event_units
from hevi.tongjian.gates import lint_copyright

RAW_TEXT = (
    "令既具，未布，恐民之不信，乃立三丈之木於國都市南門，募民有能徙置北門者予十金。"
    "民怪之，莫敢徙。復曰能徙者予五十金。有一人徙之，輒予五十金，以明不欺。卒下令。"
)

_GOOD_DRAFT = {
    "event_units": [
        {
            "title": "商鞅立木",
            "era": "战国·秦",
            "year": -359,
            "summary": "商鞅立木南门,悬赏取信于民",
            "segments": [
                {"type": "narration", "text": "令既具，未布，恐民之不信，"},
                {
                    "type": "drama",
                    "text": "乃立三丈之木於國都市南門，募民有能徙置北門者予十金。",
                },
                {"type": "narration", "text": "民怪之，莫敢徙。"},
                {"type": "drama", "text": "復曰能徙者予五十金。有一人徙之，輒予五十金，以明不欺。"},
                {"type": "narration", "text": "卒下令。"},
            ],
        }
    ]
}


def _mock_llm(json_text: str) -> AsyncMock:
    llm = AsyncMock()
    llm.return_value = {"content": json_text}
    return llm


# ── extract_event_units ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_extract_event_units_parses_segments_in_order():
    llm = _mock_llm(json.dumps(_GOOD_DRAFT, ensure_ascii=False))
    units = await extract_event_units(source_name="史记·商君列传", raw_text=RAW_TEXT, llm=llm)

    assert len(units) == 1
    unit = units[0]
    assert unit.event_unit_id == "EU001"
    assert unit.title == "商鞅立木"
    assert unit.year == -359
    assert len(unit.segments) == 5
    assert [s.type for s in unit.segments] == [
        "narration",
        "drama",
        "narration",
        "drama",
        "narration",
    ]
    assert [s.order for s in unit.segments] == [0, 1, 2, 3, 4]
    for seg in unit.segments:
        assert seg.source_text in RAW_TEXT
        assert seg.est_duration_s > 0


@pytest.mark.asyncio
async def test_extract_event_units_drops_hallucinated_segment():
    draft = {
        "event_units": [
            {
                "title": "商鞅立木",
                "era": "战国·秦",
                "year": -359,
                "summary": "商鞅立木南门",
                "segments": [
                    {"type": "narration", "text": "令既具，未布，恐民之不信，"},
                    {"type": "drama", "text": "这句话原文根本没有，是编的"},
                ],
            }
        ]
    }
    llm = _mock_llm(json.dumps(draft, ensure_ascii=False))
    units = await extract_event_units(source_name="test", raw_text=RAW_TEXT, llm=llm)

    assert len(units) == 1
    assert len(units[0].segments) == 1
    assert units[0].segments[0].type == "narration"


@pytest.mark.asyncio
async def test_extract_event_units_drops_unit_with_no_valid_segments():
    draft = {
        "event_units": [
            {"title": "全编造", "segments": [{"type": "narration", "text": "全是编的内容"}]}
        ]
    }
    llm = _mock_llm(json.dumps(draft, ensure_ascii=False))
    units = await extract_event_units(source_name="test", raw_text=RAW_TEXT, llm=llm)
    assert units == []


@pytest.mark.asyncio
async def test_extract_event_units_degrades_on_llm_failure():
    llm = AsyncMock(side_effect=RuntimeError("network down"))
    units = await extract_event_units(source_name="test", raw_text=RAW_TEXT, llm=llm)
    assert units == []


# ── T1 lint_copyright ────────────────────────────────────────────────────


def test_lint_copyright_passes_on_classical_text():
    result = lint_copyright(RAW_TEXT)
    assert result.passed is True
    assert result.errors == []


def test_lint_copyright_passes_on_long_classical_text():
    # 长文言原文(>200字,虚词以之/也/矣/哉为主)不应被误判为白话译文
    long_classical = (
        "智伯請地於韓康子，康子欲弗與。段規曰：「智伯好利而愎，不與，將伐我；不如與之。"
        "彼狃於得地，必請於他人；他人不與，必向之以兵。然則我得免於患而待事之變矣。」"
        "康子曰：「善。」使使者致萬家之邑於智伯，智伯悅。又求地於魏桓子，桓子欲弗與。"
        "任章曰：「何故弗與？」桓子曰：「無故索地，故弗與。」任章曰：「無故索地，"
        "諸大夫必懼；吾與之地，智伯必驕。彼驕而輕敵，此懼而相親。以相親之兵待輕敵之人，"
        "智氏之命必不長矣。」桓子曰：「善。」復與之萬家之邑一。"
    )
    assert len(long_classical) >= 200
    result = lint_copyright(long_classical)
    assert result.passed is True
    assert result.errors == []


def test_lint_copyright_fails_on_translation_marker():
    text = "商鞅立木\n【译文】命令已经完备，还没公布..." + RAW_TEXT
    result = lint_copyright(text)
    assert result.passed is False
    assert any("译注标记" in e for e in result.errors)


def test_lint_copyright_fails_on_high_modern_particle_density():
    # 大量现代白话虚词、极少文言虚词的长文本 —— 疑似译文而非原文
    text = "的了的了的了呢吗啊呀地" * 40
    result = lint_copyright(text)
    assert result.passed is False
    assert any("白话译文" in e for e in result.errors)
