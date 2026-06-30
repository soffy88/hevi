"""hevi.assembly.assembler 测试 — 纯函数单测 + lavfi 合成片真 ffmpeg 集成测。"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from hevi.assembly.assembler import (
    ShotSegment,
    assemble_longvideo,
    build_audio_filter,
    build_xfade_chain,
    compose_avatar_broll,
    load_timing_manifest,
    probe_duration,
)

_HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
ffmpeg_only = pytest.mark.skipif(not _HAS_FFMPEG, reason="needs ffmpeg/ffprobe")


# ── 纯函数单测(无需 ffmpeg) ─────────────────────────────────────────


def test_xfade_chain_single_shot() -> None:
    fc, label, total = build_xfade_chain([5.0], "fade", 0.5)
    assert fc == ""
    assert label == "0:v"
    assert total == 5.0


def test_xfade_chain_total_duration_math() -> None:
    # 3 段各 5s,重叠 0.5s,总时长 = 15 - 2*0.5 = 14
    fc, label, total = build_xfade_chain([5.0, 5.0, 5.0], "fade", 0.5)
    assert label == "[vout]"
    assert total == pytest.approx(14.0)
    assert "xfade=transition=fade" in fc
    # 第一段 offset = 5 - 0.5 = 4.5;第二段 offset = (5+5-0.5) - 0.5 = 9.0
    assert "offset=4.500" in fc
    assert "offset=9.000" in fc


def test_audio_filter_narration_only() -> None:
    f, label = build_audio_filter(True, False, 1, -1, -14.0, -18.0, 10.0)
    assert label == "[aout]"
    assert "loudnorm=I=-14.0" in f


def test_audio_filter_ducking() -> None:
    # 旁白 + BGM → 侧链闪避
    f, label = build_audio_filter(True, True, 1, 2, -14.0, -18.0, 30.0)
    assert label == "[aout]"
    assert "sidechaincompress" in f
    assert "loudnorm" in f
    assert "amix=inputs=2" in f


def test_audio_filter_none() -> None:
    f, label = build_audio_filter(False, False, -1, -1, -14.0, -18.0, 10.0)
    assert label is None


def test_load_timing_manifest_missing(tmp_path: Path) -> None:
    assert load_timing_manifest(tmp_path / "nope.wav") is None


def test_load_timing_manifest_ok(tmp_path: Path) -> None:
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"x")
    (tmp_path / "a.wav.timing.json").write_text('{"durations": [1.5, 2.0]}')
    assert load_timing_manifest(audio) == [1.5, 2.0]


# ── 集成测(真 ffmpeg / lavfi 合成片) ───────────────────────────────


def _make_clip(path: Path, seconds: float, color: str, fps: int = 16) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i",
         f"testsrc=duration={seconds}:size=640x360:rate={fps}",
         "-vf", f"drawbox=c={color}:t=fill", "-pix_fmt", "yuv420p", str(path)],
        check=True, capture_output=True,
    )


def _make_audio(path: Path, seconds: float) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i",
         f"sine=frequency=440:duration={seconds}", str(path)],
        check=True, capture_output=True,
    )


def _has_audio_stream(path: Path) -> bool:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a",
         "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    )
    return "audio" in out.stdout


@ffmpeg_only
async def test_probe_duration(tmp_path: Path) -> None:
    clip = tmp_path / "c.mp4"
    _make_clip(clip, 3.0, "red")
    assert await probe_duration(clip) == pytest.approx(3.0, abs=0.3)


@ffmpeg_only
async def test_assemble_audio_driven_duration(tmp_path: Path) -> None:
    """3 个 5s 镜头,各按对白音频时长(2/3/4s)裁剪 → 成片 ≈ 9 - 2*0.5 = 8s。"""
    clips = []
    for i, color in enumerate(["red", "green", "blue"]):
        c = tmp_path / f"shot{i}.mp4"
        _make_clip(c, 5.0, color)
        clips.append(c)
    shots = [
        ShotSegment(clips[0], target_duration=2.0),
        ShotSegment(clips[1], target_duration=3.0),
        ShotSegment(clips[2], target_duration=4.0),
    ]
    out = tmp_path / "final.mp4"
    await assemble_longvideo(
        shots=shots, output_path=out, width=640, height=360, fps=24,
        transition="fade", transition_duration=0.5,
    )
    assert out.exists()
    # 9s 总时长 - 2 次 0.5s 重叠 = 8s
    assert await probe_duration(out) == pytest.approx(8.0, abs=0.6)


@ffmpeg_only
async def test_assemble_with_narration_and_bgm(tmp_path: Path) -> None:
    """带旁白 + BGM → 成片含音轨(loudnorm + ducking 链路跑通)。"""
    c0, c1 = tmp_path / "s0.mp4", tmp_path / "s1.mp4"
    _make_clip(c0, 4.0, "red")
    _make_clip(c1, 4.0, "blue")
    narr, bgm = tmp_path / "narr.wav", tmp_path / "bgm.wav"
    _make_audio(narr, 6.0)
    _make_audio(bgm, 10.0)
    out = tmp_path / "final.mp4"
    await assemble_longvideo(
        shots=[ShotSegment(c0), ShotSegment(c1)],
        output_path=out, narration_audio=narr, bgm_path=bgm,
        width=640, height=360, fps=24,
    )
    assert out.exists()
    assert _has_audio_stream(out)


@ffmpeg_only
async def test_compose_avatar_broll(tmp_path: Path) -> None:
    """数字人 PiP 合成: B-roll 铺底 + 数字人(带音轨)角落叠加,取数字人音频。"""
    broll, avatar = tmp_path / "broll.mp4", tmp_path / "avatar.mp4"
    _make_clip(broll, 4.0, "blue")
    # 数字人片带音轨
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=duration=4:size=320x320:rate=24",
         "-f", "lavfi", "-i", "sine=frequency=300:duration=4",
         "-pix_fmt", "yuv420p", "-shortest", str(avatar)],
        check=True, capture_output=True,
    )
    out = tmp_path / "composed.mp4"
    await compose_avatar_broll(broll_video=broll, avatar_video=avatar, output_path=out)
    assert out.exists()
    assert _has_audio_stream(out)  # 取数字人音轨
    assert await probe_duration(out) == pytest.approx(4.0, abs=0.5)


@ffmpeg_only
async def test_assemble_hard_cut(tmp_path: Path) -> None:
    """transition='cut' → 硬切,成片 ≈ 时长之和(无重叠)。"""
    c0, c1 = tmp_path / "s0.mp4", tmp_path / "s1.mp4"
    _make_clip(c0, 3.0, "red")
    _make_clip(c1, 3.0, "blue")
    out = tmp_path / "final.mp4"
    await assemble_longvideo(
        shots=[ShotSegment(c0), ShotSegment(c1)],
        output_path=out, width=640, height=360, fps=24, transition="cut",
    )
    assert out.exists()
    assert await probe_duration(out) == pytest.approx(6.0, abs=0.5)
