"""Tests for 9:16 auto-reframe and multi-aspect exporter."""

import subprocess
import tempfile
from pathlib import Path

import cv2
import numpy as np
import pytest

from hevi.motion_fx.reframe import (
    compute_reframe_windows,
    detect_subject,
    reframe,
    render_multi_aspect,
)
from hevi.motion_fx.transitions import probe_video


@pytest.fixture(scope="module")
def sample_16x9_video():
    """Create a synthetic 16:9 test video (640x360) with a moving salient subject."""
    tmpdir = Path(tempfile.mkdtemp())
    video_path = tmpdir / "sample_16x9.mp4"
    w, h, fps = 640, 360, 25

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
        str(video_path),
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for i in range(50):
        img = np.full((h, w, 3), [15, 15, 15], dtype=np.uint8)
        # Salient moving subject
        x = int(120 + i * 5)
        img[80:280, x:x+90] = [230, 210, 180]
        proc.stdin.write(img.tobytes())
    proc.stdin.close()
    proc.wait()

    return video_path


def test_detect_subject():
    frame = np.full((360, 640, 3), [10, 10, 10], dtype=np.uint8)
    frame[100:260, 200:300] = [240, 240, 240]

    det = detect_subject(frame)
    # Centroid should be around x=250, y=180
    assert 180 <= det.cx <= 320
    assert 120 <= det.cy <= 240
    assert det.width > 0


def test_reframe_crop_bounds_and_coverage(sample_16x9_video):
    is_vert, w_crop, h_crop, x_seq, metrics = compute_reframe_windows(
        sample_16x9_video,
        aspect="9:16",
    )

    assert not is_vert
    assert h_crop == 360  # No top/bottom black bars
    assert w_crop == 202  # 360 * 9 / 16 ~ 202

    info = probe_video(sample_16x9_video)
    w_in = info.width

    # Check bounds for all frames
    for x in x_seq:
        assert x >= 0
        assert x + w_crop <= w_in

    # Check subject coverage >= 50%
    assert metrics["subject_coverage"] >= 0.50


def test_reframe_render_output(sample_16x9_video):
    tmpdir = sample_16x9_video.parent
    out = tmpdir / "reframed_output.mp4"

    reframe(sample_16x9_video, out, aspect="9:16")
    assert out.is_file()

    info = probe_video(out)
    assert info.height == 360
    assert info.width == 202
    assert abs(info.duration - 2.0) <= 0.1


def test_reframe_passthrough_for_vertical():
    tmpdir = Path(tempfile.mkdtemp())
    vert_clip = tmpdir / "vert_clip.mp4"
    w, h, fps = 360, 640, 25

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
        str(vert_clip),
    ]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(25):
        img = np.zeros((h, w, 3), dtype=np.uint8)
        p.stdin.write(img.tobytes())
    p.stdin.close()
    p.wait()

    out_pass = tmpdir / "vert_passthrough.mp4"
    reframe(vert_clip, out_pass, aspect="9:16")

    info = probe_video(out_pass)
    assert info.width == 360
    assert info.height == 640


def test_render_multi_aspect_parallel():
    tmpdir = Path(tempfile.mkdtemp())
    html_file = tmpdir / "multi_test.html"
    html_file.write_text("""<!DOCTYPE html>
<html>
<body style="margin:0;overflow:hidden;background:#050811;">
<canvas id="c"></canvas>
<script>
  const canvas = document.getElementById("c");
  const ctx = canvas.getContext("2d");
  function resize() {
    canvas.width = window.innerWidth || 360;
    canvas.height = window.innerHeight || 640;
  }
  window.addEventListener("resize", resize);
  resize();
  window.draw = function(t) {
    const w = canvas.width;
    const h = canvas.height;
    ctx.fillStyle = "#050811";
    ctx.fillRect(0, 0, w, h);
    ctx.fillStyle = "#38bdf8";
    ctx.fillRect(w * 0.3, h * 0.3, w * 0.4, h * 0.4);
  };
</script>
</body>
</html>""")

    res = render_multi_aspect(
        html_file,
        tmpdir,
        aspects=["9:16", "16:9", "1:1"],
        duration=0.3,
        fps=30,
        subframes=2,
        base_dim=360,
    )

    assert "9:16" in res
    assert "16:9" in res
    assert "1:1" in res

    info_916 = probe_video(res["9:16"])
    info_169 = probe_video(res["16:9"])
    info_11 = probe_video(res["1:1"])

    assert info_916.width == 360 and info_916.height == 640
    assert info_169.width == 640 and info_169.height == 360
    assert info_11.width == 360 and info_11.height == 360


def test_reframe_interview_face_containment_and_smoothness():
    """AMFX-R2 H1 & H2: Interview video must achieve >=90% subject containment and p95<=8, max<=20."""
    interview_candidates = [
        Path("samples/aimotion_fx/src_interview_16x9_6s.mp4"),
        Path("artifacts/real_video/20261005T160434Z/artifacts/scene_interview_720p.mp4"),
    ]
    vid = next((p for p in interview_candidates if p.is_file()), None)
    if vid is None:
        pytest.skip("Interview video asset not found")

    is_vert, w_crop, h_crop, x_seq, metrics = compute_reframe_windows(
        vid,
        aspect="9:16",
        smooth_alpha=0.08,
        max_velocity=7.5,
    )

    assert not is_vert
    assert len(x_seq) > 50

    # AMFX-R2 H1: Face/body subject containment >= 90%
    assert metrics["subject_in_window_ratio"] >= 0.90, (
        f"Subject containment ratio {metrics['subject_in_window_ratio']:.4f} is below required 90%"
    )

    # AMFX-R2 H2: Within-shot frame-to-frame displacement p95 <= 8, max <= 20
    assert metrics["displacement_p95"] <= 8.0, (
        f"Within-shot displacement p95 ({metrics['displacement_p95']} px) exceeds 8.0 px/frame limit"
    )
    assert metrics["displacement_max"] <= 20.0, (
        f"Within-shot displacement max ({metrics['displacement_max']} px) exceeds 20.0 px/frame limit"
    )


def test_reframe_broll_smoothness():
    """AMFX-R2 H2: B-roll video without cuts must have smooth camera motion with p95<=8, max<=20."""
    broll_candidates = [
        Path("samples/aimotion_fx/src_broll_16x9_6s.mp4"),
        Path("artifacts/real_video/20261005T160434Z/artifacts/scene_broll_720p.mp4"),
    ]
    vid = next((p for p in broll_candidates if p.is_file()), None)
    if vid is None:
        pytest.skip("B-roll video asset not found")

    is_vert, w_crop, h_crop, x_seq, metrics = compute_reframe_windows(
        vid,
        aspect="9:16",
        smooth_alpha=0.08,
        max_velocity=7.5,
    )

    assert not is_vert
    assert len(x_seq) > 50

    # AMFX-R2 H2: Within-shot frame-to-frame displacement p95 <= 8, max <= 20
    assert metrics["displacement_p95"] <= 8.0, (
        f"Within-shot displacement p95 ({metrics['displacement_p95']} px) exceeds 8.0 px/frame limit"
    )
    assert metrics["displacement_max"] <= 20.0, (
        f"Within-shot displacement max ({metrics['displacement_max']} px) exceeds 20.0 px/frame limit"
    )

