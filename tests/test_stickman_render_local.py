import os
import subprocess
from pathlib import Path
import pytest
from PIL import Image

from hevi.stickman.proposal import StoryboardScene, DirectorProposal
from hevi.stickman.render_local import (
    render_scene_frame,
    render_local_video,
    draw_stickman,
    DEFAULT_DNA,
    FFPROBE,
)


def test_draw_stickman_both_styles(tmp_path):
    # Style 1: classic minimalist
    img1 = Image.new("RGBA", (400, 400), (255, 255, 255, 255))
    from PIL import ImageDraw
    draw1 = ImageDraw.Draw(img1)
    draw_stickman(draw1, 200, 260, pose="hook", style="classic_minimalist")
    p1 = tmp_path / "classic.png"
    img1.save(p1)
    assert p1.exists()

    # Style 2: color story (beanie + yellow shirt)
    img2 = Image.new("RGBA", (400, 400), (250, 250, 250, 255))
    draw2 = ImageDraw.Draw(img2)
    draw_stickman(draw2, 200, 260, pose="eureka", style="color_story")
    p2 = tmp_path / "color_story.png"
    img2.save(p2)
    assert p2.exists()


def test_render_scene_frame_bilingual(tmp_path):
    scene = StoryboardScene(
        scene_index=1,
        stage="悬念追问",
        duration_s=3.0,
        visual_beats=["[0-3s] 火柴人发问"],
        narration_zh="为什么同样一块冰，放水里浮起来放油里却沉下去？",
        narration_en="Why does ice float in water but sink in oil?",
    )
    frame_path = tmp_path / "frame_01.png"
    render_scene_frame(frame_path, scene, w=1280, h=720, style="classic_minimalist")
    assert frame_path.exists()
    img = Image.open(frame_path)
    assert img.size == (1280, 720)


def test_render_local_video_mini(tmp_path):
    # Test rendering a mini approved proposal (2 scenes of 2.0s = 4.0s total)
    scenes = [
        StoryboardScene(
            scene_index=1,
            stage="悬念追问",
            duration_s=2.0,
            visual_beats=["[0-2s] hook"],
            narration_zh="为什么冰块放水里会浮起来？",
            narration_en="Why does ice float in water?",
        ),
        StoryboardScene(
            scene_index=2,
            stage="揭秘",
            duration_s=2.0,
            visual_beats=["[0-2s] reveal"],
            narration_zh="因为水密度大于冰的密度！",
            narration_en="Because water density is higher than ice!",
        ),
    ]

    proposal = DirectorProposal(
        proposal_id="prop_test_mini",
        title="测试视频",
        topic="浮力原理",
        hook="为什么冰块会浮？",
        color_palette={"bg": "white"},
        storyboard=scenes,
        voiceover={"profile": "test"},
        bgm_style="piano",
        aspect_ratio="16:9",
        art_style="classic_minimalist",
        status="approved",
    )

    out_mp4 = tmp_path / "mini_stickman.mp4"
    res = render_local_video(proposal, out_mp4)

    assert Path(res["out_path"]).exists()
    assert res["duration_s"] >= 3.8
    assert res["aspect_ratio"] == "16:9"
    assert res["qa"]["ffprobe_verified"] is True
    # Clean up to keep disk space free
    if out_mp4.exists():
        out_mp4.unlink()
