"""吕氏五段法固化测试(2026-10-24):modern_echo 段型 + decision_point 抉择点 +
现代词黑名单分段作用域。规范见 docs/rules/history_scene_narrative.md。"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from hevi.studio.mix import plan_history_mix
from hevi.tongjian.authored_episode import (
    AuthoredBeat,
    AuthoredCharacter,
    AuthoredEpisode,
    compile_authored_episode,
)
from hevi.tongjian.event_unit import _VALID_SEGMENT_TYPES, _coerce_segments
from hevi.tongjian.schemas import ChapterIR, ChapterMeta, Constitution, Script, ScriptLine
from hevi.tongjian.script import (
    _check_forbidden_terms,
    _check_modern_echo_placement,
    _coerce_script,
)
from hevi.tongjian.voiceover import _DECISION_HOLD_MS, synthesize_voiceover

_EMPTY_IR = ChapterIR(meta=ChapterMeta(source="test", char_count=0))


def _line(lid: str, type_: str, text: str, **kw) -> ScriptLine:
    return ScriptLine(line_id=lid, type=type_, text=text, **kw)


# ── 黑名单分段作用域 ────────────────────────────────────────────────────────


class TestForbiddenScope:
    def test_modern_word_blocked_in_historical_lines(self):
        script = Script(
            lines=[
                _line("LN001", "narration", "这一幕值得大家点赞。"),
                _line("LN002", "dialogue", "此事就这么定了。", speaker="C001"),
            ]
        )
        errors = _check_forbidden_terms(script, Constitution())
        assert any("点赞" in e and "LN001" in e for e in errors)

    def test_same_word_allowed_in_modern_echo(self):
        script = Script(
            lines=[
                _line("LN001", "narration", "卫鞅立木于南门。"),
                _line("LN002", "modern_echo", "今天我们也会为承诺点赞，也怕被说内卷。"),
            ]
        )
        assert _check_forbidden_terms(script, Constitution()) == []

    def test_constitution_forbidden_also_scoped(self):
        constitution = Constitution(forbidden=["现代梗"])
        script = Script(
            lines=[
                _line("LN001", "commentary", "此评语不带现代梗。"),
                _line("LN002", "modern_echo", "用现代梗讲就是：先把信用做出来。"),
            ]
        )
        errors = _check_forbidden_terms(script, constitution)
        assert errors and all("LN001" in e for e in errors)


# ── modern_echo 结构门 ──────────────────────────────────────────────────────


class TestModernEchoPlacement:
    def test_none_ok(self):
        script = Script(lines=[_line("LN001", "narration", "讲解。")])
        assert _check_modern_echo_placement(script) == []

    def test_single_last_ok(self):
        script = Script(
            lines=[
                _line("LN001", "narration", "讲解。"),
                _line("LN002", "modern_echo", "回到今天。"),
            ]
        )
        assert _check_modern_echo_placement(script) == []

    def test_not_last_rejected(self):
        script = Script(
            lines=[
                _line("LN001", "modern_echo", "回到今天。"),
                _line("LN002", "narration", "讲解。"),
            ]
        )
        assert _check_modern_echo_placement(script)

    def test_two_rejected(self):
        script = Script(
            lines=[
                _line("LN001", "modern_echo", "回到今天。"),
                _line("LN002", "modern_echo", "再回到今天。"),
            ]
        )
        assert _check_modern_echo_placement(script)


# ── L2 coerce:段型与抉择点透传 ──────────────────────────────────────────────


class TestCoerceScript:
    def test_modern_echo_type_preserved_and_zh_alias(self):
        draft = {
            "lines": [
                {"type": "narration", "text": "讲解一句。"},
                {"type": "鉴今", "text": "回到今天收尾。"},
            ]
        }
        script = _coerce_script(draft, _EMPTY_IR)
        assert [ln.type for ln in script.lines] == ["narration", "modern_echo"]

    def test_decision_point_only_on_narration(self):
        draft = {
            "lines": [
                {"type": "narration", "text": "如果是你，你会怎么做？", "decision_point": True},
                {
                    "type": "dialogue",
                    "text": "就这么办。",
                    "speaker": "C001",
                    "dramatized": True,
                    "decision_point": True,
                },
            ]
        }
        script = _coerce_script(draft, _EMPTY_IR)
        assert script.lines[0].decision_point is True
        assert script.lines[1].decision_point is False


# ── L0 选段:modern_echo 不从原文产出 ────────────────────────────────────────


class TestEventUnitSegments:
    def test_modern_echo_is_reserved_type(self):
        assert "modern_echo" in _VALID_SEGMENT_TYPES

    def test_extraction_downgrades_modern_echo(self):
        raw = "衛鞅立木於南門，民莫敢徙。"
        segs = _coerce_segments([{"type": "modern_echo", "text": "衛鞅立木於南門"}], raw)
        assert len(segs) == 1 and segs[0].type == "narration"


# ── L3:抉择点 → 时间轴 hold gap ─────────────────────────────────────────────


def _write_fake_wav(path: Path, duration_ms: int = 1000) -> None:
    sample_rate = 16000
    data_size = int(sample_rate * duration_ms / 1000) * 2
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"RIFF")
        f.write(struct.pack("<I", 36 + data_size))
        f.write(b"WAVE")
        f.write(b"fmt ")
        f.write(struct.pack("<I", 16))
        f.write(struct.pack("<HHIIHH", 1, 1, sample_rate, sample_rate * 2, 2, 16))
        f.write(b"data")
        f.write(struct.pack("<I", data_size))
        f.write(b"\x00" * data_size)


def _mock_tts(duration_ms: int = 1000):
    async def _tts(*, script, output_path, **kwargs):
        _write_fake_wav(Path(output_path), duration_ms)
        return output_path

    return _tts


class TestDecisionHoldGap:
    async def test_hold_gap_inserted_after_decision_line(self, tmp_path):
        script = Script(
            lines=[
                _line("LN001", "narration", "如果是你，你会怎么做？", decision_point=True),
                _line("LN002", "narration", "卫鞅的办法是立木。"),
            ]
        )
        timeline = await synthesize_voiceover(
            script, output_dir=tmp_path, tts_fn=_mock_tts(1000)
        )
        holds = [g for g in timeline.gaps if g.purpose == "decision_point_hold"]
        assert len(holds) == 1
        assert holds[0].after_line == "LN001"
        assert holds[0].duration_ms == _DECISION_HOLD_MS
        # 总时长 = 两行口播 + hold
        assert timeline.total_duration_ms == 1000 + _DECISION_HOLD_MS + 1000

    async def test_no_hold_without_decision_point(self, tmp_path):
        script = Script(lines=[_line("LN001", "narration", "普通讲解。")])
        timeline = await synthesize_voiceover(
            script, output_dir=tmp_path, tts_fn=_mock_tts(1000)
        )
        assert [g for g in timeline.gaps if g.purpose == "decision_point_hold"] == []


# ── 人工撰稿编译:五段结构硬校验 ─────────────────────────────────────────────


def _mini_episode(beats: list[AuthoredBeat]) -> AuthoredEpisode:
    return AuthoredEpisode(
        title="测试集",
        thesis="立意",
        raw_text="原文",
        intro="片头",
        characters=[AuthoredCharacter(id="C1", name="甲", appearance="甲")],
        locations={"S1": "场景一"},
        beats=beats,
    )


def _narr(text: str = "讲解。", **kw) -> AuthoredBeat:
    return AuthoredBeat(kind="narration", scene="S1", text=text, visual_prompt="画面", **kw)


class TestAuthoredFivePart:
    def test_valid_five_part_compiles(self):
        ep = _mini_episode(
            [
                _narr("现场。", section="现场"),
                _narr("如果是你？", section="代入", decision_point=True),
                AuthoredBeat(kind="dialogue", scene="S1", speaker="C1", text="就这么办。"),
                AuthoredBeat(
                    kind="modern_echo",
                    scene="S1",
                    text="回到今天，我们也该先兑现承诺，别怕被说内卷。",
                    visual_prompt="现代画面",
                    section="鉴今",
                ),
            ]
        )
        compiled = compile_authored_episode(ep)
        types = [ln.type for ln in compiled.script.lines]
        assert types == ["narration", "narration", "dialogue", "modern_echo"]
        assert compiled.script.lines[1].decision_point is True

    def test_two_modern_echo_rejected(self):
        ep = _mini_episode(
            [
                AuthoredBeat(kind="modern_echo", scene="S1", text="一", visual_prompt="画"),
                AuthoredBeat(kind="modern_echo", scene="S1", text="二", visual_prompt="画"),
            ]
        )
        with pytest.raises(ValueError, match="至多一段"):
            compile_authored_episode(ep)

    def test_modern_echo_not_last_rejected(self):
        ep = _mini_episode(
            [
                AuthoredBeat(kind="modern_echo", scene="S1", text="鉴今", visual_prompt="画"),
                _narr("讲解。"),
            ]
        )
        with pytest.raises(ValueError, match="最后一个"):
            compile_authored_episode(ep)

    def test_decision_point_on_dialogue_rejected(self):
        ep = _mini_episode(
            [
                AuthoredBeat(
                    kind="dialogue", scene="S1", speaker="C1", text="台词。", decision_point=True
                )
            ]
        )
        with pytest.raises(ValueError, match="只能标在 narration"):
            compile_authored_episode(ep)

    def test_two_decision_points_rejected(self):
        ep = _mini_episode(
            [_narr("问一？", decision_point=True), _narr("问二？", decision_point=True)]
        )
        with pytest.raises(ValueError, match="至多一处"):
            compile_authored_episode(ep)


# ── studio cue 层:decision_hold 标记 ────────────────────────────────────────


class TestMixDecisionHold:
    async def test_cue_stamped_with_decision_hold(self):
        script = Script(
            lines=[
                _line("LN001", "narration", "如果是你，你会怎么做？", decision_point=True),
                _line("LN002", "narration", "后来卫鞅立木。"),
            ]
        )
        mix = await plan_history_mix(script)
        assert len(mix.commentary_cues) == 2
        assert mix.commentary_cues[0]["visual_config"]["decision_hold"] == {
            "pause_s": 3.0,
            "on_screen_question": True,
        }
        assert "decision_hold" not in (mix.commentary_cues[1].get("visual_config") or {})
