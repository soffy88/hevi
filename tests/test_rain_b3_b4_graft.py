"""Tests for the rain-before-stops B3/B4 graft (clean-room).

B3: two-image alignment is judged on synthetic fixture pictures
drawn by the test itself (a window frame with panes); the gate
sees only the caller-supplied structure points and pane counts.
B4: confirmed-text overlay runs on a synthetic solid-colour clip
made locally with ffmpeg; no price and no Seedance route is
involved anywhere in this file.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from hevi.capabilities import get as _get_capability
from hevi.capabilities.confirmed_text_overlay import (
    _probe_video,
    check_confirmed_text,
    overlay_confirmed_text,
)
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.two_image_alignment_gate import check_two_image_alignment

FFMPEG_OK = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


# ---- B3 fixtures: a window frame with panes ----

def _draw_window(path: Path, *, x0: int, y0: int, panes: int, size=(320, 240)) -> Path:
    from PIL import Image, ImageDraw

    image = Image.new("RGB", size, (200, 190, 170))
    draw = ImageDraw.Draw(image)
    x1, y1 = x0 + 160, y0 + 120
    draw.rectangle([x0, y0, x1, y1], outline=(40, 40, 40), width=4)
    for index in range(1, panes):
        mx = x0 + (160 * index) // panes
        draw.line([(mx, y0), (mx, y1)], fill=(40, 40, 40), width=3)
    draw.line([(x0, y0 + 60), (x1, y0 + 60)], fill=(40, 40, 40), width=3)
    image.save(path)
    return path


def _points(x0: int, y0: int, panes: int) -> list[dict]:
    points = [
        {"id": "frame_tl", "x": x0, "y": y0},
        {"id": "frame_tr", "x": x0 + 160, "y": y0},
        {"id": "frame_bl", "x": x0, "y": y0 + 120},
        {"id": "frame_br", "x": x0 + 160, "y": y0 + 120},
    ]
    for index in range(1, panes):
        points.append(
            {"id": f"mullion_{index}", "x": x0 + (160 * index) // panes, "y": y0 + 60}
        )
    return points


def _record(path: Path, *, x0: int, y0: int, panes: int) -> dict:
    return {
        "image_path": str(path),
        "structures": _points(x0, y0, panes),
        "repeated_count": panes,
        "frame_region": {"x": 0, "y": 0, "w": 320, "h": 240},
    }


def test_b3_aligned_pair_passes(tmp_path):
    before = _draw_window(tmp_path / "before.png", x0=40, y0=30, panes=3)
    after = _draw_window(tmp_path / "after.png", x0=40, y0=30, panes=3)
    report = check_two_image_alignment(
        _record(before, x0=40, y0=30, panes=3),
        _record(after, x0=40, y0=30, panes=3),
        tolerance_px=5,
    )
    assert report["verdict"] == "pass", report["issues"]
    assert report["max_displacement_px"] == 0.0
    assert report["mean_pixel_difference"] == 0.0
    assert report["repeated_count"] == {"before": 3, "after": 3}


def test_b3_shifted_frame_and_lost_pane_fail(tmp_path):
    before = _draw_window(tmp_path / "before.png", x0=40, y0=30, panes=3)
    after = _draw_window(tmp_path / "after.png", x0=65, y0=40, panes=2)
    report = check_two_image_alignment(
        _record(before, x0=40, y0=30, panes=3),
        _record(after, x0=65, y0=40, panes=2),
        tolerance_px=5,
    )
    assert report["verdict"] == "fail"
    codes = {issue["code"] for issue in report["issues"]}
    assert "displacement_over_tolerance" in codes
    assert "repeated_count_mismatch" in codes
    assert "point_missing_after" in codes  # mullion_2 has no counterpart
    assert report["max_displacement_px"] is not None
    assert report["max_displacement_px"] > 5


def test_b3_missing_point_is_named(tmp_path):
    before = _draw_window(tmp_path / "before.png", x0=40, y0=30, panes=2)
    after = _draw_window(tmp_path / "after.png", x0=40, y0=30, panes=2)
    after_record = _record(after, x0=40, y0=30, panes=2)
    after_record["structures"] = [
        p for p in after_record["structures"] if p["id"] != "frame_br"
    ]
    report = check_two_image_alignment(
        _record(before, x0=40, y0=30, panes=2), after_record, tolerance_px=5
    )
    assert report["verdict"] == "fail"
    assert any(
        issue["code"] == "point_missing_after" and issue["point_id"] == "frame_br"
        for issue in report["issues"]
    )


def test_b3_size_mismatch_fails(tmp_path):
    before = _draw_window(tmp_path / "before.png", x0=40, y0=30, panes=2)
    after = _draw_window(tmp_path / "after.png", x0=40, y0=30, panes=2, size=(320, 200))
    report = check_two_image_alignment(
        _record(before, x0=40, y0=30, panes=2),
        _record(after, x0=40, y0=30, panes=2),
        tolerance_px=5,
    )
    assert report["verdict"] == "fail"
    assert any(issue["code"] == "size_mismatch" for issue in report["issues"])


def test_b3_tolerance_is_required_and_missing_file_raises(tmp_path):
    before = _draw_window(tmp_path / "before.png", x0=40, y0=30, panes=2)
    after = _draw_window(tmp_path / "after.png", x0=40, y0=30, panes=2)
    with pytest.raises(CapabilityError, match="tolerance_px"):
        check_two_image_alignment(
            _record(before, x0=40, y0=30, panes=2),
            _record(after, x0=40, y0=30, panes=2),
            tolerance_px=None,
        )
    with pytest.raises(CapabilityError, match="tolerance_px"):
        check_two_image_alignment(
            _record(before, x0=40, y0=30, panes=2),
            _record(after, x0=40, y0=30, panes=2),
            tolerance_px=0,
        )
    missing = _record(before, x0=40, y0=30, panes=2)
    missing["image_path"] = str(tmp_path / "no_such.png")
    with pytest.raises(CapabilityError, match="not found"):
        check_two_image_alignment(
            missing, _record(after, x0=40, y0=30, panes=2), tolerance_px=5
        )


def test_b3_registered_on_the_registry():
    capability = _get_capability("qa.two_image_alignment_gate")
    assert capability.name == "qa.two_image_alignment_gate"


# ---- B4: confirmed-text overlay on a synthetic clip ----

def _fake_clip(path: Path) -> Path:
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "color=c=0x2a4a6a:s=320x180:d=2:r=24",
            "-an", str(path),
        ],
        check=True,
    )
    return path


def _record_b4(**overrides):
    record = {
        "text_id": "letter-1",
        "text": "雨停之前，我们再见。",
        "version": 2,
        "confirmed": True,
        "confirmed_by": "作者",
    }
    record.update(overrides)
    return record


_SCRIPT = "开场雨声。信纸上写着：雨停之前，我们再见。镜头停住。"


def _placement(**overrides):
    placement = {
        "x": 20, "y": 120, "start_s": 0.5, "end_s": 1.5,
        "fontsize": 28, "color": "#FFFFFF",
    }
    placement.update(overrides)
    return placement


@pytest.mark.skipif(not FFMPEG_OK, reason="ffmpeg/ffprobe not on PATH")
def test_b4_overlay_lands_confirmed_text(tmp_path):
    source = _fake_clip(tmp_path / "source.mp4")
    out = tmp_path / "out.mp4"
    report = overlay_confirmed_text(
        source, _record_b4(), _SCRIPT, _placement(), out
    )
    assert report["verdict"] == "pass"
    assert report["text_id"] == "letter-1"
    assert report["version"] == 2
    assert report["frames_overlaid"] > 0
    assert report["placement_pixels_changed"] >= 20
    assert Path(report["output_video"]).is_file()
    info = _probe_video(out)
    assert abs(info["duration"] - 2.0) < 0.15
    assert info["width"] == 320 and info["height"] == 180


def test_b4_check_passes_for_confirmed_matching_record():
    report = check_confirmed_text(_record_b4(), _SCRIPT)
    assert report["verdict"] == "pass", report["issues"]


@pytest.mark.skipif(not FFMPEG_OK, reason="ffmpeg/ffprobe not on PATH")
def test_b4_unconfirmed_record_overlays_nothing(tmp_path):
    source = _fake_clip(tmp_path / "source.mp4")
    out = tmp_path / "out.mp4"
    with pytest.raises(CapabilityError, match="not_confirmed"):
        overlay_confirmed_text(
            source, _record_b4(confirmed=False), _SCRIPT, _placement(), out
        )
    assert not out.exists()


@pytest.mark.skipif(not FFMPEG_OK, reason="ffmpeg/ffprobe not on PATH")
def test_b4_superseded_and_mismatched_text_fail_closed(tmp_path):
    source = _fake_clip(tmp_path / "source.mp4")
    with pytest.raises(CapabilityError, match="superseded"):
        overlay_confirmed_text(
            source, _record_b4(superseded_by="letter-1-v3"), _SCRIPT,
            _placement(), tmp_path / "a.mp4",
        )
    with pytest.raises(CapabilityError, match="text_script_mismatch"):
        overlay_confirmed_text(
            source, _record_b4(text="另一句没写进剧本的话。"), _SCRIPT,
            _placement(), tmp_path / "b.mp4",
        )
    with pytest.raises(CapabilityError, match="version_invalid"):
        overlay_confirmed_text(
            source, _record_b4(version=0), _SCRIPT,
            _placement(), tmp_path / "c.mp4",
        )


@pytest.mark.skipif(not FFMPEG_OK, reason="ffmpeg/ffprobe not on PATH")
def test_b4_placement_past_duration_fails(tmp_path):
    source = _fake_clip(tmp_path / "source.mp4")
    with pytest.raises(CapabilityError, match="past the source duration"):
        overlay_confirmed_text(
            source, _record_b4(), _SCRIPT,
            _placement(start_s=1.0, end_s=3.0), tmp_path / "out.mp4",
        )


def test_b4_registered_on_the_registry():
    capability = _get_capability("video.confirmed_text_overlay")
    assert capability.name == "video.confirmed_text_overlay"
