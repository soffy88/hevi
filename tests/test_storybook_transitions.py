"""Unit tests for storybook transitions (绘本转场 5 种模式及 transitions.storybook 能力)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import cv2
import numpy as np
import pytest

from hevi.capabilities import get, names
from hevi.capabilities.errors import CapabilityError
from hevi.motion_fx.transitions.engine import REGISTRY
from hevi.motion_fx.transitions.storybook import (
    render_page_flip,
    render_pencil_sketch,
    render_torn_paper,
    render_watercolor_bloom,
    render_wet_brush,
)


@pytest.fixture
def sample_frames():
    """生成两张不同色调的手绘测试帧。"""
    h, w = 360, 640
    frame_a = np.full((h, w, 3), (210, 240, 220), dtype=np.uint8)  # 浅青绿 (森林)
    cv2.circle(frame_a, (w // 2, h // 2), 60, (50, 120, 70), -1)

    frame_b = np.full((h, w, 3), (255, 230, 215), dtype=np.uint8)  # 暖橙粉 (晚霞)
    cv2.rectangle(frame_b, (w // 4, h // 4), (3 * w // 4, 3 * h // 4), (80, 80, 180), -1)

    return frame_a, frame_b


def test_storybook_transitions_in_registry():
    assert "transitions.storybook" in names()
    expected_transitions = [
        "page_flip", "storybook_page_flip",
        "wet_brush", "storybook_wet_brush",
        "torn_paper", "storybook_torn_paper",
        "pencil_sketch", "storybook_pencil_sketch",
        "watercolor_bloom", "storybook_watercolor_bloom",
    ]
    for name in expected_transitions:
        assert name in REGISTRY, f"Missing {name} in motion_fx REGISTRY"


@pytest.mark.parametrize("trans_fn", [
    render_page_flip,
    render_wet_brush,
    render_torn_paper,
    render_pencil_sketch,
    render_watercolor_bloom,
])
def test_transition_progress_boundaries(sample_frames, trans_fn):
    frame_a, frame_b = sample_frames

    # p = 0.0 应该等于 frame_a
    out_0 = trans_fn(frame_a, frame_b, 0.0)
    np.testing.assert_array_equal(out_0, frame_a)

    # p = 1.0 应该等于 frame_b
    out_1 = trans_fn(frame_a, frame_b, 1.0)
    np.testing.assert_array_equal(out_1, frame_b)

    # p = 0.5 过渡态帧有效且不同于原图
    out_mid = trans_fn(frame_a, frame_b, 0.5)
    assert out_mid.shape == frame_a.shape
    assert out_mid.dtype == np.uint8
    assert not np.array_equal(out_mid, frame_a)
    assert not np.array_equal(out_mid, frame_b)


@pytest.mark.parametrize("trans_type", [
    "page_flip",
    "wet_brush",
    "torn_paper",
    "pencil_sketch",
    "watercolor_bloom",
])
def test_transitions_storybook_capability_render(tmp_path: Path, sample_frames, trans_type):
    cap = get("transitions.storybook")
    out_dir = tmp_path / f"trans_{trans_type}"

    frame_a, frame_b = sample_frames
    img_a_path = out_dir / "frame_a.png"
    img_b_path = out_dir / "frame_b.png"
    out_dir.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(img_a_path), frame_a)
    cv2.imwrite(str(img_b_path), frame_b)

    dur = 1.0
    res = cap.render(
        {
            "transition_type": trans_type,
            "clip_a": str(img_a_path),
            "clip_b": str(img_b_path),
            "duration": dur,
            "fps": 24,
        },
        out_dir,
        duration=dur,
        aspect="16:9",
        seed=42,
    )

    assert res.mp4 is not None
    mp4_path = Path(res.mp4)
    assert mp4_path.is_file()
    assert mp4_path.stat().st_size > 1000

    # 用 ffprobe 验证视频文件真实时长与编码
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(mp4_path),
    ]
    actual_dur = float(subprocess.check_output(cmd).decode().strip())
    assert abs(actual_dur - dur) <= 0.15


def test_invalid_transition_type_fails(tmp_path: Path):
    cap = get("transitions.storybook")
    with pytest.raises(CapabilityError):
        cap.validate_params({"transition_type": "non_existent_type"})
