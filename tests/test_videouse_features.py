"""video-use 11 项能力接入测试（对标 browser-use/video-use）。

覆盖：
  1. Scribe service（词级时间戳 + 说话人 + 音频事件）
  2. Color grade（ASC CDL + 预设扩展 + per-segment）
  3. Take selector（多 take beat 选择）
  4. Session memory（project.md 持久化）
  5. Animation overlay（多引擎 overlay 计划）
  6. Subtitle styles（bold-overlay + natural-sentence + karaoke ASS）
  7. Timeline view 增强（词标注 + 文本摘要）
  8. Strategy enforcement（确认流程追踪）
  9. 集成 / 端到端契约
"""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path

import pytest


# ═══════════════════════════════════════════════════════════════════════
# 1. Scribe service
# ═══════════════════════════════════════════════════════════════════════

class TestScribeService:
    """ElevenLabs Scribe 词级转写服务。"""

    def test_scribe_word_basic(self):
        from hevi.assembly.scribe_service import ScribeWord

        w = ScribeWord("hello", 0.0, 0.5, "SPEAKER_00", 0.95)
        assert w.word == "hello"
        assert w.start == 0.0
        assert w.end == 0.5
        assert w.duration == 0.5
        assert w.speaker == "SPEAKER_00"
        assert w.confidence == 0.95
        assert not w.is_event

    def test_scribe_word_event(self):
        from hevi.assembly.scribe_service import ScribeWord

        w = ScribeWord("(laughter)", 1.0, 1.5, "", 1.0, type="event")
        assert w.is_event
        assert w.word == "(laughter)"

    def test_scribe_transcript_to_dict(self):
        from hevi.assembly.scribe_service import (
            ScribeTranscript,
            ScribeUtterance,
            ScribeWord,
        )

        t = ScribeTranscript(
            text="hello world",
            words=[
                ScribeWord("hello", 0.0, 0.5, "SPEAKER_00"),
                ScribeWord("world", 0.6, 1.0, "SPEAKER_00"),
            ],
            utterances=[
                ScribeUtterance("SPEAKER_00", start=0.0, end=1.0, text="hello world"),
            ],
            language="en",
            duration_s=1.0,
        )
        d = t.to_dict()
        assert d["text"] == "hello world"
        assert len(d["words"]) == 2
        assert len(d["utterances"]) == 1
        assert d["language"] == "en"

    def test_scribe_transcript_roundtrip(self):
        from hevi.assembly.scribe_service import (
            ScribeTranscript,
            ScribeWord,
        )

        t = ScribeTranscript(
            text="test",
            words=[
                ScribeWord("test", 0.0, 0.5, "S1", 0.9),
            ],
            language="zh",
            duration_s=0.5,
        )
        d = t.to_dict()
        t2 = ScribeTranscript.from_dict(d)
        assert t2.text == t.text
        assert len(t2.words) == len(t.words)
        assert t2.words[0].word == "test"
        assert t2.words[0].confidence == 0.9

    def test_find_word_gaps(self):
        from hevi.assembly.scribe_service import ScribeWord, find_word_gaps

        words = [
            ScribeWord("a", 0.0, 0.3, "S1"),
            ScribeWord("b", 0.5, 0.8, "S1"),  # gap 0.2s
            ScribeWord("c", 0.9, 1.0, "S1"),  # gap 0.1s
            ScribeWord("d", 1.5, 1.8, "S1"),  # gap 0.5s
        ]
        gaps = find_word_gaps(words, min_gap_s=0.05)
        # gap between a→b: 0.5-0.3=0.2 ≥ 0.05 ✓
        # gap between b→c: 0.9-0.8=0.1 ≥ 0.05 ✓
        # gap between c→d: 1.5-1.0=0.5 ≥ 0.05 ✓
        assert len(gaps) == 3
        assert gaps[0].gap_duration == pytest.approx(0.2)
        assert gaps[1].gap_duration == pytest.approx(0.1)
        assert gaps[2].gap_duration == pytest.approx(0.5)

    def test_find_word_gaps_skips_events(self):
        from hevi.assembly.scribe_service import ScribeWord, find_word_gaps

        words = [
            ScribeWord("a", 0.0, 0.3, "S1"),
            ScribeWord("(silence)", 0.3, 0.8, "", 1.0, type="event"),
            ScribeWord("b", 1.0, 1.5, "S1"),
        ]
        gaps = find_word_gaps(words, min_gap_s=0.05)
        # a→event: skipped (event)
        # event→b: skipped (event)
        assert len(gaps) == 0

    def test_find_best_gap(self):
        from hevi.assembly.scribe_service import ScribeWord, find_best_gap, find_word_gaps

        words = [
            ScribeWord("a", 0.0, 0.3, "S1"),
            ScribeWord("b", 0.8, 1.0, "S1"),
            ScribeWord("c", 2.0, 2.3, "S1"),
        ]
        gaps = find_word_gaps(words)
        best = find_best_gap(gaps, target_t=0.5)
        assert best is not None
        assert best.gap_start == pytest.approx(0.3)  # gap a→b

    def test_find_best_gap_empty(self):
        from hevi.assembly.scribe_service import find_best_gap

        assert find_best_gap([], target_t=1.0) is None

    def test_mock_scribe_client(self):
        from hevi.assembly.scribe_service import MockScribeClient

        client = MockScribeClient()
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(
                client.transcribe("/fake/audio.wav", language="en")
            )
        finally:
            loop.close()
        assert result.text == "hello world this is a test"
        assert len(result.words) == 7
        assert result.language == "en"
        assert any(w.is_event for w in result.words)

    def test_mock_scribe_client_preset(self):
        from hevi.assembly.scribe_service import (
            MockScribeClient,
            ScribeTranscript,
            ScribeWord,
        )

        preset = ScribeTranscript(
            text="custom",
            words=[ScribeWord("custom", 0.0, 0.5)],
            language="zh",
            duration_s=0.5,
        )
        client = MockScribeClient(preset=preset)
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(client.transcribe("/fake.wav"))
        finally:
            loop.close()
        assert result.text == "custom"
        assert result.language == "zh"

    def test_to_edit_words(self):
        from hevi.assembly.scribe_service import (
            ScribeTranscript,
            ScribeWord,
            to_edit_words,
        )

        t = ScribeTranscript(
            text="hi",
            words=[
                ScribeWord("hi", 0.0, 0.3, "S1"),
                ScribeWord("(noise)", 0.3, 0.5, "", 1.0, type="event"),
                ScribeWord("bye", 0.5, 0.8, "S1"),
            ],
        )
        edit_words = to_edit_words(t, skip_events=True)
        assert len(edit_words) == 2
        assert edit_words[0].word == "hi"
        assert edit_words[1].word == "bye"

    def test_extract_audio_events(self):
        from hevi.assembly.scribe_service import (
            ScribeTranscript,
            ScribeWord,
            extract_audio_events,
        )

        t = ScribeTranscript(
            text="",
            words=[
                ScribeWord("hello", 0.0, 0.5),
                ScribeWord("(laughter)", 0.5, 1.0, type="event"),
                ScribeWord("world", 1.0, 1.5),
                ScribeWord("(applause)", 1.5, 2.0, type="event"),
            ],
        )
        events = extract_audio_events(t)
        assert len(events) == 2
        assert events[0].word == "(laughter)"
        assert events[1].word == "(applause)"

    def test_speaker_segments(self):
        from hevi.assembly.scribe_service import (
            ScribeTranscript,
            ScribeUtterance,
            ScribeWord,
            speaker_segments,
        )

        t = ScribeTranscript(
            text="",
            utterances=[
                ScribeUtterance("S1", [ScribeWord("a", 0.0, 0.3)], 0.0, 0.3, "a"),
                ScribeUtterance("S2", [ScribeWord("b", 0.5, 0.8)], 0.5, 0.8, "b"),
                ScribeUtterance("S1", [ScribeWord("c", 1.0, 1.3)], 1.0, 1.3, "c"),
            ],
        )
        segs = speaker_segments(t)
        assert len(segs) == 3
        assert segs[0]["speaker"] == "S1"
        assert segs[1]["speaker"] == "S2"
        assert segs[2]["speaker"] == "S1"

    def test_audio_events_constants(self):
        from hevi.assembly.scribe_service import AUDIO_EVENTS

        assert "(laughter)" in AUDIO_EVENTS
        assert "(applause)" in AUDIO_EVENTS
        assert "(sigh)" in AUDIO_EVENTS
        assert "(music)" in AUDIO_EVENTS


# ═══════════════════════════════════════════════════════════════════════
# 2. Color grade
# ═══════════════════════════════════════════════════════════════════════

class TestColorGrade:
    """扩展调色系统。"""

    def test_asccdl_default(self):
        from hevi.assembly.color_grade import ASCCDL

        cdl = ASCCDL()
        assert cdl.slope == (1.0, 1.0, 1.0)
        assert cdl.offset == (0.0, 0.0, 0.0)
        assert cdl.saturation == 1.0

    def test_asccdl_to_vf(self):
        from hevi.assembly.color_grade import ASCCDL

        cdl = ASCCDL(
            slope=(1.1, 1.0, 0.9),
            offset=(0.02, 0.0, -0.01),
            saturation=0.8,
        )
        vf = cdl.to_vf()
        assert "saturation=0.8" in vf
        assert "colorbalance" in vf

    def test_asccdl_to_vf_identity(self):
        from hevi.assembly.color_grade import ASCCDL

        cdl = ASCCDL()
        vf = cdl.to_vf()
        assert vf == "null"

    def test_grade_presets_exist(self):
        from hevi.assembly.color_grade import GRADE_PRESETS

        expected = [
            "warm_cinematic", "neutral_punch", "teal_orange",
            "desaturated", "vintage", "high_contrast", "cool_blue",
            "golden_hour", "noir", "pastel", "bleach_bypass",
        ]
        for name in expected:
            assert name in GRADE_PRESETS, f"missing preset: {name}"

    def test_resolve_grade_preset(self):
        from hevi.assembly.color_grade import resolve_grade

        vf = resolve_grade("warm_cinematic")
        assert vf is not None
        assert "saturation" in vf

    def test_resolve_grade_none(self):
        from hevi.assembly.color_grade import resolve_grade

        assert resolve_grade("") is None
        assert resolve_grade("none") is None
        assert resolve_grade("null") is None

    def test_resolve_grade_custom(self):
        from hevi.assembly.color_grade import resolve_grade

        vf = resolve_grade("eq=brightness=0.05,curves=vintage")
        assert vf == "eq=brightness=0.05,curves=vintage"

    def test_resolve_grade_multi(self):
        from hevi.assembly.color_grade import resolve_grade

        vf = resolve_grade("warm_cinematic,neutral_punch")
        assert vf is not None
        # Should contain parts from both presets
        assert "saturation" in vf

    def test_list_presets(self):
        from hevi.assembly.color_grade import list_presets

        presets = list_presets()
        assert len(presets) >= 10
        assert "warm_cinematic" in presets
        assert "noir" in presets

    def test_segment_grade(self):
        from hevi.assembly.color_grade import SegmentGrade

        sg = SegmentGrade(range_index=0, grade="warm_cinematic")
        vf = sg.resolve_vf()
        assert vf is not None

    def test_segment_grade_with_cdl(self):
        from hevi.assembly.color_grade import ASCCDL, SegmentGrade

        cdl = ASCCDL(saturation=0.7)
        sg = SegmentGrade(range_index=1, grade="", cdl=cdl)
        vf = sg.resolve_vf()
        assert "saturation=0.7" in vf

    def test_grade_pipeline(self):
        from hevi.assembly.color_grade import GradePipeline, SegmentGrade

        pipe = GradePipeline(
            default_grade="warm_cinematic",
            segment_grades=[
                SegmentGrade(range_index=0, grade="noir"),
                SegmentGrade(range_index=2, grade="cool_blue"),
            ],
        )
        # Segment 0 → noir
        vf0 = pipe.get_grade_for_segment(0)
        assert vf0 is not None
        assert "saturation=0.0" in vf0  # noir is desaturated

        # Segment 1 → default (warm_cinematic)
        vf1 = pipe.get_grade_for_segment(1)
        assert vf1 is not None

        # Segment 2 → cool_blue
        vf2 = pipe.get_grade_for_segment(2)
        assert vf2 is not None

        # Segment 3 → default
        vf3 = pipe.get_grade_for_segment(3)
        assert vf3 is not None

    def test_grade_pipeline_to_dict(self):
        from hevi.assembly.color_grade import ASCCDL, GradePipeline, SegmentGrade

        pipe = GradePipeline(
            default_grade="none",
            segment_grades=[
                SegmentGrade(range_index=0, grade="vintage", cdl=ASCCDL(saturation=0.8)),
            ],
        )
        d = pipe.to_dict()
        assert d["default_grade"] == "none"
        assert len(d["segment_grades"]) == 1
        assert d["segment_grades"][0]["grade"] == "vintage"
        assert d["segment_grades"][0]["cdl"]["saturation"] == 0.8

    def test_build_grade_filter(self):
        from hevi.assembly.color_grade import build_grade_filter

        vf = build_grade_filter("warm_cinematic")
        assert vf is not None
        assert "saturation" in vf

    def test_build_grade_filter_preview(self):
        from hevi.assembly.color_grade import build_grade_filter

        vf = build_grade_filter("warm_cinematic", preview=True)
        assert vf is not None
        assert "scale=1280:-2" in vf

    def test_build_grade_filter_extra(self):
        from hevi.assembly.color_grade import build_grade_filter

        vf = build_grade_filter("none", extra_filters=["eq=brightness=0.05"])
        assert vf == "eq=brightness=0.05"

    def test_build_grade_filter_none(self):
        from hevi.assembly.color_grade import build_grade_filter

        assert build_grade_filter("none") is None
        assert build_grade_filter("") is None


# ═══════════════════════════════════════════════════════════════════════
# 3. Take selector
# ═══════════════════════════════════════════════════════════════════════

class TestTakeSelector:
    """多 take beat 选择器。"""

    def test_take_beat_score(self):
        from hevi.assembly.take_selector import TakeBeat

        tb = TakeBeat(
            take_id="take_0",
            beat="intro",
            start=0.0,
            end=5.0,
            fluency=0.8,
            energy=0.7,
            completeness=0.9,
        )
        score = tb.compute_score()
        expected = 0.8 * 0.4 + 0.7 * 0.3 + 0.9 * 0.3
        assert score == pytest.approx(expected)

    def test_take_beat_custom_weights(self):
        from hevi.assembly.take_selector import TakeBeat

        tb = TakeBeat(
            take_id="t0", beat="b1", start=0.0, end=1.0,
            fluency=1.0, energy=0.0, completeness=0.0,
        )
        score = tb.compute_score(weights={"fluency": 1.0, "energy": 0.0, "completeness": 0.0})
        assert score == pytest.approx(1.0)

    def test_take_set_properties(self):
        from hevi.assembly.take_selector import TakeBeat, TakeSet

        ts = TakeSet(beats={
            "intro": [
                TakeBeat("t0", "intro", 0.0, 5.0),
                TakeBeat("t1", "intro", 0.0, 5.0),
            ],
            "body": [
                TakeBeat("t0", "body", 5.0, 15.0),
            ],
        })
        assert ts.beat_names == ["intro", "body"]
        assert set(ts.take_ids) == {"t0", "t1"}

    def test_select_best_takes_auto(self):
        from hevi.assembly.take_selector import TakeBeat, TakeSet, select_best_takes

        ts = TakeSet(beats={
            "intro": [
                TakeBeat("t0", "intro", 0.0, 5.0, fluency=0.5, energy=0.5, completeness=0.5),
                TakeBeat("t1", "intro", 0.0, 5.0, fluency=0.9, energy=0.8, completeness=0.9),
            ],
        })
        # Pre-compute scores
        for candidates in ts.beats.values():
            for c in candidates:
                c.compute_score()

        result = select_best_takes(ts)
        assert result.strategy == "auto"
        assert "intro" in result.selections
        assert result.selections["intro"].take_id == "t1"
        assert result.total_score > 0

    def test_select_best_takes_manual(self):
        from hevi.assembly.take_selector import TakeBeat, TakeSet, select_best_takes

        ts = TakeSet(beats={
            "intro": [
                TakeBeat("t0", "intro", 0.0, 5.0, fluency=0.9, energy=0.9, completeness=0.9),
                TakeBeat("t1", "intro", 0.0, 5.0, fluency=0.3, energy=0.3, completeness=0.3),
            ],
        })
        for candidates in ts.beats.values():
            for c in candidates:
                c.compute_score()

        # Manual override: pick t1 even though t0 has higher score
        result = select_best_takes(ts, manual_overrides={"intro": "t1"})
        assert result.strategy == "manual"
        assert result.selections["intro"].take_id == "t1"

    def test_selection_to_edit_ranges(self):
        from hevi.assembly.take_selector import SelectionResult, TakeBeat

        result = SelectionResult(
            selections={
                "intro": TakeBeat("t1", "intro", 0.0, 5.0, score=0.85),
                "body": TakeBeat("t0", "body", 5.0, 15.0, score=0.72),
            },
            total_score=1.57,
        )
        ranges = result.to_edit_ranges(source_key="main.mp4")
        assert len(ranges) == 2
        assert ranges[0].source == "main.mp4"
        assert ranges[0].beat == "body"  # sorted by beat_name
        assert "t0" in ranges[0].reason

    def test_selection_to_dict(self):
        from hevi.assembly.take_selector import SelectionResult, TakeBeat

        result = SelectionResult(
            selections={
                "intro": TakeBeat("t1", "intro", 0.0, 5.0, score=0.8),
            },
            strategy="auto",
        )
        d = result.to_dict()
        assert d["strategy"] == "auto"
        assert "intro" in d["selections"]

    def test_build_take_set_from_words(self):
        from hevi.assembly.edit_craft import Word
        from hevi.assembly.take_selector import build_take_set_from_words

        take_words = {
            "t0": [Word("a", 0.0, 0.3), Word("b", 0.3, 0.6), Word("c", 2.0, 2.3)],
            "t1": [Word("a", 0.0, 0.3), Word("b", 0.4, 0.7)],
        }
        beats = [
            {"beat": "first", "start": 0.0, "end": 1.0},
            {"beat": "second", "start": 2.0, "end": 3.0},
        ]
        ts = build_take_set_from_words(take_words, beats)
        assert "first" in ts.beats
        assert "second" in ts.beats
        assert len(ts.beats["first"]) == 2  # both takes have words in [0,1]
        assert len(ts.beats["second"]) == 1  # only t0


# ═══════════════════════════════════════════════════════════════════════
# 4. Session memory
# ═══════════════════════════════════════════════════════════════════════

class TestSessionMemory:
    """project.md 会话持久化。"""

    def test_session_memory_basic(self):
        from hevi.assembly.session_memory import SessionMemory

        mem = SessionMemory(strategy="使用 warm_cinematic 调色")
        assert mem.strategy == "使用 warm_cinematic 调色"
        assert len(mem.decisions) == 0

    def test_add_decision(self):
        from hevi.assembly.session_memory import SessionMemory

        mem = SessionMemory()
        d = mem.add_decision("cut intro short", "energy too low", source="agent")
        assert d.what == "cut intro short"
        assert d.why == "energy too low"
        assert d.source == "agent"
        assert d.when  # auto-timestamped
        assert len(mem.decisions) == 1

    def test_add_reasoning(self):
        from hevi.assembly.session_memory import SessionMemory

        mem = SessionMemory()
        mem.add_reasoning("intro 部分语气较弱，考虑从 body 开始")
        assert len(mem.reasoning) == 1

    def test_outstanding_lifecycle(self):
        from hevi.assembly.session_memory import SessionMemory

        mem = SessionMemory()
        mem.add_outstanding("需要确认字幕语言", priority="high", blocker=True)
        assert len(mem.outstanding) == 1
        assert mem.outstanding[0].blocker

        resolved = mem.resolve_outstanding("需要确认字幕语言")
        assert resolved
        assert len(mem.outstanding) == 0

    def test_resolve_nonexistent(self):
        from hevi.assembly.session_memory import SessionMemory

        mem = SessionMemory()
        assert not mem.resolve_outstanding("nonexistent")

    def test_to_dict(self):
        from hevi.assembly.session_memory import SessionMemory

        mem = SessionMemory(strategy="test")
        mem.add_decision("d1", "r1")
        mem.add_outstanding("o1", "low")
        d = mem.to_dict()
        assert d["strategy"] == "test"
        assert len(d["decisions"]) == 1
        assert len(d["outstanding"]) == 1

    def test_save_and_load_project_md(self):
        from hevi.assembly.session_memory import (
            SessionMemory,
            load_project_md,
            save_project_md,
        )

        mem = SessionMemory(
            strategy="选择 take_1 作为主 take，因为流畅度最高",
            constraints=["时长不超过 60 秒", "必须有字幕"],
        )
        mem.metadata["project"] = "demo"
        mem.metadata["version"] = "2"
        mem.add_decision("使用 warm_cinematic", "与品牌调性一致", source="user")
        mem.add_decision("cut at 5.0s", "此处有自然停顿", source="agent")
        mem.add_reasoning("take_0 有背景噪音，take_1 更清晰")
        mem.add_outstanding("确认结尾淡出时长", priority="medium")
        mem.add_outstanding("字幕字体待确认", priority="high", blocker=True)

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "project.md"
            save_project_md(mem, path)

            assert path.exists()
            content = path.read_text(encoding="utf-8")
            assert "# Project Memory" in content
            assert "warm_cinematic" in content
            assert "字幕" in content

            # Load back
            loaded = load_project_md(path)
            assert loaded.strategy == mem.strategy
            assert len(loaded.decisions) == 2
            assert len(loaded.reasoning) == 1
            assert len(loaded.outstanding) == 2
            assert loaded.metadata["project"] == "demo"

    def test_load_nonexistent(self):
        from hevi.assembly.session_memory import load_project_md

        mem = load_project_md(Path("/nonexistent/project.md"))
        assert mem.strategy == ""
        assert len(mem.decisions) == 0

    def test_load_or_create(self):
        from hevi.assembly.session_memory import load_or_create

        with tempfile.TemporaryDirectory() as td:
            mem = load_or_create(Path(td))
            assert mem.strategy == ""

    def test_save_convenience(self):
        from hevi.assembly.session_memory import SessionMemory, save

        mem = SessionMemory(strategy="test")
        with tempfile.TemporaryDirectory() as td:
            save(mem, Path(td))
            assert (Path(td) / "project.md").exists()


# ═══════════════════════════════════════════════════════════════════════
# 5. Animation overlay
# ═══════════════════════════════════════════════════════════════════════

class TestAnimationOverlay:
    """动画 overlay 计划系统。"""

    def test_overlay_task(self):
        from hevi.assembly.animation_overlay import OverlayTask

        task = OverlayTask(
            task_id="anim_001",
            engine="pil",
            spec={"text": "Hello", "width": 1920},
            start_in_output=5.0,
            duration=3.0,
        )
        assert task.task_id == "anim_001"
        assert task.engine == "pil"
        assert task.status == "pending"

    def test_overlay_task_to_spec(self):
        from hevi.assembly.animation_overlay import OverlayTask

        task = OverlayTask(
            task_id="x",
            engine="hyperframes",
            spec={},
            start_in_output=2.0,
            duration=1.5,
            output_path=Path("/tmp/overlay.mp4"),
        )
        spec = task.to_overlay_spec()
        assert spec["file"] == "/tmp/overlay.mp4"
        assert spec["start_in_output"] == 2.0
        assert spec["duration"] == 1.5

    def test_overlay_plan(self):
        from hevi.assembly.animation_overlay import OverlayPlan

        plan = OverlayPlan(parallel=True)
        t1 = plan.add_task("t1", "pil", {"text": "A"}, start=0.0, duration=2.0)
        t2 = plan.add_task("t2", "hyperframes", {"html": "<div>"}, start=3.0, duration=4.0)
        assert len(plan.tasks) == 2
        assert t1.task_id == "t1"
        assert t2.duration == 4.0

    def test_get_successful_overlays(self):
        from hevi.assembly.animation_overlay import OverlayTask, get_successful_overlays

        tasks = [
            OverlayTask("t1", "pil", {}, 0.0, 2.0,
                        output_path=Path("/tmp/t1.mp4"), status="done"),
            OverlayTask("t2", "manim", {}, 3.0, 4.0, status="failed", error="no manim"),
            OverlayTask("t3", "hyperframes", {}, 7.0, 3.0, status="pending"),
        ]
        # Mock exists check — done tasks with nonexistent path won't pass
        # We need to create a temp file for t1
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            Path(f.name).write_bytes(b"\x00" * 100)
            tasks[0].output_path = Path(f.name)

        result = get_successful_overlays(tasks)
        assert len(result) == 1
        assert result[0]["start_in_output"] == 0.0

        # Cleanup
        tasks[0].output_path.unlink(missing_ok=True)

    def test_overlay_plan_sequential(self):
        from hevi.assembly.animation_overlay import OverlayPlan

        plan = OverlayPlan(parallel=False)
        plan.add_task("s1", "pil", {}, start=0.0, duration=1.0)
        assert not plan.parallel


# ═══════════════════════════════════════════════════════════════════════
# 6. Subtitle styles
# ═══════════════════════════════════════════════════════════════════════

class TestSubtitleStyles:
    """字幕样式系统。"""

    def test_subtitle_style_basic(self):
        from hevi.assembly.subtitle_styles import SubtitleStyle

        style = SubtitleStyle(name="test", font_size=24)
        assert style.name == "test"
        assert style.font_size == 24

    def test_to_force_style(self):
        from hevi.assembly.subtitle_styles import SubtitleStyle

        style = SubtitleStyle(
            name="test",
            font_size=28,
            bold=True,
            outline=3,
            margin_v=40,
        )
        fs = style.to_force_style()
        assert "FontSize=28" in fs
        assert "Bold=1" in fs
        assert "Outline=3" in fs
        assert "MarginV=40" in fs
        assert "Noto Sans CJK SC" in fs  # CJK font always present

    def test_presets_exist(self):
        from hevi.assembly.subtitle_styles import SUBTITLE_STYLES

        expected = [
            "default", "bold_yellow", "large_white", "compact",
            "bold_overlay", "natural_sentence", "karaoke", "cinematic",
        ]
        for name in expected:
            assert name in SUBTITLE_STYLES, f"missing preset: {name}"

    def test_list_styles(self):
        from hevi.assembly.subtitle_styles import list_styles

        styles = list_styles()
        assert len(styles) >= 8
        assert "bold_overlay" in styles
        assert "karaoke" in styles

    def test_get_style(self):
        from hevi.assembly.subtitle_styles import get_style

        s = get_style("bold_overlay")
        assert s.name == "bold_overlay"
        assert s.bold

    def test_get_style_fallback(self):
        from hevi.assembly.subtitle_styles import get_style

        s = get_style("nonexistent")
        assert s.name == "default"

    def test_build_ass_header(self):
        from hevi.assembly.subtitle_styles import SubtitleStyle, build_ass_header

        style = SubtitleStyle(name="test", font_size=24)
        header = build_ass_header(style)
        assert "[Script Info]" in header
        assert "[V4+ Styles]" in header
        assert "[Events]" in header
        assert "Format:" in header

    def test_cues_to_ass(self):
        from hevi.assembly.edit_craft import SubtitleCue
        from hevi.assembly.subtitle_styles import SubtitleStyle, cues_to_ass

        cues = [
            SubtitleCue(start=0.0, end=2.0, text="你好世界"),
            SubtitleCue(start=3.0, end=5.0, text="Hello world"),
        ]
        style = SubtitleStyle(name="test", font_size=24)
        ass = cues_to_ass(cues, style)
        assert "Dialogue:" in ass
        assert "你好世界" in ass
        assert "Hello world" in ass

    def test_cues_to_ass_highlight(self):
        from hevi.assembly.edit_craft import SubtitleCue
        from hevi.assembly.subtitle_styles import SubtitleStyle, cues_to_ass

        cues = [SubtitleCue(start=0.0, end=2.0, text="这是重要的关键词")]
        style = SubtitleStyle(name="test")
        ass = cues_to_ass(cues, style, highlight_words=["关键词"])
        assert r"\b1" in ass  # bold on
        assert r"\b0" in ass  # bold off

    def test_cues_to_karaoke_ass(self):
        from hevi.assembly.edit_craft import SubtitleCue
        from hevi.assembly.subtitle_styles import SubtitleStyle, cues_to_karaoke_ass

        cues = [SubtitleCue(start=0.0, end=2.0, text="hello world")]
        words_with_timing = [
            {"word": "hello", "start": 0.0, "end": 1.0},
            {"word": "world", "start": 1.0, "end": 2.0},
        ]
        style = SubtitleStyle(name="test")
        ass = cues_to_karaoke_ass(cues, style, words_with_timing=words_with_timing)
        assert r"\k" in ass  # karaoke effect

    def test_build_subtitle_filter_srt(self):
        from hevi.assembly.subtitle_styles import build_subtitle_filter

        f = build_subtitle_filter(Path("/tmp/test.srt"), "bold_overlay")
        assert "subtitles=" in f
        assert "force_style=" in f
        assert "Noto Sans CJK SC" in f

    def test_build_subtitle_filter_ass(self):
        from hevi.assembly.subtitle_styles import build_subtitle_filter

        f = build_subtitle_filter(Path("/tmp/test.ass"))
        assert "subtitles=" in f
        assert "force_style" not in f  # ASS uses embedded styles

    def test_ass_time_format(self):
        from hevi.assembly.subtitle_styles import _ass_time

        assert _ass_time(0.0) == "0:00:00.00"
        assert _ass_time(1.5) == "0:00:01.50"
        assert _ass_time(65.25) == "0:01:05.25"
        assert _ass_time(3661.0) == "1:01:01.00"


# ═══════════════════════════════════════════════════════════════════════
# 7. Timeline view enhancements
# ═══════════════════════════════════════════════════════════════════════

class TestTimelineViewEnhancements:
    """timeline_view 增强功能。"""

    def test_compute_word_labels(self):
        from hevi.assembly.timeline_view import compute_word_labels

        words = [
            type("W", (), {"word": "a", "start": 0.0, "end": 0.5, "speaker": "S1"}),
            type("W", (), {"word": "b", "start": 0.5, "end": 1.0, "speaker": "S1"}),
            type("W", (), {"word": "c", "start": 2.0, "end": 2.5, "speaker": "S2"}),
        ]
        labels = compute_word_labels(words, 0.0, 2.0)
        assert len(labels) == 3  # all within [0, 2]

    def test_compute_word_labels_filtered(self):
        from hevi.assembly.timeline_view import compute_word_labels

        words = [
            type("W", (), {"word": "a", "start": 0.0, "end": 0.5, "speaker": ""}),
            type("W", (), {"word": "b", "start": 5.0, "end": 5.5, "speaker": ""}),
        ]
        labels = compute_word_labels(words, 4.0, 6.0)
        assert len(labels) == 1
        assert labels[0].word == "b"

    def test_word_label_x_ratio(self):
        from hevi.assembly.timeline_view import compute_word_labels

        words = [
            type("W", (), {"word": "mid", "start": 5.0, "end": 5.5, "speaker": ""}),
        ]
        labels = compute_word_labels(words, 0.0, 10.0)
        assert labels[0].x_ratio == pytest.approx(0.5)

    def test_compute_word_labels_empty_window(self):
        from hevi.assembly.timeline_view import compute_word_labels

        words = [type("W", (), {"word": "a", "start": 0.0, "end": 0.5, "speaker": ""})]
        labels = compute_word_labels(words, 1.0, 1.0)
        assert labels == []

    def test_timeline_summary_text(self):
        from hevi.assembly.timeline_view import timeline_summary_text

        ranges = [
            type("R", (), {"start": 0.0, "end": 5.0, "beat": "intro", "quote": "hello"})(),
            type("R", (), {"start": 5.0, "end": 15.0, "beat": "body", "quote": "main"})(),
        ]
        text = timeline_summary_text(ranges, grade="warm_cinematic", words=[1, 2, 3])
        assert "Timeline Summary" in text
        assert "intro" in text
        assert "body" in text
        assert "warm_cinematic" in text
        assert "Words: 3" in text
        assert "Total: 15.00s" in text
        assert "2 segments" in text

    def test_timeline_summary_dict_ranges(self):
        from hevi.assembly.timeline_view import timeline_summary_text

        ranges = [
            {"start": 0.0, "end": 3.0, "beat": "a"},
            {"start": 3.0, "end": 6.0, "beat": "b"},
        ]
        text = timeline_summary_text(ranges)
        assert "Total: 6.00s" in text

    def test_cut_times_from_ranges(self):
        from hevi.assembly.timeline_view import cut_times_from_ranges

        ranges = [
            type("R", (), {"start": 0.0, "end": 5.0})(),
            type("R", (), {"start": 5.0, "end": 10.0})(),
            type("R", (), {"start": 10.0, "end": 15.0})(),
        ]
        cuts = cut_times_from_ranges(ranges)
        assert len(cuts) == 2
        assert cuts[0] == pytest.approx(5.0)
        assert cuts[1] == pytest.approx(10.0)


# ═══════════════════════════════════════════════════════════════════════
# 8. Strategy enforcement
# ═══════════════════════════════════════════════════════════════════════

class TestStrategyEnforcement:
    """策略确认执行层。"""

    def test_gate_lifecycle(self):
        from hevi.assembly.strategy_enforcement import (
            ConfirmationStatus,
            StrategyGate,
            StrategyProposal,
        )

        gate = StrategyGate()
        assert gate.status == ConfirmationStatus.PENDING
        assert not gate.is_confirmed

        gate.propose(StrategyProposal(
            summary="选择 take_1",
            rationale="流畅度最高",
        ))
        assert gate.status == ConfirmationStatus.PROPOSED

        gate.confirm(by="user")
        assert gate.is_confirmed
        assert gate.status == ConfirmationStatus.CONFIRMED

        gate.enforce()  # Should not raise
        gate.mark_executed()
        assert gate.status == ConfirmationStatus.PENDING  # reset after execute

    def test_gate_enforce_without_confirm(self):
        from hevi.assembly.strategy_enforcement import StrategyGate, StrategyProposal

        gate = StrategyGate()
        gate.propose(StrategyProposal(summary="test", rationale="test"))

        from hevi.assembly.edit_craft import EditCraftError
        with pytest.raises(EditCraftError, match="策略未确认"):
            gate.enforce()

    def test_gate_reject(self):
        from hevi.assembly.strategy_enforcement import (
            ConfirmationStatus,
            StrategyGate,
            StrategyProposal,
        )

        gate = StrategyGate()
        gate.propose(StrategyProposal(summary="v1", rationale="first try"))
        gate.reject("用户认为不合适")
        assert gate.status == ConfirmationStatus.PENDING
        assert len(gate.get_history()) == 1

    def test_gate_skip(self):
        from hevi.assembly.strategy_enforcement import (
            ConfirmationStatus,
            StrategyGate,
            StrategyProposal,
        )
        from hevi.assembly.edit_craft import EditCraftError

        gate = StrategyGate()
        gate.propose(StrategyProposal(summary="test", rationale="test"))
        gate.skip("testing mode")
        assert gate.status == ConfirmationStatus.SKIPPED

        # enforce with allow_skip=False should raise
        with pytest.raises(EditCraftError, match="跳过"):
            gate.enforce(allow_skip=False)

        # enforce with allow_skip=True should pass
        gate.enforce(allow_skip=True)

    def test_gate_history(self):
        from hevi.assembly.strategy_enforcement import StrategyGate, StrategyProposal

        gate = StrategyGate()

        # First proposal → confirm → execute
        gate.propose(StrategyProposal(summary="v1", rationale="first"))
        gate.confirm()
        gate.enforce()
        gate.mark_executed()

        # Second proposal → reject
        gate.propose(StrategyProposal(summary="v2", rationale="second"))
        gate.reject("not good")

        history = gate.get_history()
        assert len(history) == 2
        assert history[0]["status"] == "executed"
        assert history[1]["status"] == "rejected"

    def test_confirm_without_proposal(self):
        from hevi.assembly.strategy_enforcement import StrategyGate
        from hevi.assembly.edit_craft import EditCraftError

        gate = StrategyGate()
        with pytest.raises(EditCraftError, match="no proposal"):
            gate.confirm()

    def test_strategy_proposal_fields(self):
        from hevi.assembly.strategy_enforcement import StrategyProposal

        p = StrategyProposal(
            summary="test strategy",
            rationale="because it works",
            alternatives=["alt1", "alt2"],
            risks=["might be too slow"],
        )
        assert p.summary == "test strategy"
        assert len(p.alternatives) == 2
        assert len(p.risks) == 1
        assert p.proposed_at  # auto-timestamped

    def test_check_edl_strategy_with_gate(self):
        from hevi.assembly.edit_craft import EditCraftError, EditDecisionList
        from hevi.assembly.strategy_enforcement import (
            StrategyGate,
            StrategyProposal,
            check_edl_strategy,
        )

        gate = StrategyGate()
        gate.propose(StrategyProposal(summary="test", rationale="test"))
        gate.confirm()

        edl = EditDecisionList()
        check_edl_strategy(edl, gate=gate)  # Should not raise

    def test_check_edl_strategy_fallback(self):
        from hevi.assembly.edit_craft import EditCraftError, EditDecisionList
        from hevi.assembly.strategy_enforcement import check_edl_strategy

        edl = EditDecisionList(strategy_confirmed=False)
        with pytest.raises(EditCraftError, match="策略未确认"):
            check_edl_strategy(edl)

        edl2 = EditDecisionList(strategy_confirmed=True)
        check_edl_strategy(edl2)  # Should not raise

    def test_confirmation_record_to_dict(self):
        from hevi.assembly.strategy_enforcement import (
            ConfirmationRecord,
            ConfirmationStatus,
            StrategyProposal,
        )

        rec = ConfirmationRecord(
            status=ConfirmationStatus.CONFIRMED,
            proposal=StrategyProposal(summary="s", rationale="r"),
            confirmed_by="user",
        )
        d = rec.to_dict()
        assert d["status"] == "confirmed"
        assert d["proposal"]["summary"] == "s"


# ═══════════════════════════════════════════════════════════════════════
# 9. Integration / cross-module
# ═══════════════════════════════════════════════════════════════════════

class TestIntegration:
    """跨模块集成测试。"""

    def test_scribe_to_edl_flow(self):
        """Scribe → word gaps → snap → EDL 完整链路。"""
        from hevi.assembly.edit_craft import EditDecisionList, EditRange, snap_to_word_boundary
        from hevi.assembly.scribe_service import (
            ScribeTranscript,
            ScribeWord,
            find_word_gaps,
            to_edit_words,
        )

        # 1. Mock Scribe 转写
        transcript = ScribeTranscript(
            text="a b c d e",
            words=[
                ScribeWord("a", 0.0, 0.3, "S1"),
                ScribeWord("b", 0.5, 0.8, "S1"),
                ScribeWord("c", 1.5, 1.8, "S1"),
                ScribeWord("d", 2.0, 2.3, "S1"),
                ScribeWord("e", 2.5, 2.8, "S1"),
            ],
        )

        # 2. 提取 edit_words
        edit_words = to_edit_words(transcript)
        assert len(edit_words) == 5

        # 3. 找间隙
        gaps = find_word_gaps(edit_words)
        assert len(gaps) >= 3

        # 4. Snap 到词边界
        snapped = snap_to_word_boundary(1.0, edit_words)
        assert snapped in [0.5, 1.5]  # nearest word boundary

        # 5. 构建 EDL
        edl = EditDecisionList(
            sources={"main": "/fake/video.mp4"},
            ranges=[
                EditRange(source="main", start=0.0, end=0.8, beat="intro"),
                EditRange(source="main", start=2.0, end=2.8, beat="outro"),
            ],
            strategy_confirmed=True,
        )
        assert len(edl.ranges) == 2

    def test_color_grade_in_pipeline(self):
        """GradePipeline → resolve → 与 edit_render 兼容。"""
        from hevi.assembly.color_grade import GradePipeline, SegmentGrade, resolve_grade

        pipe = GradePipeline(
            default_grade="warm_cinematic",
            segment_grades=[
                SegmentGrade(range_index=0, grade="noir"),
            ],
        )
        # 第一段用 noir
        vf0 = pipe.get_grade_for_segment(0)
        assert vf0 is not None

        # 其他段用 default
        vf1 = pipe.get_grade_for_segment(1)
        expected = resolve_grade("warm_cinematic")
        assert vf1 == expected

    def test_take_selector_to_edl(self):
        """Take selector → EditRange → EDL。"""
        from hevi.assembly.edit_craft import EditDecisionList
        from hevi.assembly.take_selector import (
            SelectionResult,
            TakeBeat,
        )

        result = SelectionResult(
            selections={
                "intro": TakeBeat("t1", "intro", 0.0, 5.0, score=0.9),
                "body": TakeBeat("t0", "body", 5.0, 20.0, score=0.85),
            },
        )
        ranges = result.to_edit_ranges("main.mp4")

        edl = EditDecisionList(
            sources={"main.mp4": "/path/to/main.mp4"},
            ranges=ranges,
            strategy_confirmed=True,
        )
        assert len(edl.ranges) == 2
        assert edl.ranges[0].source == "main.mp4"

    def test_session_memory_with_decisions(self):
        """Session memory 记录完整剪辑流程。"""
        from hevi.assembly.session_memory import SessionMemory, load_project_md, save_project_md

        mem = SessionMemory(strategy="auto-select best takes")
        mem.add_decision("selected take_1 for intro", "highest fluency score")
        mem.add_decision("applied warm_cinematic grade", "brand consistency")
        mem.add_reasoning("take_0 had background noise, discarded")
        mem.add_outstanding("review final cut with client", priority="high")

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "project.md"
            save_project_md(mem, path)
            loaded = load_project_md(path)

            assert loaded.strategy == "auto-select best takes"
            assert len(loaded.decisions) == 2
            assert any("fluency" in d.why for d in loaded.decisions)

    def test_strategy_gate_full_flow(self):
        """完整策略确认 → 执行流程。"""
        from hevi.assembly.strategy_enforcement import (
            ConfirmationStatus,
            StrategyGate,
            StrategyProposal,
        )

        gate = StrategyGate()

        # Propose
        gate.propose(StrategyProposal(
            summary="Cut intro, keep body, apply warm grade",
            rationale="Intro has low energy; warm matches brand",
            alternatives=["Keep full video", "Different grade"],
            risks=["Client may want different intro"],
        ))

        # Confirm
        gate.confirm(by="user")
        gate.enforce()

        # Execute (simulated)
        gate.mark_executed()

        history = gate.get_history()
        assert len(history) == 1
        assert history[0]["status"] == "executed"
        assert history[0]["confirmed_by"] == "user"

    def test_subtitle_styles_with_karaoke(self):
        """Karaoke ASS 生成完整链路。"""
        from hevi.assembly.edit_craft import SubtitleCue
        from hevi.assembly.scribe_service import ScribeWord
        from hevi.assembly.subtitle_styles import (
            SubtitleStyle,
            cues_to_karaoke_ass,
        )

        words = [
            ScribeWord("你好", 0.0, 0.5, "S1"),
            ScribeWord("世界", 0.5, 1.0, "S1"),
        ]
        cues = [SubtitleCue(start=0.0, end=1.0, text="你好世界")]
        words_timing = [
            {"word": w.word, "start": w.start, "end": w.end}
            for w in words
        ]
        style = SubtitleStyle(name="karaoke")
        ass = cues_to_karaoke_ass(cues, style, words_with_timing=words_timing)
        assert "Dialogue:" in ass
        assert "你好" in ass
        assert r"\k" in ass

    def test_overlay_plan_with_grade(self):
        """Overlay plan + grade pipeline 组合。"""
        from hevi.assembly.animation_overlay import OverlayPlan
        from hevi.assembly.color_grade import GradePipeline, SegmentGrade

        plan = OverlayPlan(parallel=True)
        plan.add_task("title", "pil", {"text": "Title"}, start=0.0, duration=3.0)
        plan.add_task("anim", "hyperframes", {"html": "<div>"}, start=5.0, duration=5.0)

        pipe = GradePipeline(
            default_grade="warm_cinematic",
            segment_grades=[SegmentGrade(0, "noir")],
        )

        # Both plans and grade should work together
        assert len(plan.tasks) == 2
        assert pipe.get_grade_for_segment(0) is not None

    def test_all_imports_from_init(self):
        """验证 __init__.py 导出的所有符号。"""
        from hevi.assembly import (
            ASCCDL,
            ConfirmationStatus,
            GradePipeline,
            OverlayPlan,
            OverlayTask,
            SegmentGrade,
            SelectionResult,
            SessionMemory,
            ScribeClient,
            ScribeTranscript,
            ScribeWord,
            StrategyGate,
            TakeSet,
            WordGap,
            find_best_gap,
            find_word_gaps,
            generate_all_overlays,
            load_or_create,
            resolve_grade,
            save,
            select_best_takes,
        )

        # All should be importable
        assert ASCCDL is not None
        assert StrategyGate is not None
        assert SessionMemory is not None
