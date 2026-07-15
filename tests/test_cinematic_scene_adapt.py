"""C2.5 场景化改编 + CG2.5 门测试。"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from hevi.cinematic.schemas import Beat, BeatDialogue
from hevi.cinematic.scene_adapt import adapt_scene, gate_scene_adapt
from hevi.tongjian.schemas import (
    ChapterIR,
    ChapterMeta,
    CharacterIR,
    EventIR,
    QuoteIR,
    Script,
    ScriptLine,
)

CHAPTER_IR = ChapterIR(
    meta=ChapterMeta(source="test"),
    characters=[
        CharacterIR(character_id="zhibo", canonical_name="智伯"),
        CharacterIR(character_id="hankangzi", canonical_name="韩康子"),
        CharacterIR(character_id="duangui", canonical_name="段规"),
    ],
    events=[EventIR(event_id="E001", summary="智伯索地")],
    quotes=[
        QuoteIR(
            quote_id="Q001",
            speaker="duangui",
            original="不如与之",
            modern="不如给他",
            event_id="E001",
        )
    ],
)

SCRIPT = Script(
    lines=[
        ScriptLine(line_id="LN001", type="narration", text="建立镜头"),
        ScriptLine(
            line_id="LN002",
            type="dialogue",
            speaker="duangui",
            text="不如给他",
            quote_id="Q001",
            event_id="E001",
        ),
    ]
)


def _mock_llm(violations: list | None = None):
    import json

    return AsyncMock(return_value={"content": json.dumps({"violations": violations or []})})


@pytest.mark.asyncio
async def test_adapt_scene_maps_script_lines_to_beats():
    scene = await adapt_scene(SCRIPT, CHAPTER_IR, scene_id="SC01")
    assert [b.beat_id for b in scene.beats] == ["B001", "B002"]
    assert scene.beats[1].dialogue.quote_id == "Q001"
    assert scene.characters == ["duangui", "hankangzi", "zhibo"]


@pytest.mark.asyncio
async def test_adapt_scene_splices_extra_beats_after_given_line():
    extra = Beat(
        beat_id="B_extra",
        dialogue=BeatDialogue(speaker="zhibo", text="给我地。", is_performative=True),
    )
    scene = await adapt_scene(SCRIPT, CHAPTER_IR, scene_id="SC01", extra_beats={"LN001": [extra]})
    assert [b.beat_id for b in scene.beats] == ["B001", "B_extra", "B002"]


@pytest.mark.asyncio
async def test_gate_passes_real_quote_dialogue():
    scene = await adapt_scene(SCRIPT, CHAPTER_IR, scene_id="SC01")
    result = await gate_scene_adapt(scene, CHAPTER_IR, llm=_mock_llm())
    assert result.passed is True


@pytest.mark.asyncio
async def test_gate_passes_marked_performative_dialogue():
    extra = Beat(
        beat_id="B_extra",
        dialogue=BeatDialogue(speaker="zhibo", text="给我地。", is_performative=True),
    )
    scene = await adapt_scene(SCRIPT, CHAPTER_IR, scene_id="SC01", extra_beats={"LN001": [extra]})
    result = await gate_scene_adapt(scene, CHAPTER_IR, llm=_mock_llm())
    assert result.passed is True


@pytest.mark.asyncio
async def test_gate_rejects_unmarked_invented_dialogue():
    """史实红线:既没 quote_id 也没标 is_performative 的台词必须被拒——这是
    scene_adapt 里最重要的一条防线,不能因为改动而悄悄松掉。"""
    extra = Beat(
        beat_id="B_bad",
        dialogue=BeatDialogue(speaker="zhibo", text="悄悄编的台词"),
    )
    scene = await adapt_scene(SCRIPT, CHAPTER_IR, scene_id="SC01", extra_beats={"LN001": [extra]})
    result = await gate_scene_adapt(scene, CHAPTER_IR, llm=_mock_llm())
    assert result.passed is False
    assert any("悄悄编台词" in e for e in result.errors)


@pytest.mark.asyncio
async def test_gate_rejects_dialogue_referencing_unknown_quote_id():
    extra = Beat(
        beat_id="B_bad",
        dialogue=BeatDialogue(speaker="zhibo", text="假引语", quote_id="Q999"),
    )
    scene = await adapt_scene(SCRIPT, CHAPTER_IR, scene_id="SC01", extra_beats={"LN001": [extra]})
    result = await gate_scene_adapt(scene, CHAPTER_IR, llm=_mock_llm())
    assert result.passed is False
    assert any("Q999" in e for e in result.errors)


@pytest.mark.asyncio
async def test_gate_rejects_banned_action_word():
    scene = await adapt_scene(SCRIPT, CHAPTER_IR, scene_id="SC01")
    scene.beats[0].action = "段规拔剑而起"
    result = await gate_scene_adapt(scene, CHAPTER_IR, llm=_mock_llm())
    assert result.passed is False
    assert any("拔剑" in e for e in result.errors)


@pytest.mark.asyncio
async def test_gate_rejects_unknown_speaker():
    extra = Beat(
        beat_id="B_bad",
        dialogue=BeatDialogue(speaker="nobody", text="谁在说话", is_performative=True),
    )
    scene = await adapt_scene(SCRIPT, CHAPTER_IR, scene_id="SC01", extra_beats={"LN001": [extra]})
    result = await gate_scene_adapt(scene, CHAPTER_IR, llm=_mock_llm())
    assert result.passed is False
    assert any("nobody" in e for e in result.errors)
