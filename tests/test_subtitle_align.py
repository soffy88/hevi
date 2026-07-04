"""hevi.assembly.subtitle_align 测试 — SRT 格式化纯函数 + 机会性 ASR 转写。"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from hevi.assembly.subtitle_align import (
    Cue,
    _fmt_ts,
    align_subtitles,
    align_subtitles_bilingual,
    cues_to_srt,
    merge_bilingual_cues,
)

try:
    import faster_whisper  # noqa: F401

    _HAS_FW = True
except ImportError:
    _HAS_FW = False
_HAS_FFMPEG = shutil.which("ffmpeg") is not None


def test_fmt_ts() -> None:
    assert _fmt_ts(0) == "00:00:00,000"
    assert _fmt_ts(1.5) == "00:00:01,500"
    assert _fmt_ts(3661.234) == "01:01:01,234"
    assert _fmt_ts(-5) == "00:00:00,000"  # 负数夹到 0


def test_cues_to_srt() -> None:
    srt = cues_to_srt([Cue(0.0, 1.5, "你好"), Cue(1.5, 3.0, "世界")])
    assert "1\n00:00:00,000 --> 00:00:01,500\n你好" in srt
    assert "2\n00:00:01,500 --> 00:00:03,000\n世界" in srt


def test_cues_to_srt_empty() -> None:
    assert cues_to_srt([]) == ""


@pytest.mark.skipif(not (_HAS_FW and _HAS_FFMPEG), reason="needs faster-whisper + ffmpeg")
async def test_align_subtitles_on_silence(tmp_path: Path) -> None:
    """静音音频转写 → 无字幕段 → 返回 None(装配器跳过烧字幕)。"""
    audio = tmp_path / "silence.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono", "-t", "2", str(audio)],
        check=True,
        capture_output=True,
    )
    result = await align_subtitles(audio, tmp_path / "out.srt")
    assert result is None  # 静音无可对齐文本


async def test_align_subtitles_missing_file(tmp_path: Path) -> None:
    assert await align_subtitles(tmp_path / "nope.wav", tmp_path / "out.srt") is None


def test_merge_bilingual_cues_two_lines_per_block() -> None:
    """双语字幕:标准做法是同一 cue 块两行(原文+译文),不是两条独立 cue。"""
    primary = [Cue(0.0, 1.5, "你好"), Cue(1.5, 3.0, "世界")]
    secondary = [Cue(0.0, 1.5, "hello"), Cue(1.5, 3.0, "world")]
    merged = merge_bilingual_cues(primary, secondary)
    assert len(merged) == 2
    assert merged[0].text == "你好\nhello"
    assert merged[0].start == 0.0 and merged[0].end == 1.5
    assert merged[1].text == "世界\nworld"


def test_merge_bilingual_cues_secondary_shorter_falls_back_to_primary_only() -> None:
    primary = [Cue(0.0, 1.0, "a"), Cue(1.0, 2.0, "b")]
    merged = merge_bilingual_cues(primary, [Cue(0.0, 1.0, "x")])
    assert merged[0].text == "a\nx"
    assert merged[1].text == "b"  # 译文缺行 → 只留原文


async def test_align_subtitles_bilingual_missing_file(tmp_path: Path) -> None:
    result = await align_subtitles_bilingual(
        tmp_path / "nope.wav", tmp_path / "out.srt", target_language="en"
    )
    assert result is None


async def test_align_subtitles_bilingual_writes_merged_srt(tmp_path: Path) -> None:
    """转写+翻译 mock,验证落盘的 SRT 每块含原文+译文两行。"""
    from unittest.mock import AsyncMock, patch

    audio = tmp_path / "narration.wav"
    audio.write_bytes(b"\x00" * 64)  # 只需存在,transcribe_to_cues 被 mock 掉

    async def fake_translate(cues, *, target_language, llm=None):
        return [Cue(c.start, c.end, c.text.upper()) for c in cues]

    with (
        patch(
            "hevi.assembly.subtitle_align.transcribe_to_cues",
            return_value=[Cue(0.0, 1.0, "hi")],
        ),
        patch("hevi.dub.translate.translate_cues", new=fake_translate),
    ):
        out = await align_subtitles_bilingual(audio, tmp_path / "bi.srt", target_language="en")
    assert out is not None
    content = out.read_text(encoding="utf-8")
    assert "hi\nHI" in content
