"""L8 字幕与剪辑合成 + G8 终审门测试。纯函数单测(无需 ffmpeg)+ 真 ffmpeg/lavfi
合成片集成测(同 tests/test_assembler.py 的 ffmpeg_only 惯例)。"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from hevi.tongjian.assemble import (
    _detect_black_frames,
    _detect_clipping,
    _dimensions_for_aspect_ratio,
    _srt_timestamp,
    _zoompan_filter,
    build_final_video,
    concat_narration_track,
    gate_final_video,
    generate_srt,
    mix_bgm_master,
    mix_sfx_master,
    render_shot_clip,
)
from hevi.tongjian.schemas import (
    Act,
    AudioSegment,
    Constitution,
    FinalVideo,
    FrameManifest,
    MusicCue,
    MusicPlan,
    Script,
    ScriptLine,
    SfxCue,
    Shot,
    ShotCamera,
    ShotFrame,
    ShotList,
    Timeline,
    TimelineGap,
    VisualStyle,
)

_HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
ffmpeg_only = pytest.mark.skipif(not _HAS_FFMPEG, reason="needs ffmpeg/ffprobe")


# ── 纯函数单测(无需 ffmpeg) ─────────────────────────────────────────────


class TestSrtTimestamp:
    def test_zero(self):
        assert _srt_timestamp(0) == "00:00:00,000"

    def test_minutes_and_millis(self):
        assert _srt_timestamp(65_432) == "00:01:05,432"

    def test_hours(self):
        assert _srt_timestamp(3_661_000) == "01:01:01,000"

    def test_negative_clamped_to_zero(self):
        assert _srt_timestamp(-500) == "00:00:00,000"


class TestGenerateSrt:
    def test_basic_narration_and_dialogue(self):
        timeline = Timeline(
            audio_segments=[
                AudioSegment(line_id="LN001", t_start_ms=0, t_end_ms=2000),
                AudioSegment(line_id="LN002", t_start_ms=2000, t_end_ms=4000),
            ]
        )
        script = Script(
            lines=[
                ScriptLine(line_id="LN001", type="narration", speaker="NARRATOR", text="旁白开场"),
                ScriptLine(line_id="LN002", type="dialogue", speaker="C001", text="台词内容"),
            ]
        )
        srt = generate_srt(timeline, script)
        assert "1\n00:00:00,000 --> 00:00:02,000\n旁白开场" in srt
        assert "2\n00:00:02,000 --> 00:00:04,000\nC001: 台词内容" in srt

    def test_skips_missing_or_empty_lines(self):
        timeline = Timeline(
            audio_segments=[
                AudioSegment(line_id="LN999", t_start_ms=0, t_end_ms=1000),
            ]
        )
        srt = generate_srt(timeline, Script(lines=[]))
        assert srt == ""


class TestZoompanFilter:
    def test_static_has_no_zoom_change(self):
        vf = _zoompan_filter("static", 832, 480, 24, 3.0)
        assert "z='1.0'" in vf
        assert "s=832x480" in vf

    def test_push_in_increases_zoom(self):
        vf = _zoompan_filter("slow_push_in", 832, 480, 24, 3.0)
        assert "zoom+" in vf

    def test_pull_out_decreases_zoom(self):
        vf = _zoompan_filter("slow_pull_out", 832, 480, 24, 3.0)
        assert "zoom-" in vf

    def test_pan_left_uses_frame_counter_for_x(self):
        vf = _zoompan_filter("pan_left", 832, 480, 24, 3.0)
        assert "on/72" in vf  # 3.0s * 24fps = 72 frames

    def test_unknown_movement_falls_back_to_static(self):
        vf = _zoompan_filter("nonexistent", 832, 480, 24, 3.0)
        assert "z='1.0'" in vf


class TestDimensionsForAspectRatio:
    def test_known_ratios(self):
        assert _dimensions_for_aspect_ratio("16:9") == (832, 480)
        assert _dimensions_for_aspect_ratio("9:16") == (480, 832)

    def test_unknown_falls_back_to_default(self):
        assert _dimensions_for_aspect_ratio("21:9") == (832, 480)


class TestGateFinalVideo:
    @pytest.mark.asyncio
    async def test_missing_file_fails(self):
        final_video = FinalVideo(video_path="/nonexistent/final.mp4")
        result = await gate_final_video(final_video, Timeline(), Script(), None, vlm=AsyncMock())
        assert not result.passed
        assert any("不存在" in e for e in result.errors)


# ── 集成测(真 ffmpeg / lavfi 合成片) ─────────────────────────────────────


def _make_image(path: Path, color: tuple[int, int, int] = (200, 40, 40)) -> None:
    from PIL import Image

    Image.new("RGB", (512, 512), color).save(path)


def _make_wav(path: Path, seconds: float, freq: int = 440) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency={freq}:duration={seconds}",
            str(path),
        ],
        check=True,
        capture_output=True,
    )


def _probe_duration_sync(path: Path) -> float:
    out = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    return float(out.stdout.strip() or 0.0)


@ffmpeg_only
async def test_render_shot_clip_push_in(tmp_path):
    frame_path = tmp_path / "frame.png"
    _make_image(frame_path)
    shot = Shot(
        shot_id="SH001",
        scene_id="E001",
        t_start_ms=0,
        t_end_ms=3000,
        camera=ShotCamera(shot_size="wide", movement="slow_push_in"),
    )
    frame = ShotFrame(shot_id="SH001", scene_id="E001", frame_path=str(frame_path))

    out = await render_shot_clip(shot, frame, output_dir=tmp_path, width=320, height=240, fps=12)

    assert out.exists()
    assert _probe_duration_sync(out) == pytest.approx(3.0, abs=0.3)


@ffmpeg_only
async def test_concat_narration_track_with_gap(tmp_path):
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    _make_wav(audio_dir / "ln001.wav", 2.0)
    _make_wav(audio_dir / "ln002.wav", 1.5)
    timeline = Timeline(
        audio_segments=[
            AudioSegment(line_id="LN001", file="ln001.wav", t_start_ms=0, t_end_ms=2000),
            AudioSegment(line_id="LN002", file="ln002.wav", t_start_ms=3500, t_end_ms=5000),
        ],
        total_duration_ms=5000,
        gaps=[TimelineGap(after_line="LN001", duration_ms=1500, purpose="act_transition")],
    )

    out = await concat_narration_track(timeline, audio_dir, output_dir=tmp_path)

    assert out is not None and out.exists()
    # 2.0 + 1.5(静音) + 1.5 = 5.0s
    assert _probe_duration_sync(out) == pytest.approx(5.0, abs=0.3)


@ffmpeg_only
async def test_concat_narration_track_empty_timeline_returns_none(tmp_path):
    assert await concat_narration_track(Timeline(), tmp_path, output_dir=tmp_path) is None


@ffmpeg_only
async def test_mix_bgm_master_single_cue(tmp_path):
    bgm_file = tmp_path / "bgm.wav"
    _make_wav(bgm_file, 10.0)
    plan = MusicPlan(cues=[MusicCue(act=1, bgm_path=str(bgm_file), t_start_ms=0, t_end_ms=4000)])

    out = await mix_bgm_master(plan, output_dir=tmp_path)

    assert out is not None and out.exists()
    assert _probe_duration_sync(out) == pytest.approx(4.0, abs=0.3)


@ffmpeg_only
async def test_mix_bgm_master_multi_cue_crossfades(tmp_path):
    bgm1, bgm2 = tmp_path / "bgm1.wav", tmp_path / "bgm2.wav"
    _make_wav(bgm1, 10.0, freq=300)
    _make_wav(bgm2, 10.0, freq=500)
    plan = MusicPlan(
        cues=[
            MusicCue(act=1, bgm_path=str(bgm1), t_start_ms=0, t_end_ms=5000),
            MusicCue(act=2, bgm_path=str(bgm2), t_start_ms=5000, t_end_ms=9000),
        ]
    )

    out = await mix_bgm_master(plan, output_dir=tmp_path, crossfade_s=1.0)

    assert out is not None and out.exists()
    # acrossfade 重叠 1.0s:5+4-1=8s
    assert _probe_duration_sync(out) == pytest.approx(8.0, abs=0.3)


@ffmpeg_only
async def test_mix_bgm_master_no_cues_returns_none(tmp_path):
    assert await mix_bgm_master(MusicPlan(), output_dir=tmp_path) is None


@ffmpeg_only
async def test_mix_sfx_master_delays_and_pads(tmp_path):
    sfx_file = tmp_path / "sfx.wav"
    _make_wav(sfx_file, 0.5, freq=800)
    plan = MusicPlan(
        sfx=[SfxCue(shot_id="SH001", sfx_name="impact", sfx_path=str(sfx_file), t_start_ms=2000)]
    )

    out = await mix_sfx_master(plan, total_duration_ms=4000, output_dir=tmp_path)

    assert out is not None and out.exists()
    assert _probe_duration_sync(out) == pytest.approx(4.0, abs=0.3)


@ffmpeg_only
async def test_detect_black_frames_finds_real_black_segment(tmp_path):
    clip = tmp_path / "black.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:size=320x240:duration=2",
            "-pix_fmt",
            "yuv420p",
            str(clip),
        ],
        check=True,
        capture_output=True,
    )
    spans = await _detect_black_frames(clip)
    assert len(spans) >= 1


@ffmpeg_only
async def test_detect_clipping_reports_max_volume(tmp_path):
    clip = tmp_path / "loud.wav"
    _make_wav(clip, 1.0)
    max_vol = await _detect_clipping(clip)
    assert max_vol is not None


@ffmpeg_only
async def test_build_final_video_end_to_end(tmp_path):
    """两个 shot,一段旁白,一幕 BGM,一个 SFX —— 全流程真跑一遍。"""
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    _make_wav(audio_dir / "ln001.wav", 2.0)
    _make_wav(audio_dir / "ln002.wav", 2.0)

    frames_dir = tmp_path / "frames"
    frames_dir.mkdir()
    frame1, frame2 = frames_dir / "f1.png", frames_dir / "f2.png"
    _make_image(frame1, (200, 40, 40))
    _make_image(frame2, (40, 40, 200))

    bgm_file = tmp_path / "bgm.wav"
    _make_wav(bgm_file, 10.0)
    sfx_file = tmp_path / "sfx.wav"
    _make_wav(sfx_file, 0.3, freq=900)

    shotlist = ShotList(
        shots=[
            Shot(
                shot_id="SH001",
                scene_id="E001",
                t_start_ms=0,
                t_end_ms=2000,
                visual_prompt="智伯举杯",
                camera=ShotCamera(movement="static"),
            ),
            Shot(
                shot_id="SH002",
                scene_id="E001",
                t_start_ms=2000,
                t_end_ms=4000,
                visual_prompt="旁白",
                camera=ShotCamera(movement="slow_push_in"),
            ),
        ]
    )
    frame_manifest = FrameManifest(
        frames=[
            ShotFrame(shot_id="SH001", scene_id="E001", frame_path=str(frame1)),
            ShotFrame(shot_id="SH002", scene_id="E001", frame_path=str(frame2)),
        ]
    )
    timeline = Timeline(
        audio_segments=[
            AudioSegment(line_id="LN001", file="ln001.wav", t_start_ms=0, t_end_ms=2000),
            AudioSegment(line_id="LN002", file="ln002.wav", t_start_ms=2000, t_end_ms=4000),
        ],
        total_duration_ms=4000,
    )
    script = Script(
        lines=[
            ScriptLine(line_id="LN001", type="narration", speaker="NARRATOR", text="第一句"),
            ScriptLine(line_id="LN002", type="narration", speaker="NARRATOR", text="第二句"),
        ]
    )
    music_plan = MusicPlan(
        cues=[MusicCue(act=1, bgm_path=str(bgm_file), t_start_ms=0, t_end_ms=4000)],
        sfx=[SfxCue(shot_id="SH001", sfx_name="impact", sfx_path=str(sfx_file), t_start_ms=500)],
    )
    constitution = Constitution(
        visual_style=VisualStyle(art_direction="水墨", aspect_ratio="16:9"),
        act_structure=[Act(act=1, title="x", events=[])],
    )
    vlm = AsyncMock(return_value={"content": '{"consistent": true, "issues": []}'})

    final_video, result = await build_final_video(
        shotlist,
        frame_manifest,
        timeline,
        script,
        music_plan,
        constitution,
        audio_dir=audio_dir,
        output_dir=tmp_path / "out",
        width=320,
        height=240,
        fps=12,
        vlm=vlm,
    )

    assert Path(final_video.video_path).exists()
    assert final_video.duration_ms > 0
    assert Path(final_video.srt_path).exists()
    assert result.passed
