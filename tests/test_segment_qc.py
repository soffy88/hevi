"""hevi.director.segment_qc 测试 — 真实 CLIP + lavfi 合成片,tts_fn 注入 AsyncMock。"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from hevi.director.segment_qc import SegmentQCResult, segment_qc

_HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
ffmpeg_only = pytest.mark.skipif(not _HAS_FFMPEG, reason="needs ffmpeg/ffprobe")


def _make_clip(path: Path, seconds: float, color: str) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c=0x{color}:size=64x64:duration={seconds}:rate=8",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
        capture_output=True,
    )


def _make_tone(path: Path, seconds: float) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}", str(path)],
        check=True,
        capture_output=True,
    )


@ffmpeg_only
async def test_segment_qc_keeps_when_no_dialogue_and_identity_ok(tmp_path: Path) -> None:
    clip = tmp_path / "clip.mp4"
    _make_clip(clip, 3.0, "808080")
    canon = tmp_path / "canon.png"
    _make_clip(tmp_path / "canon_src.mp4", 0.1, "808080")
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(tmp_path / "canon_src.mp4"), "-vframes", "1", str(canon)],
        check=True,
        capture_output=True,
    )

    result = await segment_qc(
        clip,
        segment_id="s1",
        character_names=["王生"],
        canon_paths={"王生": canon},
        dialogue_text=None,
        tts_fn=None,
    )
    assert isinstance(result, SegmentQCResult)
    assert result.dialogue_fits is True
    assert result.retake_tier == "keep"


@ffmpeg_only
async def test_segment_qc_re_rolls_when_identity_below_threshold(tmp_path: Path) -> None:
    clip = tmp_path / "clip.mp4"
    _make_clip(clip, 3.0, "0000FF")  # 跟 canon 颜色差异很大,身份分应该很低
    canon = tmp_path / "canon.png"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=0xFF0000:size=64x64",
            "-vframes",
            "1",
            str(canon),
        ],
        check=True,
        capture_output=True,
    )

    result = await segment_qc(
        clip,
        segment_id="s1",
        character_names=["王生"],
        canon_paths={"王生": canon},
        dialogue_text=None,
        tts_fn=None,
        identity_threshold=0.999,  # 强制必挂,不依赖 CLIP 对纯色块的具体分值假设
    )
    assert result.retake_tier == "re_roll"
    assert "身份分" in result.retake_reason


@ffmpeg_only
async def test_segment_qc_re_rolls_when_dialogue_does_not_fit(tmp_path: Path) -> None:
    clip = tmp_path / "clip.mp4"
    _make_clip(clip, 1.0, "808080")  # 视频只有 1s
    canon = tmp_path / "canon.png"
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(clip), "-vframes", "1", str(canon)],
        check=True,
        capture_output=True,
    )

    async def fake_tts_fn(*, script, output_path, voice, emotion):
        _make_tone(output_path, 3.0)  # TTS 真实时长 3s,远超视频的 1s
        return output_path

    result = await segment_qc(
        clip,
        segment_id="s1",
        character_names=["王生"],
        canon_paths={"王生": canon},
        dialogue_text="弟子慕道已久,求仙师收留!",
        speaker="王生",
        tts_fn=AsyncMock(side_effect=fake_tts_fn),
    )
    assert result.dialogue_fits is False
    assert result.retake_tier == "re_roll"
    assert result.tts_actual_s == pytest.approx(3.0, abs=0.2)


@ffmpeg_only
async def test_segment_qc_only_scores_characters_present_in_canon_paths(tmp_path: Path) -> None:
    clip = tmp_path / "clip.mp4"
    _make_clip(clip, 1.0, "808080")
    canon = tmp_path / "canon.png"
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(clip), "-vframes", "1", str(canon)],
        check=True,
        capture_output=True,
    )

    result = await segment_qc(
        clip,
        segment_id="s1",
        character_names=["王生", "老道士"],  # 老道士没有 canon
        canon_paths={"王生": canon},
        dialogue_text=None,
        tts_fn=None,
    )
    assert list(result.identity_scores.keys()) == ["王生"]
