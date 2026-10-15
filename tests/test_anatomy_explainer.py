from __future__ import annotations

import pytest
from pathlib import Path
import json
import subprocess
from PIL import Image
import numpy as np

from hevi.capabilities import get, list as list_capabilities
from hevi.capabilities.anatomy_explainer.renderer import validate_anatomy_params


def test_anatomy_capability_registered():
    caps = list_capabilities(kind="shot")
    names = [c.name for c in caps]
    assert "anatomy_explainer" in names
    cap = get("anatomy_explainer")
    assert cap.aspects == ["16:9", "9:16"]


def test_anatomy_params_validation():
    # Valid
    valid = validate_anatomy_params({"object": "windmill", "duration": 5.0, "seed": 123})
    assert valid["object"] == "windmill"
    assert valid["duration"] == 5.0

    # Invalid object
    with pytest.raises(ValueError):
        validate_anatomy_params({"object": "invalid_robot", "duration": 4.0})

    # Invalid duration
    with pytest.raises(ValueError):
        validate_anatomy_params({"object": "waterwheel", "duration": 1.0})
    with pytest.raises(ValueError):
        validate_anatomy_params({"object": "soap_pump", "duration": 20.0})


@pytest.mark.slow
def test_anatomy_render_and_assertions(tmp_path: Path):
    cap = get("anatomy_explainer")
    
    # Render windmill in 16:9, short duration (3s) for speed
    out_dir_1 = tmp_path / "out_16_9"
    res1 = cap.render({"object": "windmill", "seed": 42}, out_dir_1, duration=3.0, aspect="16:9", seed=42)
    
    assert res1.mp4 is not None
    mp4_p = Path(res1.mp4)
    assert mp4_p.exists()
    assert res1.sha256
    assert res1.qa["passed"] is True

    # Check ffprobe via probe_video_stats or direct ffprobe call
    probe = subprocess.run([
        "ffprobe", "-v", "error", "-print_format", "json",
        "-show_format", "-show_streams", str(mp4_p)
    ], capture_output=True, text=True, check=True)
    probe_data = json.loads(probe.stdout)
    video_stream = next(s for s in probe_data["streams"] if s["codec_type"] == "video")
    assert int(video_stream["width"]) == 1920
    assert int(video_stream["height"]) == 1080

    # Test sha consistency (same params + seed twice)
    out_dir_2 = tmp_path / "out_16_9_repeat"
    res2 = cap.render({"object": "windmill", "seed": 42}, out_dir_2, duration=3.0, aspect="16:9", seed=42)
    assert res1.sha256 == res2.sha256

    # Test portrait 9:16 render & font size / saturation assertion
    out_dir_916 = tmp_path / "out_9_16"
    res3 = cap.render({"object": "soap_pump", "seed": 42}, out_dir_916, duration=3.0, aspect="9:16", seed=42)
    assert res3.mp4 is not None
    probe916 = subprocess.run([
        "ffprobe", "-v", "error", "-print_format", "json",
        "-show_streams", res3.mp4
    ], capture_output=True, text=True, check=True)
    v916 = next(s for s in json.loads(probe916.stdout)["streams"] if s["codec_type"] == "video")
    assert int(v916["width"]) == 1080
    assert int(v916["height"]) == 1920

    # Real pixel saturation assertion across the frame using standard RGB formula
    frames_dir = out_dir_916 / "frames"
    frame_0 = frames_dir / "0000.png"
    if frame_0.exists():
        im = Image.open(frame_0).convert("RGB")
        arr = np.array(im, dtype=np.float32) / 255.0
        max_c = np.max(arr, axis=2)
        min_c = np.min(arr, axis=2)
        diff = max_c - min_c
        with np.errstate(divide='ignore', invalid='ignore'):
            sat = np.where(max_c > 0, diff / max_c, 0)
        mean_sat = np.mean(sat)
        assert mean_sat >= 0.35, f"Mean frame saturation {mean_sat:.2f} < 0.35"
