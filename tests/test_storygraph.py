"""B0 story_graph 抽取测试。手稿为自撰短篇小说节选(无版权问题),验证
小说通用抽取范式:确定性 span 定位、char_id/event_id 分配、对白幻觉守卫、
first_appearance 计算、LLM 失败降级。约定对齐 tests/test_tongjian_chapter_ir.py。
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from hevi.storygraph import extract_story_graph

RAW_TEXT = (
    "林夏推开出租屋的门时,天已经黑透了。桌上留着一张纸条,是母亲的字迹:"
    "「饭在锅里,我去医院看你父亲,别等我。」她把纸条攥成一团,冷笑了一声。"
    "三年前那个男人抛下这个家的时候,可没想过还会有今天。"
    "手机响了,是发小陈默。陈默在电话那头压低声音:「你父亲的病,是我垫的钱。」"
    "林夏愣住了。她一直以为那笔救命钱是天上掉下来的。"
    "「你为什么不告诉我?」她的声音发颤。陈默沉默了很久,才说:「因为我怕你不肯要。」"
    "那一夜,林夏在阳台上站到天亮。她终于决定,去医院见父亲最后一面。"
)

# 一份能通过基本校验的抽取草稿:三个人物 + 三个事件 + 两处对白,
# mentions/quote_span/original 全部是 RAW_TEXT 的逐字连续子串。
_GOOD_DRAFT = {
    "characters": [
        {
            "name": "林夏",
            "aliases": ["她"],
            "description": "年轻女性,冷峻,压抑着怨恨",
            "role": "protagonist",
            "faction": "",
            "mentions": ["林夏推开出租屋的门时", "林夏愣住了"],
        },
        {
            "name": "陈默",
            "aliases": ["发小陈默"],
            "description": "沉默寡言的青年,暗中相助",
            "role": "supporting",
            "faction": "",
            "mentions": ["是发小陈默"],
        },
        {
            "name": "母亲",
            "aliases": [],
            "description": "操劳的中年女性",
            "role": "supporting",
            "faction": "",
            "mentions": ["是母亲的字迹"],
        },
    ],
    "events": [
        {
            "summary": "林夏回到出租屋,发现母亲留条去医院看父亲",
            "actors": ["林夏", "母亲"],
            "location": "出租屋",
            "time_hint": "入夜",
            "causes": [],
            "effects": [1],
            "beat_type": "铺垫",
            "dramatic_weight": 2,
            "quote_span": "桌上留着一张纸条",
        },
        {
            "summary": "陈默来电,坦白父亲的救命钱是他垫付的",
            "actors": ["林夏", "陈默"],
            "location": "出租屋",
            "time_hint": "当晚",
            "causes": [0],
            "effects": [2],
            "beat_type": "转折",
            "dramatic_weight": 4,
            "quote_span": "你父亲的病,是我垫的钱",
        },
        {
            "summary": "林夏站到天亮,决定去见父亲最后一面",
            "actors": ["林夏"],
            "location": "阳台",
            "time_hint": "那一夜",
            "causes": [1],
            "effects": [],
            "beat_type": "收束",
            "dramatic_weight": 5,
            "quote_span": "去医院见父亲最后一面",
        },
    ],
    "quotes": [
        {
            "speaker": "陈默",
            "original": "因为我怕你不肯要。",
            "modern": "因为我怕你不愿意接受。",
            "event_index": 1,
            "emotion": "隐忍",
        },
        {
            "speaker": "林夏",
            "original": "你为什么不告诉我?",
            "modern": "你为什么瞒着我?",
            "event_index": 1,
            "emotion": "颤抖",
        },
    ],
    "locations": [
        {"name": "出租屋", "type": "住所", "event_indices": [0, 1]},
        {"name": "阳台", "type": "住所", "event_indices": [2]},
    ],
}


def _mock_llm(json_text: str) -> AsyncMock:
    llm = AsyncMock()
    llm.return_value = {"content": json_text}
    return llm


@pytest.mark.asyncio
async def test_extract_story_graph_resolves_real_spans():
    llm = _mock_llm(json.dumps(_GOOD_DRAFT, ensure_ascii=False))
    sg = await extract_story_graph(source_name="都市短篇·最后一面", raw_text=RAW_TEXT, llm=llm)

    assert len(sg.characters) == 3
    linxia = next(c for c in sg.characters if c.name == "林夏")
    assert linxia.char_id == "C001"
    assert linxia.description  # 外貌/性格特征被保留(喂 Subject 建模)
    assert len(linxia.source_spans) == 2
    for start, end in linxia.source_spans:
        assert RAW_TEXT[start:end] in ("林夏推开出租屋的门时", "林夏愣住了")

    # first_appearance = 最早 mention 的 span
    assert linxia.first_appearance == min(linxia.source_spans, key=lambda s: s[0])
    assert (
        RAW_TEXT[linxia.first_appearance[0] : linxia.first_appearance[1]] == "林夏推开出租屋的门时"
    )

    assert len(sg.events) == 3
    assert sg.events[0].actors == ["C001", "C003"]  # 林夏, 母亲
    assert sg.events[1].causes == ["E001"]
    assert sg.events[0].effects == ["E002"]
    assert sg.events[1].beat_type == "转折"
    start, end = sg.events[1].source_span
    assert RAW_TEXT[start:end] == "你父亲的病,是我垫的钱"

    assert len(sg.quotes) == 2
    assert sg.quotes[0].speaker == "C002"  # 陈默
    assert sg.quotes[0].original in RAW_TEXT
    assert sg.quotes[0].event_id == "E002"

    # 阶段 1:relationships / arcs 结构存在但不填充
    assert sg.relationships == []
    assert sg.arcs == []


@pytest.mark.asyncio
async def test_extract_story_graph_drops_hallucinated_quote():
    """original 在手稿里找不到 → 丢弃,不进入 StoryGraph(叙事红线)。"""
    draft = {
        "characters": _GOOD_DRAFT["characters"][:1],
        "events": [],
        "quotes": [
            {
                "speaker": "林夏",
                "original": "这句话手稿里根本没有,是模型编的。",
                "modern": "",
                "event_index": None,
                "emotion": "",
            }
        ],
        "locations": [],
    }
    llm = _mock_llm(json.dumps(draft, ensure_ascii=False))
    sg = await extract_story_graph(source_name="test", raw_text=RAW_TEXT, llm=llm)
    assert sg.quotes == []


@pytest.mark.asyncio
async def test_extract_story_graph_degrades_on_llm_failure():
    """LLM 调用异常 → 不抛异常,返回空壳 StoryGraph(降级,不阻塞流水线)。"""
    llm = AsyncMock(side_effect=RuntimeError("network down"))
    sg = await extract_story_graph(source_name="test", raw_text=RAW_TEXT, llm=llm)
    assert sg.events == []
    assert sg.characters == []
    assert sg.meta.char_count == len(RAW_TEXT)


@pytest.mark.asyncio
async def test_extract_story_graph_maps_locations_to_events():
    llm = _mock_llm(json.dumps(_GOOD_DRAFT, ensure_ascii=False))
    sg = await extract_story_graph(source_name="test", raw_text=RAW_TEXT, llm=llm)
    assert len(sg.locations) == 2
    home = next(loc for loc in sg.locations if loc.name == "出租屋")
    assert home.location_id == "L001"
    assert home.events == ["E001", "E002"]
