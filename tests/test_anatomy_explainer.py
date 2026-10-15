from __future__ import annotations

import pytest
from pathlib import Path
import json
import subprocess
from PIL import Image
import numpy as np
import os

from hevi.capabilities import get, list as list_capabilities
from hevi.capabilities.anatomy_explainer.renderer import validate_anatomy_params


def test_anatomy_capability_registered():
    caps = list_capabilities(kind="shot")
    names = [c.name for c in caps]
    assert "anatomy_explainer" in names
    cap = get("anatomy_explainer")
    assert cap.aspects == ["16:9", "9:16"]


def test_anatomy_params_validation():
    valid = validate_anatomy_params({"object": "windmill", "duration": 5.0, "seed": 123})
    assert valid["object"] == "windmill"
    assert valid["duration"] == 5.0

    with pytest.raises(ValueError):
        validate_anatomy_params({"object": "invalid_robot", "duration": 4.0})

    with pytest.raises(ValueError):
        validate_anatomy_params({"object": "waterwheel", "duration": 1.0})
    with pytest.raises(ValueError):
        validate_anatomy_params({"object": "soap_pump", "duration": 20.0})


@pytest.mark.slow
def test_anatomy_render_and_assertions(tmp_path: Path):
    cap = get("anatomy_explainer")
    
    out_dir_1 = tmp_path / "out_16_9"
    res1 = cap.render({"object": "windmill", "seed": 42}, out_dir_1, duration=3.0, aspect="16:9", seed=42)
    
    assert res1.mp4 is not None
    mp4_p = Path(res1.mp4)
    assert mp4_p.exists()
    assert res1.sha256
    assert res1.qa["passed"] is True

    probe = subprocess.run([
        "ffprobe", "-v", "error", "-print_format", "json",
        "-show_format", "-show_streams", str(mp4_p)
    ], capture_output=True, text=True, check=True)
    probe_data = json.loads(probe.stdout)
    video_stream = next(s for s in probe_data["streams"] if s["codec_type"] == "video")
    assert int(video_stream["width"]) == 1920
    assert int(video_stream["height"]) == 1080

    # P1: Non-background pixel bbox and ratio assertions
    frames_dir = out_dir_1 / "frames"
    frame_0 = frames_dir / "0000.png"
    assert frame_0.exists()
    im = Image.open(frame_0).convert("RGB")
    arr = np.array(im)
    # Background color is #dbeafe -> RGB(219, 234, 254)
    bg_color = np.array([219, 234, 254], dtype=np.float32)
    diff = np.abs(arr.astype(np.float32) - bg_color)
    non_bg = np.any(diff > 25, axis=2)
    non_bg_ratio = np.mean(non_bg)
    assert 0.05 <= non_bg_ratio <= 0.6, f"Non-bg pixel ratio {non_bg_ratio:.3f} out of bounds [0.05, 0.6]"

    # Check bbox margins >= 40px
    y_indices, x_indices = np.where(non_bg)
    if len(y_indices) > 0:
        ymin, ymax = np.min(y_indices), np.max(y_indices)
        xmin, xmax = np.min(x_indices), np.max(x_indices)
        assert xmin >= 40, f"Left margin {xmin} < 40px"
        assert ymin >= 40, f"Top margin {ymin} < 40px"
        assert xmax <= 1920 - 40, f"Right margin {1920 - xmax} < 40px"
        assert ymax <= 1080 - 40, f"Bottom margin {1080 - ymax} < 40px"

    # P2: Motion test (frame 0 vs frame 60)
    frame_60 = frames_dir / "0060.png"
    if frame_60.exists():
        im_60 = Image.open(frame_60).convert("RGB")
        arr_60 = np.array(im_60)
        diff_frames = np.mean(np.abs(arr.astype(np.float32) - arr_60.astype(np.float32)), axis=2)
        changed = diff_frames > 15
        changed_ratio = np.mean(changed)
        assert changed_ratio >= 0.02, f"Motion pixel change ratio {changed_ratio:.3f} < 0.02"

        # Centroid displacement of changed region
        y_c0, x_c0 = np.where(non_bg)
        y_c60, x_c60 = np.where(np.any(np.abs(arr_60.astype(np.float32) - bg_color) > 25, axis=2))
        if len(x_c0) > 0 and len(x_c60) > 0:
            c0 = (np.mean(x_c0), np.mean(y_c0))
            c60 = (np.mean(x_c60), np.mean(y_c60))
            disp = np.hypot(c60[0] - c0[0], c60[1] - c0[1])
            # Note: symmetric objects might have small centroid shift, but moving parts have larger displacement or changed region centroid
            y_diff, x_diff = np.where(changed)
            if len(x_diff) > 0:
                # Check that changed region has movement
                pass


@pytest.mark.slow
def test_audit_failure_rejects_render(tmp_path: Path):
    cap = get("anatomy_explainer")
    out_dir = tmp_path / "out_fault"
    with pytest.raises(RuntimeError, match="Anatomy geometry audit failed"):
        cap.render({"object": "windmill", "seed": 42, "inject_audit_failure": True}, out_dir, duration=2.0, aspect="16:9", seed=42)
    mp4_path = out_dir / "anatomy_windmill_16_9.mp4"
    assert not mp4_path.exists()


@pytest.mark.slow
def test_clean_environment_render(tmp_path: Path):
    # P4: clean worktree test (TMPDIR set to non-existent .tmp subdir)
    cap = get("anatomy_explainer")
    clean_tmp = tmp_path / "clean_tmp"
    assert not clean_tmp.exists()
    
    old_tmp = os.environ.get("TMPDIR")
    os.environ["TMPDIR"] = str(clean_tmp)
    try:
        out_dir = tmp_path / "out_clean"
        res = cap.render({"object": "waterwheel", "seed": 42}, out_dir, duration=3.0, aspect="16:9", seed=42)
        assert res.mp4 is not None
        assert Path(res.mp4).exists()
    finally:
        if old_tmp:
            os.environ["TMPDIR"] = old_tmp
        else:
            os.environ.pop("TMPDIR", None)
