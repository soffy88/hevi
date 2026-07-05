"""L5 character_bible(文本部分)生成 + G5 门测试。"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from hevi.tongjian.character_bible import gate_character_bible, generate_character_bible
from hevi.tongjian.schemas import (
    Act,
    ChapterIR,
    ChapterMeta,
    CharacterIR,
    Constitution,
    QuoteIR,
    Script,
    ScriptLine,
    VisualStyle,
)

CHAPTER_IR = ChapterIR(
    meta=ChapterMeta(source="test", char_count=100),
    characters=[
        CharacterIR(
            character_id="C001",
            canonical_name="智伯",
            aliases=["智襄子"],
            role_in_chapter="antagonist",
        ),
        CharacterIR(character_id="C002", canonical_name="段规", role_in_chapter="supporting"),
        CharacterIR(character_id="C003", canonical_name="旁观者", role_in_chapter="anonymous"),
    ],
    quotes=[QuoteIR(quote_id="Q001", speaker="C002", original="智伯好利而愎")],
)

CONSTITUTION = Constitution(
    visual_style=VisualStyle(art_direction="水墨质感历史插画", palette=["#2b2b2b"]),
    act_structure=[Act(act=1, title="x", events=[])],
)

SCRIPT_WITH_DIALOGUE = Script(
    lines=[
        ScriptLine(line_id="LN001", type="dialogue", speaker="C002", text="...", quote_id="Q001"),
        ScriptLine(line_id="LN002", type="narration", text="...", visual_hint="智伯于宴席举杯"),
    ]
)


def _mock_llm(json_text: str) -> AsyncMock:
    llm = AsyncMock()
    llm.return_value = {"content": json_text}
    return llm


# ── generate_character_bible ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_generate_includes_dialogue_speaker_and_visual_hint_mention():
    draft = {
        "characters": [
            {
                "character_id": "C001",
                "appearance": "四十余岁,魁伟美髯,玄色深衣",
                "era_check": "战国早期服制",
            },
            {
                "character_id": "C002",
                "appearance": "中年谋士,青衣束发",
                "era_check": "战国早期服制",
            },
        ]
    }
    llm = _mock_llm(json.dumps(draft, ensure_ascii=False))
    bible = await generate_character_bible(SCRIPT_WITH_DIALOGUE, CHAPTER_IR, CONSTITUTION, llm=llm)

    ids = {e.character_id for e in bible.characters}
    assert ids == {"C001", "C002"}  # C001 因 visual_hint 提及,C002 因说了台词;C003 无戏份不入选
    c001 = next(e for e in bible.characters if e.character_id == "C001")
    assert c001.appearance == "四十余岁,魁伟美髯,玄色深衣"
    assert c001.ref_image is None
    assert c001.voice_id is None


@pytest.mark.asyncio
async def test_generate_no_dramatic_characters_returns_empty():
    empty_script = Script(lines=[ScriptLine(line_id="LN001", type="narration", text="...")])
    llm = _mock_llm('{"characters": []}')
    bible = await generate_character_bible(empty_script, CHAPTER_IR, CONSTITUTION, llm=llm)
    assert bible.characters == []


@pytest.mark.asyncio
async def test_generate_keeps_entry_with_blank_fields_when_llm_omits_character():
    # LLM 只回了 C002,漏了有台词/visual_hint 的 C001 —— 不能整个丢掉 C001,
    # 而是保留空壳条目让 G5 抓出来(降级,不是消失)。
    draft = {"characters": [{"character_id": "C002", "appearance": "x", "era_check": "y"}]}
    llm = _mock_llm(json.dumps(draft, ensure_ascii=False))
    bible = await generate_character_bible(SCRIPT_WITH_DIALOGUE, CHAPTER_IR, CONSTITUTION, llm=llm)

    c001 = next(e for e in bible.characters if e.character_id == "C001")
    assert c001.appearance == ""


@pytest.mark.asyncio
async def test_generate_degrades_on_llm_failure():
    llm = AsyncMock(side_effect=RuntimeError("network down"))
    bible = await generate_character_bible(SCRIPT_WITH_DIALOGUE, CHAPTER_IR, CONSTITUTION, llm=llm)
    assert {e.character_id for e in bible.characters} == {"C001", "C002"}
    assert all(e.appearance == "" for e in bible.characters)


# ── gate_character_bible ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_gate_passes_on_good_bible_with_ref_image_warning():
    draft = {
        "characters": [
            {
                "character_id": "C001",
                "appearance": "四十余岁,魁伟美髯,玄色深衣",
                "era_check": "战国早期服制",
            },
            {
                "character_id": "C002",
                "appearance": "中年谋士,青衣束发",
                "era_check": "战国早期服制",
            },
        ]
    }
    llm = _mock_llm(json.dumps(draft, ensure_ascii=False))
    bible = await generate_character_bible(SCRIPT_WITH_DIALOGUE, CHAPTER_IR, CONSTITUTION, llm=llm)
    result = gate_character_bible(bible)

    assert result.passed is True
    assert result.coverage == 1.0
    # ref_image 还没有(阻塞在 GPU),但这只是 warning,不阻塞门
    assert any("尚无权威参考图" in w for w in result.warnings)


@pytest.mark.asyncio
async def test_gate_fails_on_missing_appearance():
    draft = {"characters": [{"character_id": "C002", "appearance": "x", "era_check": "y"}]}
    llm = _mock_llm(json.dumps(draft, ensure_ascii=False))
    bible = await generate_character_bible(SCRIPT_WITH_DIALOGUE, CHAPTER_IR, CONSTITUTION, llm=llm)
    result = gate_character_bible(bible)

    assert result.passed is False
    assert any("缺少外形描述" in e for e in result.errors)
    assert result.coverage == 0.5


@pytest.mark.asyncio
async def test_gate_fails_on_anachronism_term():
    draft = {
        "characters": [
            {
                "character_id": "C001",
                "appearance": "身着唐装,气度不凡",
                "era_check": "战国早期服制",
            },
            {
                "character_id": "C002",
                "appearance": "中年谋士,青衣束发",
                "era_check": "战国早期服制",
            },
        ]
    }
    llm = _mock_llm(json.dumps(draft, ensure_ascii=False))
    bible = await generate_character_bible(SCRIPT_WITH_DIALOGUE, CHAPTER_IR, CONSTITUTION, llm=llm)
    result = gate_character_bible(bible)

    assert result.passed is False
    assert any("年代错误词" in e and "唐装" in e for e in result.errors)
