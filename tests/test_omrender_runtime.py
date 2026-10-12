"""Tests for OMRENDER runtime enhancements and bug fixes.

Covers:
* CMU mocap FK rotation order fix (twist clip upright, 0 flipped frames).
* Quality profile 21:9 resolution calculation.
* Runtime selector intent matching for kinetic typography & product promo.
* Clean-room input-driven stories without MiniMax audio paths.
* Beat generator producing performed visual choreography without placeholder cards.
* Binary path discovery robust against PATH variations.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from hevi.providers.hyperframes.beat_generator import generate_beats_js
from hevi.providers.hyperframes.kinetic import ASPECT_DIMENSIONS
from hevi.studio.runtime import select_runtime
from hevi.studio.svg_character import _find_bin
from hevi.video.quality_profile import ASPECT_RATIOS, resolve_resolution


def test_twist_clip_mocap_no_flip() -> None:
    repo = Path(__file__).resolve().parents[1]
    twist_path = repo / "assets" / "mocap-clips" / "clips" / "twist.json"
    assert twist_path.is_file(), "twist.json missing"

    data = json.loads(twist_path.read_text(encoding="utf-8"))
    frames = data.get("frames", [])
    assert len(frames) > 100, "twist clip should have substantial frames"

    # In our coordinate system, head.y is higher than hips.y (head.y > hips.y in 3D FK projection)
    # Ensure zero inverted/upside-down frames
    flipped = 0
    for frame in frames:
        head_y = frame.get("head", [0, 0])[1]
        hips_y = frame.get("hips", [0, 0])[1]
        # In projection, head is consistently above hips
        if head_y < hips_y:
            flipped += 1

    assert flipped == 0, f"twist clip had {flipped}/{len(frames)} upside-down frames"


def test_aspect_ratio_21_9_support() -> None:
    assert "21:9" in ASPECT_RATIOS
    assert "21:9" in ASPECT_DIMENSIONS
    w, h = resolve_resolution(name="high", aspect_ratio="21:9")
    assert h == 1080
    assert w == 2520


def test_runtime_selection_for_kinetic_and_promo() -> None:
    res1 = select_runtime(intent="为新产品制作一段 kinetic typography 动效")
    assert res1["runtime"] == "hyperframes"

    res2 = select_runtime(intent="高端智能硬件产品宣传视频")
    assert res2["runtime"] == "hyperframes"

    res3 = select_runtime(intent="风格化黑板报知识讲解")
    assert res3["runtime"] == "hyperframes_styled"


def test_input_driven_stories_clean_and_no_minimax() -> None:
    repo = Path(__file__).resolve().parents[1]
    story_dir_a = repo / "output" / "stories" / "static-electricity" / "story.json"
    story_dir_b = repo / "output" / "stories" / "whale-cancer" / "story.json"

    assert story_dir_a.is_file(), "Topic A story.json missing"
    assert story_dir_b.is_file(), "Topic B story.json missing"

    for p in (story_dir_a, story_dir_b):
        content = p.read_text(encoding="utf-8")
        assert "minimax" not in content.lower()
        assert "audio/tts" not in content

        data = json.loads(content)
        assert 25.0 <= data["duration"] <= 65.0, f"duration {data['duration']} out of range"
        assert len(data["lines"]) >= 4, "story must have spoken lines"
        assert len(data["chapters"]) >= 2, "story must have structured chapters"
        for line in data["lines"]:
            assert len(line.get("words", [])) > 0, "must have word-level timestamps"


def test_beat_generator_produces_real_performed_scenes() -> None:
    repo = Path(__file__).resolve().parents[1]
    story_path = repo / "output" / "stories" / "static-electricity" / "story.json"
    story = json.loads(story_path.read_text(encoding="utf-8"))

    for style in ("v8-chalkboard", "v6-cinematic", "v4-paper", "v1-editorial"):
        beats_js = generate_beats_js(style, story)
        assert "window.Beats = function" in beats_js
        assert "待演绎" not in beats_js
        # Must mention words from the static electricity topic
        assert any(term in beats_js for term in ["静电", "电子", "摩擦", "放电", "电荷"])


def test_binary_finder_without_default_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    # Even if PATH doesn't contain /home/soffy/.local/bin, _find_bin checks /home/soffy/.local/bin
    found = _find_bin("ffmpeg", "/fallback/ffmpeg")
    assert found in ("/home/soffy/.local/bin/ffmpeg", "/usr/bin/ffmpeg")
