"""Unit tests for explainer.render capability, preview frames, and FFmpeg local MP4 render."""

import pytest
import subprocess
from pathlib import Path

from hevi.capabilities import get
from hevi.explainer.render_engine import (
    generate_preview_frames,
    render_final_explainer_mp4,
    render_scene_video,
    render_storyboard_sheet,
)
from hevi.explainer.script import create_oral_script
from hevi.explainer.visual_plan import build_visual_plan
from hevi.explainer.voice import build_voiceover_package


def test_render_preview_frames_and_storyboard(tmp_path: Path):
    article = "第一段引言介绍。\n\n第二段核心逻辑分析。\n\n第三段系统工作机制。"
    script = create_oral_script(article, title="渲染预览测试")
    voiceover = build_voiceover_package(script, tmp_path / "voice_prev")
    plan = build_visual_plan(script, voiceover, tmp_path / "plan_prev")

    # 1. 低清快速预览帧生成
    preview_dir = tmp_path / "previews"
    frames = generate_preview_frames(plan, preview_dir, preview_w=320, preview_h=180)
    assert len(frames) >= len(plan.scenes)
    for f in frames:
        assert f.is_file()
        assert f.stat().st_size > 500

    # 2. 预览分镜大图
    sheet = render_storyboard_sheet(plan, preview_dir, preview_frames=frames)
    assert sheet.is_file()
    assert sheet.stat().st_size > 2000


def test_render_scene_video_with_pip(tmp_path: Path):
    article = "测试单个分镜视频合成。\n\n机制流程步骤说明。"
    script = create_oral_script(article, title="单镜测试")
    voiceover = build_voiceover_package(script, tmp_path / "voice_scene")
    plan = build_visual_plan(script, voiceover, tmp_path / "plan_scene")

    scene = plan.scenes[0]
    out_dir = tmp_path / "clip_out"
    clip = render_scene_video(scene, out_dir, width=640, height=360, fps=25)
    assert clip.is_file()
    assert clip.stat().st_size > 1000

    # ffprobe 验证视频流时长与有效性
    proc = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(clip),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    dur = float(proc.stdout.strip())
    assert dur > 0.4


def test_capability_explainer_render_full_and_preview(tmp_path: Path):
    cap = get("explainer.render")
    assert cap is not None

    article = "快速能力渲染集成测试。\n\n第二段总结。"
    script = create_oral_script(article, title="能力测试")
    voiceover = build_voiceover_package(script, tmp_path / "voice_cap")
    plan = build_visual_plan(script, voiceover, tmp_path / "plan_cap")

    # 测试 preview_only 模式
    res_prev = cap.render(
        params={
            "plan": plan.to_dict(),
            "voiceover": voiceover.to_dict(),
            "fast_preview_only": True,
        },
        out_dir=tmp_path / "render_cap_prev",
        duration=5.0,
        aspect="16:9",
        seed=42,
    )
    assert res_prev.png is not None
    assert Path(res_prev.png).is_file()
    assert res_prev.mp4 is None

    # 测试完整 MP4 渲染模式
    res_full = cap.render(
        params={
            "plan": plan.to_dict(),
            "voiceover": voiceover.to_dict(),
            "fast_preview_only": False,
        },
        out_dir=tmp_path / "render_cap_full",
        duration=5.0,
        aspect="16:9",
        seed=42,
    )
    assert res_full.mp4 is not None
    mp4_p = Path(res_full.mp4)
    assert mp4_p.is_file()
    assert mp4_p.stat().st_size > 5000

    # ffprobe 验证输出包含有效音视频轨道
    probe_v = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_name",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(mp4_p),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "h264" in probe_v.stdout

    probe_a = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=codec_name",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(mp4_p),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "aac" in probe_a.stdout
