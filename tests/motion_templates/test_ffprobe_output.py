"""FFprobe media compliance tests for rendered motion template outputs."""

import json
import subprocess
from pathlib import Path
import pytest

SAMPLES_DIR = Path(__file__).resolve().parents[2] / "samples" / "aimotion"


def probe_media(mp4_path: Path) -> dict:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "stream=width,height,r_frame_rate,duration,codec_name,pix_fmt",
        "-show_entries",
        "format=duration,size",
        "-of",
        "json",
        str(mp4_path),
    ]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
    return json.loads(res.stdout)


def get_rendered_samples() -> list[Path]:
    assert SAMPLES_DIR.is_dir(), f"Samples dir {SAMPLES_DIR} must exist"
    samples = sorted(list(SAMPLES_DIR.glob("*.mp4")))
    assert len(samples) >= 6, f"Expected at least 6 rendered MP4 samples, found {len(samples)}"
    return samples


@pytest.mark.parametrize("mp4_path", get_rendered_samples())
def test_sample_ffprobe_invariants(mp4_path: Path):
    info = probe_media(mp4_path)
    streams = info.get("streams", [])
    video_streams = [s for s in streams if s.get("codec_name") == "h264"]
    assert len(video_streams) >= 1, f"Expected at least one H.264 video stream in {mp4_path.name}"

    v = video_streams[0]
    w = int(v["width"])
    h = int(v["height"])
    fps = v["r_frame_rate"]
    pix_fmt = v.get("pix_fmt")

    # 1. Aspect ratio resolution check
    if "9_16" in mp4_path.stem:
        assert (w, h) == (1080, 1920), f"Expected 1080x1920 for 9:16, got {w}x{h}"
    elif "16_9" in mp4_path.stem:
        assert (w, h) == (1920, 1080), f"Expected 1920x1080 for 16:9, got {w}x{h}"
    elif "1_1" in mp4_path.stem:
        assert (w, h) == (1080, 1080), f"Expected 1080x1080 for 1:1, got {w}x{h}"

    # 2. Framerate check (30fps)
    assert fps == "30/1", f"Expected 30fps, got {fps}"

    # 3. Pixel format check
    assert pix_fmt == "yuv420p", f"Expected yuv420p, got {pix_fmt}"

    # 4. Duration check (<= 15.0s)
    duration = float(info.get("format", {}).get("duration", v.get("duration", 0)))
    assert 0 < duration <= 15.0, f"Duration must be <= 15.0s, got {duration}"

    # 5. File size check (< 20MB)
    size_bytes = mp4_path.stat().st_size
    assert size_bytes < 20 * 1024 * 1024, f"File size exceeds 20MB limit: {size_bytes} bytes"
