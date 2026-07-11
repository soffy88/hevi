"""L2 script 生成 + G2 史实门测试。"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from hevi.tongjian.schemas import Act, ChapterIR, ChapterMeta, Constitution, EventIR, QuoteIR
from hevi.tongjian.script import build_script, gate_script, generate_script

CHAPTER_IR = ChapterIR(
    meta=ChapterMeta(source="test", char_count=100),
    events=[
        EventIR(event_id="E001", summary="智伯宴请韩魏赵三家", dramatic_weight=3),
        EventIR(event_id="E002", summary="智伯提出索地被赵襄子拒绝", dramatic_weight=5),
    ],
    quotes=[
        QuoteIR(
            quote_id="Q001",
            speaker="C001",
            original="祸乱要起，也得由我来起。我不发难，谁敢？",
            modern="祸乱要来，也得我来挑起。我不带头，谁敢带头？",
            event_id="E002",
        )
    ],
)


def _make_constitution(
    target_duration_sec: int, forbidden: list[str] | None = None
) -> Constitution:
    return Constitution(
        thesis="礼崩乐坏",
        narrative_stance="上帝视角旁白",
        tone=["肃杀"],
        forbidden=forbidden or [],
        act_structure=[Act(act=1, title="索地", events=["E001", "E002"], emotion_curve="压抑铺垫")],
        target_duration_sec=target_duration_sec,
    )


_GOOD_LINES = [
    {
        "act": 1,
        "type": "narration",
        "speaker": "NARRATOR",
        "text": "智伯设宴,韩魏赵三家大夫皆列席,席间气氛看似寻常。",
        "event_id": "E001",
        "emotion": "平静中藏锋",
        "visual_hint": "宴席远景",
    },
    {
        "act": 1,
        "type": "dialogue",
        "speaker": "C001",
        "text": "祸乱要来,也得我来挑起。我不带头,谁敢带头?",
        "event_id": "E002",
        "quote_id": "Q001",
        "emotion": "狂傲",
        "visual_hint": "智伯举杯,睥睨众人",
    },
]


def _good_draft() -> dict:
    return {"lines": [dict(ln) for ln in _GOOD_LINES]}


def _good_target_duration_sec() -> int:
    total_chars = sum(len(ln["text"]) for ln in _GOOD_LINES)
    return round(total_chars / (4.5 * 0.85))


def _mock_llm(json_text: str) -> AsyncMock:
    llm = AsyncMock()
    llm.return_value = {"content": json_text}
    return llm


def _clean_check_llm() -> AsyncMock:
    """两项 LLM 审查(dialogue 一致性 / 幻觉扫描)都返回"无违规"。"""
    return _mock_llm('{"violations": []}')


# ── generate_script ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_generate_script_drops_dialogue_without_valid_quote():
    draft = {
        "lines": [
            {
                "act": 1,
                "type": "dialogue",
                "speaker": "C001",
                "text": "编造的台词",
                "event_id": "E002",
                "quote_id": "Q999",
            }
        ]
    }
    llm = _mock_llm(json.dumps(draft, ensure_ascii=False))
    script = await generate_script(_make_constitution(20), CHAPTER_IR, llm=llm)
    assert script.lines == []


@pytest.mark.asyncio
async def test_generate_script_keeps_valid_lines_and_assigns_line_ids():
    llm = _mock_llm(json.dumps(_good_draft(), ensure_ascii=False))
    script = await generate_script(
        _make_constitution(_good_target_duration_sec()), CHAPTER_IR, llm=llm
    )

    assert [ln.line_id for ln in script.lines] == ["LN001", "LN002"]
    assert script.lines[1].type == "dialogue"
    assert script.lines[1].quote_id == "Q001"


@pytest.mark.asyncio
async def test_generate_script_drops_unknown_event_id():
    draft = {"lines": [{"act": 1, "type": "narration", "text": "旁白", "event_id": "E999"}]}
    llm = _mock_llm(json.dumps(draft, ensure_ascii=False))
    script = await generate_script(_make_constitution(20), CHAPTER_IR, llm=llm)
    assert script.lines[0].event_id is None


@pytest.mark.asyncio
async def test_generate_script_degrades_on_llm_failure():
    llm = AsyncMock(side_effect=RuntimeError("network down"))
    script = await generate_script(_make_constitution(20), CHAPTER_IR, llm=llm)
    assert script.lines == []


# ── gate_script ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_gate_script_passes_on_good_script():
    gen_llm = _mock_llm(json.dumps(_good_draft(), ensure_ascii=False))
    constitution = _make_constitution(_good_target_duration_sec())
    script = await generate_script(constitution, CHAPTER_IR, llm=gen_llm)

    result = await gate_script(script, CHAPTER_IR, constitution, llm=_clean_check_llm())
    assert result.passed is True
    assert result.errors == []


@pytest.mark.asyncio
async def test_gate_script_detects_forbidden_term():
    constitution = _make_constitution(_good_target_duration_sec(), forbidden=["带头"])
    gen_llm = _mock_llm(json.dumps(_good_draft(), ensure_ascii=False))
    script = await generate_script(constitution, CHAPTER_IR, llm=gen_llm)

    result = await gate_script(script, CHAPTER_IR, constitution, llm=_clean_check_llm())
    assert result.passed is False
    assert any("命中违禁词" in e for e in result.errors)


@pytest.mark.asyncio
async def test_gate_script_detects_duration_mismatch():
    constitution = _make_constitution(target_duration_sec=1)  # 目标字数远小于实际
    gen_llm = _mock_llm(json.dumps(_good_draft(), ensure_ascii=False))
    script = await generate_script(constitution, CHAPTER_IR, llm=gen_llm)

    result = await gate_script(script, CHAPTER_IR, constitution, llm=_clean_check_llm())
    assert result.passed is False
    assert any("偏差" in e for e in result.errors)


@pytest.mark.asyncio
async def test_gate_script_detects_dialogue_inconsistency():
    constitution = _make_constitution(_good_target_duration_sec())
    gen_llm = _mock_llm(json.dumps(_good_draft(), ensure_ascii=False))
    script = await generate_script(constitution, CHAPTER_IR, llm=gen_llm)

    check_llm = _mock_llm(
        json.dumps({"violations": [{"line_id": "LN002", "reason": "偏离原意"}]}, ensure_ascii=False)
    )
    result = await gate_script(script, CHAPTER_IR, constitution, llm=check_llm)
    assert result.passed is False
    assert any("语义不一致" in e for e in result.errors)


@pytest.mark.asyncio
async def test_gate_script_detects_hallucinated_content():
    constitution = _make_constitution(_good_target_duration_sec())
    gen_llm = _mock_llm(json.dumps(_good_draft(), ensure_ascii=False))
    script = await generate_script(constitution, CHAPTER_IR, llm=gen_llm)

    call_count = 0

    async def fake_llm(*, messages, max_tokens=None):
        nonlocal call_count
        call_count += 1
        content = messages[0]["content"]
        if "忠实改写自原引语" in content:
            return {"content": '{"violations": []}'}
        if "编造的**史实**内容" in content:
            return {
                "content": json.dumps(
                    {"violations": [{"line_id": "LN001", "reason": "原文没有三家大夫赴宴的记载"}]},
                    ensure_ascii=False,
                )
            }
        return {"content": '{"violations": []}'}

    result = await gate_script(script, CHAPTER_IR, constitution, llm=fake_llm)
    assert result.passed is False
    assert any("疑似包含原文没有的情节" in e for e in result.errors)


# ── build_script (点定重写 / 删除降级) ─────────────────────────────────────


@pytest.mark.asyncio
async def test_build_script_rewrites_violating_line_until_pass():
    constitution = _make_constitution(_good_target_duration_sec(), forbidden=["带头"])

    async def fake_llm(*, messages, max_tokens=None):
        content = messages[0]["content"]
        if "你是历史正剧编剧" in content:
            return {"content": json.dumps(_good_draft(), ensure_ascii=False)}
        if "被审查判定违规" in content:
            return {"content": '{"text": "祸乱要来,也得我来挑起,谁人敢应?"}'}
        # 一致性 / 幻觉扫描都放行,只让确定性的违禁词检查触发降级
        return {"content": '{"violations": []}'}

    script, result = await build_script(constitution, CHAPTER_IR, llm=fake_llm)

    assert result.passed is True
    dialogue = next(ln for ln in script.lines if ln.type == "dialogue")
    assert "带头" not in dialogue.text


@pytest.mark.asyncio
async def test_build_script_deletes_line_after_max_rewrite_attempts():
    constitution = _make_constitution(_good_target_duration_sec(), forbidden=["带头"])

    async def fake_llm(*, messages, max_tokens=None):
        content = messages[0]["content"]
        if "你是历史正剧编剧" in content:
            return {"content": json.dumps(_good_draft(), ensure_ascii=False)}
        if "被审查判定违规" in content:
            # 重写永远修不好(依旧命中违禁词),逼出"3 次仍违规 → 删除该行"的降级路径
            return {"content": '{"text": "祸乱要来,也得我来带头挑起"}'}
        return {"content": '{"violations": []}'}

    script, result = await build_script(constitution, CHAPTER_IR, llm=fake_llm)

    # 违规的 dialogue 行重写 3 次仍不过 → 被删除(降级路径生效,不再是 dialogue 行)。
    assert all(ln.type != "dialogue" for ln in script.lines)
    # 删除该行会打破字数匹配(唯一剩下的旁白行太短),这是接受的降级代价,
    # 不再是"命中违禁词"这个已经解决的问题。
    assert not any("命中违禁词" in e for e in result.errors)
    assert any("偏差" in e for e in result.errors)
