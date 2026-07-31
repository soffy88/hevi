"""剪辑成片层单元测试 — 纯函数为主，可选 ffmpeg 集成。"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from hevi.assembly.cut_self_eval import assert_self_eval_passed, self_eval_edl
from hevi.assembly.edit_craft import (
    AUDIO_FADE_S,
    EditCraftError,
    EditDecisionList,
    EditRange,
    SubtitleCue,
    Word,
    apply_cut_padding,
    assert_subtitles_last,
    build_segment_afade_filter,
    clamp_pad_ms,
    compute_output_duration,
    format_srt,
    overlay_setpts_expr,
    remap_cues_to_output_timeline,
    require_strategy_confirmation,
    snap_range_to_words,
    snap_to_word_boundary,
    validate_edl,
)
from hevi.assembly.takes_pack import (
    format_takes_packed,
    pack_edit_dir,
    pack_phrases,
    words_from_transcript_json,
)

_HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
ffmpeg_only = pytest.mark.skipif(not _HAS_FFMPEG, reason="needs ffmpeg/ffprobe")


# ── 策略门 ──────────────────────────────────────────────────────────────


def test_strategy_gate_blocks_unconfirmed() -> None:
    edl = EditDecisionList(
        sources={"A": "/a.mp4"},
        ranges=[EditRange("A", 0, 1)],
        strategy_confirmed=False,
    )
    with pytest.raises(EditCraftError, match="策略未确认"):
        require_strategy_confirmation(edl)


def test_strategy_gate_allows_confirmed() -> None:
    edl = EditDecisionList(
        sources={"A": "/a.mp4"},
        ranges=[EditRange("A", 0, 1)],
        strategy_confirmed=True,
    )
    require_strategy_confirmation(edl)  # no raise


# ── 词边界 ──────────────────────────────────────────────────────────────


def _words() -> list[Word]:
    return [
        Word("你好", 0.0, 0.4),
        Word("世界", 0.5, 0.9),
        Word("测试", 1.2, 1.6),
    ]


def test_snap_start_inside_word_goes_to_word_start() -> None:
    assert snap_to_word_boundary(0.25, _words(), side="start") == pytest.approx(0.0)


def test_snap_end_inside_word_goes_to_word_end() -> None:
    assert snap_to_word_boundary(0.7, _words(), side="end") == pytest.approx(0.9)


def test_pad_clamped_to_window() -> None:
    assert clamp_pad_ms(10) == 30
    assert clamp_pad_ms(500) == 200
    assert clamp_pad_ms(50) == 50


def test_apply_cut_padding_respects_source_duration() -> None:
    s, e = apply_cut_padding(1.0, 2.0, pad_before_ms=50, pad_after_ms=80, source_duration=2.05)
    assert s == pytest.approx(0.95)
    assert e == pytest.approx(2.05)


def test_snap_range_to_words() -> None:
    s, e = snap_range_to_words(0.2, 1.0, _words(), pad_before_ms=30, pad_after_ms=30)
    assert s <= 0.0 + 1e-6 or s < 0.2
    assert e >= 0.9


# ── SRT 重映射 ──────────────────────────────────────────────────────────


def test_remap_cues_output_timeline() -> None:
    cues = [
        SubtitleCue(0.0, 0.5, "A"),
        SubtitleCue(1.0, 1.5, "B"),
        SubtitleCue(5.0, 5.5, "C"),  # 不在 ranges 内
    ]
    ranges = [
        EditRange("S", 0.0, 0.6, beat="h1"),
        EditRange("S", 1.0, 1.6, beat="h2"),
    ]
    out = remap_cues_to_output_timeline(cues, ranges)
    assert len(out) == 2
    assert out[0].text == "A"
    assert out[0].start == pytest.approx(0.0)
    assert out[1].text == "B"
    # 第二段 offset = 0.6
    assert out[1].start == pytest.approx(0.6)
    assert "A" in format_srt(out)


# ── 滤镜顺序 / fade ─────────────────────────────────────────────────────


def test_subtitles_must_be_last() -> None:
    assert_subtitles_last(["scale", "overlay", "subtitles"])
    with pytest.raises(EditCraftError, match="字幕必须"):
        assert_subtitles_last(["subtitles", "overlay"])


def test_afade_filter_has_in_and_out() -> None:
    f = build_segment_afade_filter(2.0, AUDIO_FADE_S)
    assert "afade=t=in" in f
    assert "afade=t=out" in f


def test_overlay_setpts() -> None:
    assert "1.500000" in overlay_setpts_expr(1.5)


# ── EDL 校验 ────────────────────────────────────────────────────────────


def test_validate_edl_rejects_unknown_source() -> None:
    edl = EditDecisionList(
        sources={"A": "/a.mp4"},
        ranges=[EditRange("B", 0, 1)],
        strategy_confirmed=True,
    )
    with pytest.raises(EditCraftError, match="不在 sources"):
        validate_edl(edl)


def test_validate_edl_rejects_empty_ranges() -> None:
    edl = EditDecisionList(sources={"A": "/a.mp4"}, ranges=[], strategy_confirmed=True)
    with pytest.raises(EditCraftError, match="为空"):
        validate_edl(edl)


def test_compute_duration() -> None:
    ranges = [EditRange("A", 0, 1.5), EditRange("A", 2, 3)]
    assert compute_output_duration(ranges) == pytest.approx(2.5)


def test_edl_roundtrip_dict() -> None:
    edl = EditDecisionList(
        sources={"A": "/a.mp4"},
        ranges=[EditRange("A", 0, 2, beat="HOOK", reason="clean")],
        strategy_confirmed=True,
        grade="warm_cinematic",
    )
    restored = EditDecisionList.from_dict(edl.to_dict())
    assert restored.ranges[0].beat == "HOOK"
    assert restored.strategy_confirmed is True


# ── takes_pack ──────────────────────────────────────────────────────────


def test_pack_phrases_breaks_on_silence() -> None:
    words = [
        Word("一", 0.0, 0.2),
        Word("二", 0.25, 0.4),
        Word("三", 1.2, 1.4),  # gap 0.8s
    ]
    phrases = pack_phrases(words, silence_break_s=0.5)
    assert len(phrases) == 2
    assert "一" in phrases[0].text
    assert "三" in phrases[1].text


def test_words_from_transcript_segments() -> None:
    data = {
        "segments": [
            {
                "start": 0,
                "end": 1,
                "text": "hello",
                "words": [
                    {"word": "hello", "start": 0.0, "end": 0.5},
                    {"word": "world", "start": 0.5, "end": 1.0},
                ],
            }
        ]
    }
    words = words_from_transcript_json(data)
    assert len(words) == 2


def test_format_takes_packed_and_pack_edit_dir(tmp_path: Path) -> None:
    edit = tmp_path / "edit"
    td = edit / "transcripts"
    td.mkdir(parents=True)
    (td / "C01.json").write_text(
        json.dumps(
            {
                "duration": 3.0,
                "words": [
                    {"word": "你好", "start": 0.0, "end": 0.4},
                    {"word": "世界", "start": 1.0, "end": 1.4},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    out = pack_edit_dir(edit)
    text = out.read_text(encoding="utf-8")
    assert "takes_packed" in text
    assert "C01" in text
    assert "你好" in text


# ── 自检 ────────────────────────────────────────────────────────────────


def test_self_eval_fails_without_confirm() -> None:
    edl = EditDecisionList(
        sources={"A": "/a.mp4"},
        ranges=[EditRange("A", 0, 1, reason="x")],
        strategy_confirmed=False,
    )
    report = self_eval_edl(edl, require_confirm=True)
    assert report.passed is False
    assert any(i.code == "edl_invalid" for i in report.issues)


def test_self_eval_passes_structure() -> None:
    edl = EditDecisionList(
        sources={"A": "/a.mp4"},
        ranges=[EditRange("A", 0, 1.5, beat="HOOK", reason="clean")],
        strategy_confirmed=True,
    )
    report = self_eval_edl(edl, require_confirm=True)
    assert report.passed is True
    assert report.expected_duration_s == pytest.approx(1.5)


def test_assert_self_eval_raises() -> None:
    edl = EditDecisionList(
        sources={"A": "/a.mp4"},
        ranges=[EditRange("A", 0, 1)],
        strategy_confirmed=False,
    )
    report = self_eval_edl(edl)
    with pytest.raises(EditCraftError, match="禁止归档"):
        assert_self_eval_passed(report)


# ── 渲染（ffmpeg） ──────────────────────────────────────────────────────


# ── filler / silence ────────────────────────────────────────────────────


def test_filler_cut_removes_um_and_long_silence() -> None:
    from hevi.assembly.filler_cut import is_filler_word, plan_filler_cut

    assert is_filler_word("um")
    assert is_filler_word("呃")
    assert not is_filler_word("人工智能")

    words = [
        Word("um", 0.0, 0.2),
        Word("你好", 0.25, 0.6),
        Word("世界", 0.65, 1.0),
        # 0.8s silence
        Word("继续", 1.8, 2.2),
    ]
    plan = plan_filler_cut(words, source_duration=2.5, strong_fillers_only=True)
    assert plan.removed_fillers
    assert any(f.word == "um" for f in plan.removed_fillers)
    assert plan.silence_gaps
    assert plan.kept
    # 保留内容总时长应短于源
    kept_dur = sum(k.end - k.start for k in plan.kept)
    assert kept_dur < 2.5


def test_filler_plan_to_edl_requires_confirm_default() -> None:
    from hevi.assembly.filler_cut import plan_filler_cut, plan_to_edl

    words = [Word("你好", 0.0, 0.5), Word("世界", 0.6, 1.0)]
    plan = plan_filler_cut(words, cut_silence=False, cut_fillers=False)
    edl = plan_to_edl(plan, source_id="m", source_path="/m.mp4")
    assert edl.strategy_confirmed is False
    assert edl.ranges


@ffmpeg_only
def test_timeline_view_filmstrip(tmp_path: Path) -> None:
    import subprocess

    from hevi.assembly.timeline_view import timeline_view

    src = tmp_path / "src.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=red:s=320x240:d=2",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=880:duration=2",
            "-shortest",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(src),
        ],
        check=True,
        capture_output=True,
    )
    out = tmp_path / "tl.jpg"
    res = timeline_view(src, 0.0, 1.5, out, tiles=4, include_waveform=True)
    assert res.path.exists()
    assert res.tile_count >= 2
    assert res.path.stat().st_size > 500


@ffmpeg_only
@pytest.mark.asyncio
async def test_talking_head_cleanup_plan_only(tmp_path: Path) -> None:
    import subprocess

    from hevi.assembly.edit_pipeline import talking_head_cleanup

    src = tmp_path / "talk.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=green:s=320x240:d=2",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=2",
            "-shortest",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(src),
        ],
        check=True,
        capture_output=True,
    )
    transcript = {
        "words": [
            {"word": "um", "start": 0.0, "end": 0.15},
            {"word": "hello", "start": 0.2, "end": 0.5},
            {"word": "world", "start": 0.55, "end": 0.9},
        ]
    }
    out = await talking_head_cleanup(
        source_video=src,
        transcript=transcript,
        work_dir=tmp_path / "session",
        strategy_confirmed=False,
    )
    assert out["status"] == "planned"
    assert Path(out["edit_dir"], "edl.json").exists()
    assert Path(out["edit_dir"], "filler_plan.json").exists()


@ffmpeg_only
@pytest.mark.asyncio
async def test_render_edl_two_segments(tmp_path: Path) -> None:
    import subprocess

    from hevi.assembly.edit_render import render_edl

    src = tmp_path / "src.mp4"
    # 3s 彩条 + 静音
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=320x240:d=3",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=3",
            "-shortest",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(src),
        ],
        check=True,
        capture_output=True,
    )
    edit_dir = tmp_path / "edit"
    edl = EditDecisionList(
        sources={"S": str(src)},
        ranges=[
            EditRange("S", 0.0, 1.0, beat="A", reason="first"),
            EditRange("S", 1.5, 2.5, beat="B", reason="second"),
        ],
        strategy_confirmed=True,
    )
    final = await render_edl(edl, edit_dir=edit_dir, output_name="final.mp4")
    assert final.exists()
    assert final.stat().st_size > 1000
    report = self_eval_edl(edl, final_path=final, require_confirm=True)
    assert report.passed, report.to_dict()
