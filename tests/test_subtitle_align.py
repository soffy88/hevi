"""hevi.assembly.subtitle_align 测试 — SRT 格式化纯函数 + 机会性 ASR 转写。"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from hevi.assembly.subtitle_align import Cue, _fmt_ts, align_subtitles, cues_to_srt

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
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono",
         "-t", "2", str(audio)],
        check=True, capture_output=True,
    )
    result = await align_subtitles(audio, tmp_path / "out.srt")
    assert result is None  # 静音无可对齐文本


async def test_align_subtitles_missing_file(tmp_path: Path) -> None:
    assert await align_subtitles(tmp_path / "nope.wav", tmp_path / "out.srt") is None
