"""Tests for the CPU style_grade ffmpeg pipeline (real ffmpeg, no mock)."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from hevi.layer4_legacy.dirstyle.omodul_impl.grade import (
    build_filter_chain,
    probe_video,
    run_style_grade,
    sha256_file,
)
from hevi.layer4_legacy.dirstyle.oprim_impl import get_style


SAMPLE_W = 1920
SAMPLE_H = 1080
SAMPLE_DUR = 4.0


def _make_test_video(path: Path, *, w: int = SAMPLE_W, h: int = SAMPLE_H,
                     dur: float = SAMPLE_DUR) -> Path:
    """Generate a real test video with testsrc2 + gradient."""
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", (f"testsrc2=size={w}x{h}:rate=30:duration={dur}"),
        "-f", "lavfi",
        "-i", (f"gradients=s={w}x{h}:c0=0x000000:c1=0xffffff:"
               f"speed=0.01:duration={dur}"),
        "-filter_complex",
        "[0:v][1:v]blend=all_mode=screen,format=yuv420p",
        "-c:v", "libx264", "-crf", "18", "-preset", "ultrafast",
        "-t", str(dur),
        str(path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    assert proc.returncode == 0, f"ffmpeg test video generation failed: {proc.stderr[-500:]}"
    return path


@pytest.fixture(scope="module")
def test_video(tmp_path_factory) -> Path:
    p = tmp_path_factory.mktemp("dirstyle_src") / "testsrc.mp4"
    return _make_test_video(p)


class TestBuildFilterChain:
    def test_returns_steps(self):
        style = get_style("wong_kar_wai")
        steps, chain = build_filter_chain(style.grade)
        assert steps, "expected non-empty steps"
        assert chain, "expected non-empty chain string"
        assert all("=" in s or s for s in steps)

    @pytest.mark.parametrize("sid", ["wong_kar_wai", "fincher", "wes_anderson", "zhang_yimou", "hou_hsiao_hsien"])
    def test_chain_contains_filters(self, sid):
        style = get_style(sid)
        _, chain = build_filter_chain(style.grade)
        assert chain
        # every entry has at least one filter name
        for step in style.grade["ffmpeg_steps"]:
            if isinstance(step, dict):
                assert step["filter"] in chain or step["filter"] == "lut3d"


class TestRunStyleGrade:
    """Real ffmpeg runs — no mock, real outputs asserted."""

    @pytest.mark.parametrize("sid,mode", [
        ("wong_kar_wai", "letterbox"),
        ("fincher", "letterbox"),
        ("wes_anderson", "letterbox"),
        ("zhang_yimou", "letterbox"),
        ("hou_hsiao_hsien", "recompose"),
        ("nolan", "letterbox"),
    ])
    def test_grade_real_render(self, test_video, tmp_path, sid, mode):
        style = get_style(sid)
        out = tmp_path / f"{sid}.mp4"
        result = run_style_grade(
            test_video, style.grade, out,
            target_w=1080, target_h=1920,
            aspect_mode=mode,
        )
        assert out.exists()
        assert result.width == 1080, f"width {result.width}"
        assert result.height == 1920, f"height {result.height}"
        assert result.duration_s > 3.5, f"duration {result.duration_s}"
        assert result.codec == "h264"
        assert result.input_sha256 != result.output_sha256
        # ffprobe independently
        info = probe_video(out)
        assert info["width"] == 1080 and info["height"] == 1920

    def test_grade_changes_color_stats(self, test_video, tmp_path):
        """The grade must measurably change the color statistics."""
        import statistics

        def y_mean(path: Path) -> float:
            out = subprocess.run(
                ["ffmpeg", "-i", str(path),
                 "-vf", "signalstats,metadata=print:key=lavfi.signalstats.YAVG",
                 "-f", "null", "-"],
                capture_output=True, text=True, check=False,
            )
            vals = []
            for line in out.stderr.splitlines():
                if "lavfi.signalstats.YAVG" in line:
                    # format: lavfi.signalstats.YAVG=122.076
                    for part in line.split():
                        if "YAVG=" in part:
                            try:
                                vals.append(float(part.split("=", 1)[1]))
                            except ValueError:
                                pass
            return statistics.mean(vals) if vals else 0.0

        before = y_mean(test_video)
        # zhang_yimou: heavy saturation + hue shift → definitely different
        style = get_style("zhang_yimou")
        out = tmp_path / "zhang.mp4"
        run_style_grade(test_video, style.grade, out,
                        target_w=1080, target_h=1920,
                        aspect_mode="letterbox")
        after = y_mean(out)
        # Allow some tolerance — but they MUST differ measurably
        diff = abs(after - before)
        assert diff > 1.0, f"y_mean unchanged: before={before:.2f} after={after:.2f}"


class TestLetterboxPreservesContent:
    def test_letterbox_does_not_crop_wide(self, test_video, tmp_path):
        """A wide 16:9 source must fit inside 9:16 with black bars,
        not be cropped to a vertical strip."""
        style = get_style("wong_kar_wai")
        out = tmp_path / "letterboxed.mp4"
        run_style_grade(test_video, style.grade, out,
                        target_w=1080, target_h=1920,
                        aspect_mode="letterbox")
        # Extract a frame and measure black bars
        frame = tmp_path / "frame.png"
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(out),
             "-vf", "select=eq(n\\,30)", "-vframes", "1", str(frame)],
            capture_output=True, text=True, check=True,
        )
        assert frame.exists()
        # Use PIL to measure: content should span full width
        from PIL import Image
        img = Image.open(frame)
        assert img.size == (1080, 1920)
        # Convert to grayscale, check top/bottom rows are black (letterbox)
        gray = img.convert("L")
        px = gray.load()
        # top 3 rows should be near-black (letterbox bars)
        top_black = all(px[x, 0] < 20 for x in range(0, 1080, 50))
        bottom_black = all(px[x, 1919] < 20 for x in range(0, 1080, 50))
        # the middle row should have content (not all black)
        mid = [px[x, 960] for x in range(0, 1080, 10)]
        mid_has_content = max(mid) > 50
        assert top_black and bottom_black, "missing letterbox black bars"
        assert mid_has_content, "middle row is all black — content missing"
