"""L0 chapter_ir 抽取 + G0 门测试。原文取自《资治通鉴·周纪一》"智伯索地"段落
(维基文库公开古籍库,繁体原文)。"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from hevi.tongjian import extract_chapter_ir, gate_chapter_ir
from hevi.tongjian.chapter_ir import _find_span

RAW_TEXT = (
    "智伯請地於韓康子，康子欲弗與。段規曰：「智伯好利而愎，不與，將伐我；不如與之。"
    "彼狃於得地，必請於他人；他人不與，必向之以兵。然則我得免於患而待事之變矣。」"
    "康子曰：「善。」使使者致萬家之邑於智伯，智伯悅。"
    "又求地於魏桓子，桓子欲弗與。任章曰：「何故弗與？」桓子曰：「無故索地，故弗與。」"
    "任章曰：「無故索地，諸大夫必懼；吾與之地，智伯必驕。彼驕而輕敵，此懼而相親。"
    "以相親之兵待輕敵之人，智氏之命必不長矣。《周書》曰：『將欲敗之，必姑輔之；"
    "將欲取之，必姑與之。』主不如與之以驕智伯，然後可以擇交而圖智氏矣。"
    "奈何獨以吾為智氏質乎！」桓子曰：「善。」復與之萬家之邑一。"
    "智伯又求藺、皋狼之地於趙襄子，襄子弗與。智伯怒，帥韓、魏之甲以攻趙氏。"
    "襄子將出，曰：「吾何走乎？」從者曰：「長子近，且城厚完。」"
    "襄子曰：「民罷力以完之，又斃死以守之，其誰與我！」從者曰：「邯鄲之倉庫實。」"
    "襄子曰：「浚民之膏澤以實之，又因而殺之，其誰與我！其晉陽乎，先主之所屬也，"
    "尹鐸之所寬也，民必和矣。」乃走晉陽。"
)

# 一份能通过 G0 门的抽取草稿:三处请地 + 三个事件,source_span/original 全部是
# RAW_TEXT 的逐字连续子串(mock LLM 直接照抄原文,不必依赖真实模型能力)。
_GOOD_DRAFT = {
    "characters": [
        {
            "name": "智伯",
            "aliases": ["智襄子"],
            "role_in_chapter": "antagonist",
            "faction": "智氏",
            "fate": "",
            "mentions": ["智伯請地於韓康子", "又求地於魏桓子"],
        },
        {
            "name": "韓康子",
            "aliases": ["康子"],
            "role_in_chapter": "supporting",
            "faction": "韓氏",
            "fate": "",
            "mentions": ["康子欲弗與"],
        },
        {
            "name": "段規",
            "aliases": [],
            "role_in_chapter": "supporting",
            "faction": "韓氏",
            "fate": "",
            "mentions": ["段規曰"],
        },
        {
            "name": "魏桓子",
            "aliases": ["桓子"],
            "role_in_chapter": "supporting",
            "faction": "魏氏",
            "fate": "",
            "mentions": ["桓子欲弗與"],
        },
        {
            "name": "任章",
            "aliases": [],
            "role_in_chapter": "supporting",
            "faction": "魏氏",
            "fate": "",
            "mentions": ["任章曰"],
        },
        {
            "name": "趙襄子",
            "aliases": ["襄子"],
            "role_in_chapter": "protagonist",
            "faction": "趙氏",
            "fate": "",
            "mentions": ["襄子弗與"],
        },
    ],
    "events": [
        {
            "summary": "智伯向韩康子索地,段规献计先给以骄智伯",
            "actors": ["智伯", "韓康子", "段規"],
            "location": "韓氏",
            "year": -455,
            "causes": [],
            "effects": [1],
            "dramatic_weight": 3,
            "quote_span": (
                "智伯請地於韓康子，康子欲弗與。段規曰：「智伯好利而愎，不與，將伐我；"
                "不如與之。彼狃於得地，必請於他人；他人不與，必向之以兵。"
                "然則我得免於患而待事之變矣。」康子曰：「善。」"
                "使使者致萬家之邑於智伯，智伯悅。"
            ),
        },
        {
            "summary": "智伯向魏桓子索地,任章献计骄敌之策",
            "actors": ["智伯", "魏桓子", "任章"],
            "location": "魏氏",
            "year": -455,
            "causes": [0],
            "effects": [2],
            "dramatic_weight": 3,
            "quote_span": (
                "又求地於魏桓子，桓子欲弗與。任章曰：「何故弗與？」桓子曰：「無故索地，故弗與。」"
                "任章曰：「無故索地，諸大夫必懼；吾與之地，智伯必驕。彼驕而輕敵，此懼而相親。"
                "以相親之兵待輕敵之人，智氏之命必不長矣。《周書》曰：『將欲敗之，必姑輔之；"
                "將欲取之，必姑與之。』主不如與之以驕智伯，然後可以擇交而圖智氏矣。"
                "奈何獨以吾為智氏質乎！」桓子曰：「善。」復與之萬家之邑一。"
            ),
        },
        {
            "summary": "智伯向赵襄子索地被拒,遂帅韩魏之兵攻赵,襄子退守晋阳",
            "actors": ["智伯", "趙襄子"],
            "location": "趙氏",
            "year": -455,
            "causes": [1],
            "effects": [],
            "dramatic_weight": 5,
            "quote_span": (
                "智伯又求藺、皋狼之地於趙襄子，襄子弗與。智伯怒，帥韓、魏之甲以攻趙氏。"
                "襄子將出，曰：「吾何走乎？」從者曰：「長子近，且城厚完。」"
                "襄子曰：「民罷力以完之，又斃死以守之，其誰與我！」從者曰：「邯鄲之倉庫實。」"
                "襄子曰：「浚民之膏澤以實之，又因而殺之，其誰與我！其晉陽乎，先主之所屬也，"
                "尹鐸之所寬也，民必和矣。」乃走晉陽。"
            ),
        },
    ],
    "quotes": [
        {
            "speaker": "段規",
            "original": "智伯好利而愎，不與，將伐我；不如與之。",
            "modern": "智伯贪利又刚愎,不给他,他会打我们;不如给他。",
            "event_index": 0,
            "emotion": "劝谏",
        },
        {
            "speaker": "趙襄子",
            "original": "其晉陽乎，先主之所屬也，尹鐸之所寬也，民必和矣。",
            "modern": "还是晋阳吧,先主托付之地,尹铎宽待过百姓,民心必定归附。",
            "event_index": 2,
            "emotion": "决断",
        },
    ],
    "locations": [
        {"name": "韓氏", "type": "封地", "event_indices": [0]},
        {"name": "晉陽", "type": "城池", "event_indices": [2]},
    ],
}


def _mock_llm(json_text: str) -> AsyncMock:
    llm = AsyncMock()
    llm.return_value = {"content": json_text}
    return llm


# ── _find_span ────────────────────────────────────────────────────────────


def test_find_span_locates_exact_substring():
    idx = RAW_TEXT.index("康子欲弗與")
    assert _find_span(RAW_TEXT, "康子欲弗與") == (idx, idx + len("康子欲弗與"))


def test_find_span_returns_none_when_absent():
    assert _find_span(RAW_TEXT, "此句不在原文中") is None


def test_find_span_returns_none_for_empty():
    assert _find_span(RAW_TEXT, "") is None


# ── extract_chapter_ir ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_extract_chapter_ir_resolves_real_spans():
    import json

    llm = _mock_llm(json.dumps(_GOOD_DRAFT, ensure_ascii=False))
    chapter_ir = await extract_chapter_ir(source_name="资治通鉴·周纪一", raw_text=RAW_TEXT, llm=llm)

    assert len(chapter_ir.characters) == 6
    zhibo = next(c for c in chapter_ir.characters if c.canonical_name == "智伯")
    assert zhibo.character_id == "C001"
    assert len(zhibo.source_spans) == 2
    for start, end in zhibo.source_spans:
        assert RAW_TEXT[start:end] in ("智伯請地於韓康子", "又求地於魏桓子")

    assert len(chapter_ir.events) == 3
    assert chapter_ir.events[0].actors == ["C001", "C002", "C003"]
    assert chapter_ir.events[1].causes == ["E001"]
    assert chapter_ir.events[0].effects == ["E002"]
    start, end = chapter_ir.events[0].source_span
    assert RAW_TEXT[start:end].startswith("智伯請地於韓康子，康子欲弗與")
    assert RAW_TEXT[start:end].endswith("智伯悅。")

    assert len(chapter_ir.quotes) == 2
    assert chapter_ir.quotes[0].speaker == "C003"  # 段規
    assert chapter_ir.quotes[0].original in RAW_TEXT
    assert chapter_ir.quotes[0].event_id == "E001"


@pytest.mark.asyncio
async def test_extract_chapter_ir_drops_hallucinated_quote():
    """original 在原文里找不到 → 丢弃,不进入 chapter_ir(史实红线)。"""
    import json

    draft = {
        "characters": _GOOD_DRAFT["characters"][:1],
        "events": [],
        "quotes": [
            {
                "speaker": "智伯",
                "original": "这句话原文根本没有,是编的",
                "modern": "",
                "event_index": None,
                "emotion": "",
            }
        ],
        "locations": [],
    }
    llm = _mock_llm(json.dumps(draft, ensure_ascii=False))
    chapter_ir = await extract_chapter_ir(source_name="test", raw_text=RAW_TEXT, llm=llm)
    assert chapter_ir.quotes == []


@pytest.mark.asyncio
async def test_extract_chapter_ir_degrades_on_llm_failure():
    """LLM 调用异常 → 不抛异常,返回空壳 ChapterIR(降级,不阻塞流水线)。"""
    llm = AsyncMock(side_effect=RuntimeError("network down"))
    chapter_ir = await extract_chapter_ir(source_name="test", raw_text=RAW_TEXT, llm=llm)
    assert chapter_ir.events == []
    assert chapter_ir.characters == []


# ── gate_chapter_ir ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_gate_chapter_ir_passes_on_good_extraction():
    import json

    extract_llm = _mock_llm(json.dumps(_GOOD_DRAFT, ensure_ascii=False))
    chapter_ir = await extract_chapter_ir(
        source_name="资治通鉴·周纪一", raw_text=RAW_TEXT, llm=extract_llm
    )

    gate_llm = _mock_llm('{"supported": true, "reason": "摘要与原文一致"}')
    gated_ir, result = await gate_chapter_ir(chapter_ir, RAW_TEXT, llm=gate_llm)

    assert result.passed is True
    assert result.coverage > 0.0
    assert result.errors == []
    assert gated_ir.characters == chapter_ir.characters


@pytest.mark.asyncio
async def test_gate_chapter_ir_fails_on_low_coverage():
    from hevi.tongjian.schemas import ChapterIR, ChapterMeta, EventIR

    chapter_ir = ChapterIR(
        meta=ChapterMeta(source="test", char_count=len(RAW_TEXT)),
        events=[EventIR(event_id="E001", summary="一件小事", source_span=(0, 5))],
    )
    gate_llm = _mock_llm('{"supported": true, "reason": ""}')
    _, result = await gate_chapter_ir(chapter_ir, RAW_TEXT, llm=gate_llm)

    assert result.passed is False
    assert any("覆盖率" in e for e in result.errors)


@pytest.mark.asyncio
async def test_gate_chapter_ir_fails_on_hallucination_spot_check():
    from hevi.tongjian.schemas import ChapterIR, ChapterMeta, EventIR

    span = (0, len(RAW_TEXT))
    chapter_ir = ChapterIR(
        meta=ChapterMeta(source="test", char_count=len(RAW_TEXT)),
        events=[EventIR(event_id="E001", summary="编造的摘要", source_span=span)],
    )
    gate_llm = _mock_llm('{"supported": false, "reason": "原文没有这个情节"}')
    _, result = await gate_chapter_ir(chapter_ir, RAW_TEXT, llm=gate_llm)

    assert result.passed is False
    assert any("幻觉抽查未通过" in e for e in result.errors)


@pytest.mark.asyncio
async def test_gate_chapter_ir_degrades_unresolved_speaker_to_anonymous():
    from hevi.tongjian.schemas import ChapterIR, ChapterMeta, EventIR, QuoteIR

    span = (0, len(RAW_TEXT))
    chapter_ir = ChapterIR(
        meta=ChapterMeta(source="test", char_count=len(RAW_TEXT)),
        events=[EventIR(event_id="E001", summary="某人说了句话", source_span=span)],
        quotes=[QuoteIR(quote_id="Q001", speaker="无名氏", original="乃走晉陽", event_id="E001")],
    )
    gate_llm = _mock_llm('{"supported": true, "reason": ""}')
    gated_ir, result = await gate_chapter_ir(chapter_ir, RAW_TEXT, llm=gate_llm)

    assert any(w for w in result.warnings if "无名氏" in w)
    anon = next(c for c in gated_ir.characters if c.canonical_name == "无名氏")
    assert anon.role_in_chapter == "anonymous"
    assert gated_ir.quotes[0].speaker == anon.character_id
