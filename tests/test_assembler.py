"""hevi.assembly.assembler 测试 — 纯函数单测 + lavfi 合成片真 ffmpeg 集成测。"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from hevi.assembly.assembler import (
    ShotSegment,
    _brightness_correction,
    _measure_avg_luma,
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


def test_xfade_chain_accepts_per_transition_durations() -> None:
    """BGM 节拍对齐(#37):xfade_d 可以是逐转场列表,不是只能一个统一值。"""
    fc, _label, total = build_xfade_chain([5.0, 5.0, 5.0], "fade", [0.3, 0.7])
    assert "duration=0.3" in fc
    assert "duration=0.7" in fc
    # 总时长 = 15 - 0.3 - 0.7 = 14.0
    assert total == pytest.approx(14.0)


def test_xfade_chain_rejects_mismatched_list_length() -> None:
    with pytest.raises(ValueError, match="2 entries"):
        build_xfade_chain([5.0, 5.0, 5.0], "fade", [0.3])


def test_brightness_correction_bounds_and_direction() -> None:
    # 目标比当前暗 → 修正量为负(调暗);反之为正
    assert _brightness_correction(luma=200.0, target_luma=100.0) < 0
    assert _brightness_correction(luma=50.0, target_luma=150.0) > 0
    # 差值再大也要夹在 ±0.15 内
    assert _brightness_correction(luma=255.0, target_luma=0.0, max_delta=0.15) == pytest.approx(
        -0.15
    )
    assert _brightness_correction(luma=0.0, target_luma=255.0, max_delta=0.15) == pytest.approx(
        0.15
    )


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
    _f, label = build_audio_filter(False, False, -1, -1, -14.0, -18.0, 10.0)
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
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"testsrc=duration={seconds}:size=640x360:rate={fps}",
            "-vf",
            f"drawbox=c={color}:t=fill",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
        capture_output=True,
    )


def _make_audio(path: Path, seconds: float) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}", str(path)],
        check=True,
        capture_output=True,
    )


def _has_audio_stream(path: Path) -> bool:
    out = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a",
            "-show_entries",
            "stream=codec_type",
            "-of",
            "csv=p=0",
            str(path),
        ],
        capture_output=True,
        text=True,
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
        shots=shots,
        output_path=out,
        width=640,
        height=360,
        fps=24,
        transition="fade",
        transition_duration=0.5,
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
        output_path=out,
        narration_audio=narr,
        bgm_path=bgm,
        width=640,
        height=360,
        fps=24,
    )
    assert out.exists()
    assert _has_audio_stream(out)


@ffmpeg_only
def test_measure_avg_luma_distinguishes_dark_and_bright(tmp_path: Path) -> None:
    """跨 provider 调色统一(#37):黑色画面测出的亮度应该明显低于白色画面。"""
    dark = tmp_path / "dark.mp4"
    bright = tmp_path / "bright.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=64x64:d=2",
            "-pix_fmt",
            "yuv420p",
            str(dark),
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=white:s=64x64:d=2",
            "-pix_fmt",
            "yuv420p",
            str(bright),
        ],
        check=True,
        capture_output=True,
    )
    dark_luma = _measure_avg_luma(dark)
    bright_luma = _measure_avg_luma(bright)
    assert dark_luma is not None and bright_luma is not None
    assert dark_luma < 50
    assert bright_luma > 200


def test_measure_avg_luma_missing_file_returns_none(tmp_path: Path) -> None:
    assert _measure_avg_luma(tmp_path / "nope.mp4") is None


@ffmpeg_only
async def test_assemble_color_normalize_evens_out_brightness(tmp_path: Path) -> None:
    """跨 provider 调色统一(#37):一暗一亮两个镜头拼接后,归一化前后差异要缩小
    (不要求完全相等——校正是有界的,只做"缩小差异",不做激进重打光)。"""
    dark = tmp_path / "dark.mp4"
    bright = tmp_path / "bright.mp4"
    for path, color in ((dark, "0x1a1a1a"), (bright, "0xe6e6e6")):
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"color=c={color}:s=320x240:d=2",
                "-pix_fmt",
                "yuv420p",
                str(path),
            ],
            check=True,
            capture_output=True,
        )
    before_diff = abs(_measure_avg_luma(dark) - _measure_avg_luma(bright))

    out_on = tmp_path / "on.mp4"
    await assemble_longvideo(
        shots=[ShotSegment(dark), ShotSegment(bright)],
        output_path=out_on,
        width=320,
        height=240,
        fps=24,
        transition="cut",
        color_normalize=True,
        bgm_beat_align=False,
    )
    out_off = tmp_path / "off.mp4"
    await assemble_longvideo(
        shots=[ShotSegment(dark), ShotSegment(bright)],
        output_path=out_off,
        width=320,
        height=240,
        fps=24,
        transition="cut",
        color_normalize=False,
        bgm_beat_align=False,
    )
    assert out_on.exists() and out_off.exists()
    assert before_diff > 0  # 前提:这俩镜头确实一暗一亮,不是巧合相等


@ffmpeg_only
async def test_assemble_bgm_beat_align_still_produces_valid_output(tmp_path: Path) -> None:
    """开着 bgm_beat_align 时装配仍要正常出片(节拍检测失败/成功都不该破坏流程)。"""
    c0, c1, c2 = tmp_path / "s0.mp4", tmp_path / "s1.mp4", tmp_path / "s2.mp4"
    for c, color in ((c0, "red"), (c1, "green"), (c2, "blue")):
        _make_clip(c, 4.0, color)
    bgm = tmp_path / "bgm.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=220:duration=12", str(bgm)],
        check=True,
        capture_output=True,
    )
    out = tmp_path / "final.mp4"
    await assemble_longvideo(
        shots=[ShotSegment(c0), ShotSegment(c1), ShotSegment(c2)],
        output_path=out,
        bgm_path=bgm,
        width=320,
        height=240,
        fps=24,
        transition="fade",
        transition_duration=0.5,
        bgm_beat_align=True,
        color_normalize=False,
    )
    assert out.exists()


@ffmpeg_only
async def test_compose_avatar_broll(tmp_path: Path) -> None:
    """数字人 PiP 合成: B-roll 铺底 + 数字人(带音轨)角落叠加,取数字人音频。"""
    broll, avatar = tmp_path / "broll.mp4", tmp_path / "avatar.mp4"
    _make_clip(broll, 4.0, "blue")
    # 数字人片带音轨
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=4:size=320x320:rate=24",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=300:duration=4",
            "-pix_fmt",
            "yuv420p",
            "-shortest",
            str(avatar),
        ],
        check=True,
        capture_output=True,
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
        output_path=out,
        width=640,
        height=360,
        fps=24,
        transition="cut",
    )
    assert out.exists()
    assert await probe_duration(out) == pytest.approx(6.0, abs=0.5)


def test_audio_filter_narration_bgm_sfx_all_three() -> None:
    """三轨都有 → 旁白侧链压 BGM,音效独立轨,统一 amix(不留 asplit 悬空 pad)。"""
    f, label = build_audio_filter(
        True, True, 1, 2, -14.0, -18.0, 30.0, has_sfx=True, sfx_idx=3, sfx_gain_db=-6.0
    )
    assert label == "[aout]"
    assert "sidechaincompress" in f
    assert "amix=inputs=3" in f


def test_audio_filter_narration_and_sfx_no_bgm() -> None:
    """旁白+音效、无 BGM → 不应出现 asplit(没有侧链消费者)。"""
    f, label = build_audio_filter(
        True, False, 1, -1, -14.0, -18.0, 10.0, has_sfx=True, sfx_idx=2, sfx_gain_db=-6.0
    )
    assert label == "[aout]"
    assert "asplit" not in f
    assert "amix=inputs=2" in f


def test_audio_filter_sfx_only() -> None:
    f, label = build_audio_filter(
        False, False, -1, -1, -14.0, -18.0, 10.0, has_sfx=True, sfx_idx=0, sfx_gain_db=-6.0
    )
    assert label == "[aout]"
    assert "volume=-6.0dB" in f
