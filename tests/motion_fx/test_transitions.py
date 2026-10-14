"""Tests for motion_fx transitions."""

import subprocess
import tempfile
from pathlib import Path

import cv2
import numpy as np
import pytest

from hevi.motion_fx.transitions import (
    REGISTRY,
    apply_transition,
    get_transition_func,
    probe_video,
)


@pytest.fixture(scope="module")
def sample_clips():
    """Create two short test clips in a temporary directory."""
    tmpdir = Path(tempfile.mkdtemp())
    w, h, fps = 360, 640, 25

    clip_a = tmpdir / "fixture_clip_a.mp4"
    clip_b = tmpdir / "fixture_clip_b.mp4"

    def make_clip(p, color_start, color_end, title, duration_sec):
        n = int(round(duration_sec * fps))
        cmd = [
            "ffmpeg", "-y",
            "-f", "rawvideo",
            "-vcodec", "rawvideo",
            "-s", f"{w}x{h}",
            "-pix_fmt", "bgr24",
            "-r", str(fps),
            "-i", "-",
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            str(p),
        ]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for i in range(n):
            t = i / float(max(1, n - 1))
            c = (np.array(color_start) * (1 - t) + np.array(color_end) * t).astype(np.uint8)
            img = np.full((h, w, 3), c, dtype=np.uint8)
            cv2.putText(img, f"{title} {i}", (30, h // 2), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)
            proc.stdin.write(img.tobytes())
        proc.stdin.close()
        proc.wait()

    make_clip(clip_a, [40, 40, 180], [20, 120, 200], "SCENE A", 2.0)
    make_clip(clip_b, [180, 40, 40], [200, 150, 30], "SCENE B", 2.0)

    return {"clip_a": clip_a, "clip_b": clip_b, "tmpdir": tmpdir, "fps": fps, "w": w, "h": h}


@pytest.mark.parametrize("kind", ["line_to_structure", "water_ripple", "glass_refract"])
def test_transitions_duration_and_encoding(sample_clips, kind):
    clip_a = sample_clips["clip_a"]
    clip_b = sample_clips["clip_b"]
    tmpdir = sample_clips["tmpdir"]
    fps = sample_clips["fps"]
    w = sample_clips["w"]
    h = sample_clips["h"]

    dur = 0.8
    out = tmpdir / f"test_{kind}.mp4"

    apply_transition(clip_a, clip_b, kind=kind, dur=dur, out=out)
    assert out.is_file()

    info = probe_video(out)
    # Expected duration: 2.0 + 2.0 - 0.8 = 3.2s
    # Total frames: 50 + 50 - 20 = 80 frames
    expected_frames = int(round((2.0 + 2.0 - dur) * fps))
    assert abs(info.total_frames - expected_frames) <= 1
    assert abs(info.duration - (2.0 + 2.0 - dur)) <= 0.08
    assert info.width == w
    assert info.height == h

    # Check codec using ffprobe directly
    proc = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=codec_name,pix_fmt",
            "-of", "csv=p=0",
            str(out),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    output = proc.stdout.strip()
    assert "h264" in output
    assert "yuv420p" in output


@pytest.mark.parametrize("kind", ["line_to_structure", "water_ripple", "glass_refract"])
def test_transition_middle_frame_differs(sample_clips, kind):
    clip_a = sample_clips["clip_a"]
    clip_b = sample_clips["clip_b"]
    tmpdir = sample_clips["tmpdir"]

    out = tmpdir / f"test_{kind}_mid.mp4"
    apply_transition(clip_a, clip_b, kind=kind, dur=1.0, out=out)

    cap = cv2.VideoCapture(str(out))
    frames = []
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        frames.append(frame)
    cap.release()

    assert len(frames) > 10
    f_start = frames[0]
    f_mid = frames[len(frames) // 2]
    f_end = frames[-1]

    diff_start_mid = float(np.mean(np.abs(f_start.astype(float) - f_mid.astype(float))))
    diff_mid_end = float(np.mean(np.abs(f_mid.astype(float) - f_end.astype(float))))

    # Middle frame should be significantly different from start and end (> 20.0 pixel intensity)
    assert diff_start_mid > 20.0
    assert diff_mid_end > 20.0


def test_transition_with_bpm_snapped_start(sample_clips):
    clip_a = sample_clips["clip_a"]
    clip_b = sample_clips["clip_b"]
    tmpdir = sample_clips["tmpdir"]

    out = tmpdir / "test_bpm_snapped.mp4"
    # start at 0.9s, at 120 bpm, div=4 (quarter note step = 0.5s), snaps to 1.0s
    apply_transition(
        clip_a, clip_b,
        kind="line_to_structure",
        dur=0.6,
        params={"bpm": 120, "division": 4},
        start=0.9,
        out=out,
    )

    info = probe_video(out)
    # Clip a plays 1.0s (25 frames), transition 0.6s (15 frames), clip b plays 2.0-0.6 = 1.4s (35 frames)
    # Total frames = 25 + 15 + 35 = 75 frames (3.0s)
    assert abs(info.total_frames - 75) <= 1


def test_unknown_transition():
    with pytest.raises(ValueError, match="Unknown transition kind"):
        get_transition_func("non_existent_transition")
