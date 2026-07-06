"""L5 character_bible(文本部分)生成 + G5 门测试。"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from hevi.tongjian.character_bible import (
    gate_character_bible,
    generate_character_bible,
    generate_reference_images,
)
from hevi.tongjian.schemas import (
    Act,
    ChapterIR,
    ChapterMeta,
    CharacterBible,
    CharacterBibleEntry,
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


# ── generate_reference_images(步骤3-4:候选立绘 + VLM 年代审)────────────────


def _make_bible(entries: list[dict] | None = None) -> CharacterBible:
    if entries is None:
        entries = [
            {
                "character_id": "C001",
                "name": "智伯",
                "appearance": "魁伟美髯,玄色深衣",
                "era_check": "战国早期服制",
            },
        ]
    return CharacterBible(characters=[CharacterBibleEntry(**e) for e in entries])


def _mock_image_gen() -> AsyncMock:
    """真实 provider 会把图片写到 output_path;mock 同样落一个假文件,行为更贴近真实。"""

    async def _gen(*, prompt, output_path, seed, extra):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"fake-png")
        return {"output_path": str(output_path), "seed": seed}

    return AsyncMock(side_effect=_gen)


def _mock_vlm(*responses: str) -> AsyncMock:
    """按调用顺序依次返回给定的 JSON 字符串(候选一个个审)。"""
    return AsyncMock(side_effect=[{"content": r} for r in responses])


@pytest.mark.asyncio
async def test_locks_first_passing_candidate(tmp_path):
    bible = _make_bible()
    image_gen = _mock_image_gen()
    vlm = _mock_vlm('{"passes": true, "violations": []}')

    result = await generate_reference_images(
        bible,
        CONSTITUTION,
        output_dir=tmp_path,
        image_gen=image_gen,
        vlm=vlm,
    )

    c001 = result.characters[0]
    assert c001.ref_image == str(tmp_path / "c001_v0.png")
    assert c001.gen_lock is not None
    assert c001.gen_lock["ip_adapter_weight"] == 0.6
    assert isinstance(c001.gen_lock["seed"], int)
    image_gen.assert_awaited_once()
    vlm.assert_awaited_once()


@pytest.mark.asyncio
async def test_falls_back_to_next_candidate_when_first_fails_audit(tmp_path):
    bible = _make_bible()
    image_gen = _mock_image_gen()
    vlm = _mock_vlm(
        '{"passes": false, "violations": ["穿了唐装"]}',
        '{"passes": true, "violations": []}',
    )

    result = await generate_reference_images(
        bible,
        CONSTITUTION,
        output_dir=tmp_path,
        image_gen=image_gen,
        vlm=vlm,
    )

    c001 = result.characters[0]
    assert c001.ref_image == str(tmp_path / "c001_v1.png")
    assert image_gen.await_count == 2
    assert vlm.await_count == 2


@pytest.mark.asyncio
async def test_leaves_ref_image_none_when_all_candidates_fail_audit(tmp_path):
    bible = _make_bible()
    image_gen = _mock_image_gen()
    vlm = _mock_vlm(*(['{"passes": false, "violations": ["x"]}'] * 3))

    result = await generate_reference_images(
        bible,
        CONSTITUTION,
        output_dir=tmp_path,
        image_gen=image_gen,
        vlm=vlm,
        num_candidates=3,
    )

    c001 = result.characters[0]
    assert c001.ref_image is None
    assert c001.gen_lock is None
    assert image_gen.await_count == 3


@pytest.mark.asyncio
async def test_leaves_ref_image_none_when_image_gen_always_fails(tmp_path):
    bible = _make_bible()
    image_gen = AsyncMock(side_effect=RuntimeError("GPU OOM"))
    vlm = AsyncMock()

    result = await generate_reference_images(
        bible,
        CONSTITUTION,
        output_dir=tmp_path,
        image_gen=image_gen,
        vlm=vlm,
    )

    c001 = result.characters[0]
    assert c001.ref_image is None
    vlm.assert_not_awaited()


@pytest.mark.asyncio
async def test_skips_entry_that_already_has_ref_image(tmp_path):
    bible = _make_bible(
        [
            {
                "character_id": "C001",
                "name": "智伯",
                "appearance": "魁伟美髯",
                "era_check": "战国早期服制",
                "ref_image": "already/locked.png",
            },
        ]
    )
    image_gen = _mock_image_gen()
    vlm = _mock_vlm('{"passes": true}')

    result = await generate_reference_images(
        bible,
        CONSTITUTION,
        output_dir=tmp_path,
        image_gen=image_gen,
        vlm=vlm,
    )

    assert result.characters[0].ref_image == "already/locked.png"
    image_gen.assert_not_awaited()
    vlm.assert_not_awaited()


@pytest.mark.asyncio
async def test_skips_entry_with_no_appearance(tmp_path):
    bible = _make_bible(
        [
            {"character_id": "C001", "name": "智伯", "appearance": "", "era_check": ""},
        ]
    )
    image_gen = _mock_image_gen()
    vlm = AsyncMock()

    result = await generate_reference_images(
        bible,
        CONSTITUTION,
        output_dir=tmp_path,
        image_gen=image_gen,
        vlm=vlm,
    )

    assert result.characters[0].ref_image is None
    image_gen.assert_not_awaited()


@pytest.mark.asyncio
async def test_gate_no_longer_warns_once_ref_image_locked(tmp_path):
    bible = _make_bible()
    image_gen = _mock_image_gen()
    vlm = _mock_vlm('{"passes": true, "violations": []}')

    result = await generate_reference_images(
        bible,
        CONSTITUTION,
        output_dir=tmp_path,
        image_gen=image_gen,
        vlm=vlm,
    )
    gate = gate_character_bible(result)

    assert not any("尚无权威参考图" in w for w in gate.warnings)
