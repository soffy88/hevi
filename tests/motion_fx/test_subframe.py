"""Tests for subframe motion blur rendering and metrics."""

import tempfile
from pathlib import Path

import cv2
import numpy as np
import pytest

from hevi.motion_fx.subframe import (
    apply_tmix_motion_blur,
    compute_blur_metrics,
    render_html_subframes,
)
from hevi.motion_fx.transitions import probe_video


@pytest.fixture(scope="module")
def fast_motion_html():
    tmpdir = Path(tempfile.mkdtemp())
    html_file = tmpdir / "fast_motion_test.html"
    html_file.write_text("""<!DOCTYPE html>
<html>
<body style="margin:0;overflow:hidden;background:#000000;">
<canvas id="c"></canvas>
<script>
  const canvas = document.getElementById("c");
  const ctx = canvas.getContext("2d");
  canvas.width = window.innerWidth || 360;
  canvas.height = window.innerHeight || 640;
  window.draw = function(t) {
    const w = canvas.width;
    const h = canvas.height;
    ctx.fillStyle = "#000000";
    ctx.fillRect(0, 0, w, h);
    
    // Fast moving bright card: 1200 px/s
    const speed = 1200;
    const x = (t * speed) % (w + 200) - 100;
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(x, h * 0.4, 80, 160);
  };
</script>
</body>
</html>""")
    return html_file


def test_subframe_blur_comparison(fast_motion_html):
    tmpdir = fast_motion_html.parent
    out_n1 = tmpdir / "test_motion_n1.mp4"
    out_n6 = tmpdir / "test_motion_n6.mp4"

    # Render short 0.4s clip (12 frames at 30fps) for N=1 and N=6
    render_html_subframes(
        fast_motion_html,
        out_n1,
        duration=0.4,
        fps=30,
        subframes=1,
        width=360,
        height=640,
    )
    render_html_subframes(
        fast_motion_html,
        out_n6,
        duration=0.4,
        fps=30,
        subframes=6,
        width=360,
        height=640,
    )

    info_n1 = probe_video(out_n1)
    info_n6 = probe_video(out_n6)
    assert info_n1.total_frames >= 11
    assert info_n6.total_frames >= 11
    assert info_n1.width == 360 and info_n1.height == 640

    def get_frame(p, idx):
        cap = cv2.VideoCapture(str(p))
        frames = []
        while True:
            ret, f = cap.read()
            if not ret:
                break
            frames.append(f)
        cap.release()
        return frames[idx]

    mid_idx = info_n1.total_frames // 2
    f_n1 = get_frame(out_n1, mid_idx)
    f_n6 = get_frame(out_n6, mid_idx)

    m_n1 = compute_blur_metrics(f_n1)
    m_n6 = compute_blur_metrics(f_n6)

    # N=6 should have smoother edges (lower Laplacian variance)
    assert m_n6["laplacian_var"] < m_n1["laplacian_var"]

    # N=6 should have an intermediate blur trail
    assert m_n6["intermediate_pixels"] > m_n1["intermediate_pixels"]


def test_subframe_fps_parameterization(fast_motion_html):
    tmpdir = fast_motion_html.parent
    out_60fps = tmpdir / "test_60fps.mp4"

    render_html_subframes(
        fast_motion_html,
        out_60fps,
        duration=0.5,
        fps=60,
        subframes=4,
        width=360,
        height=640,
    )
    info = probe_video(out_60fps)
    assert abs(info.fps - 60.0) < 1.0
    assert info.total_frames >= 28


def test_tmix_motion_blur():
    tmpdir = Path(tempfile.mkdtemp())
    src = tmpdir / "src_highfps.mp4"
    w, h, fps = 320, 240, 60

    # Build 1s 60fps video
    import subprocess
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
        str(src),
    ]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for i in range(60):
        img = np.zeros((h, w, 3), dtype=np.uint8)
        x = (i * 10) % (w - 40)
        img[80:160, x:x+40] = 255
        p.stdin.write(img.tobytes())
    p.stdin.close()
    p.wait()

    out = tmpdir / "tmix_30fps.mp4"
    apply_tmix_motion_blur(src, out, subframes=4, target_fps=30)
    info = probe_video(out)
    assert out.is_file()
    assert abs(info.fps - 30.0) < 1.0
