"""Tests for qa.final_qc_gate: probe, keyframes, change rate, captions."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

import hevi.capabilities as caps
from hevi.capabilities.final_qc import run_final_qc

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe required",
)


def _ffmpeg(args: list[str]) -> None:
    proc = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", *args],
        capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, proc.stderr


def _video(path: Path, src: str) -> Path:
    _ffmpeg(["-f", "lavfi", "-i", src, "-c:v", "libx264",
             "-pix_fmt", "yuv420p", "-an", str(path)])
    return path


def _moving(path: Path) -> Path:
    return _video(path, "testsrc2=size=320x180:rate=10:duration=4")


def _static(path: Path) -> Path:
    return _video(path, "color=c=red:size=320x180:rate=10:duration=4")


def _black(path: Path) -> Path:
    return _video(path, "color=c=black:size=320x180:rate=10:duration=4")


def _vertical(path: Path) -> Path:
    return _video(path, "testsrc2=size=180x320:rate=10:duration=4")


def test_moving_film_passes_probe_and_change_checks(tmp_path: Path) -> None:
    media = _moving(tmp_path / "moving.mp4")
    report = run_final_qc(
        media, expected_duration_sec=4.0, expected_width=320,
        expected_height=180, expected_codec="h264",
        subtitle_text="hello world", work_dir=tmp_path / "work",
    )
    assert report["probe"]["width"] == 320
    assert report["checks"]["duration"]["pass"] is True
    assert report["checks"]["resolution"]["pass"] is True
    assert report["checks"]["video_codec"]["pass"] is True
    assert report["checks"]["head_tail_clean"]["pass"] is True
    assert report["checks"]["picture_change_rate"]["pass"] is True
    assert report["checks"]["caption_no_emoji"]["pass"] is True
    assert report["verdict"] == "pass"
    assert report["failed_checks"] == []
    assert len(report["visual_review_frames"]) == 3


def test_static_film_fails_change_rate_but_lists_it(tmp_path: Path) -> None:
    media = _static(tmp_path / "static.mp4")
    report = run_final_qc(media, work_dir=tmp_path / "work")
    assert report["checks"]["picture_change_rate"]["pass"] is False
    assert report["verdict"] == "fail"
    assert "picture_change_rate" in report["failed_checks"]


def test_black_film_fails_head_tail(tmp_path: Path) -> None:
    media = _black(tmp_path / "black.mp4")
    report = run_final_qc(media, work_dir=tmp_path / "work")
    assert report["checks"]["head_tail_clean"]["pass"] is False
    assert report["verdict"] == "fail"


def test_wrong_duration_and_emoji_each_fail(tmp_path: Path) -> None:
    media = _moving(tmp_path / "moving.mp4")
    report = run_final_qc(
        media, expected_duration_sec=99.0, subtitle_text="hi \U0001f600",
        work_dir=tmp_path / "work",
    )
    assert report["checks"]["duration"]["pass"] is False
    assert report["checks"]["caption_no_emoji"]["pass"] is False
    assert report["verdict"] == "fail"
    assert set(report["failed_checks"]) >= {"duration", "caption_no_emoji"}


def test_vertical_safe_zone_and_skipped_never_count_as_pass(tmp_path: Path) -> None:
    media = _vertical(tmp_path / "vert.mp4")
    bad = run_final_qc(media, subtitle_bottom_fraction=0.92, work_dir=tmp_path / "w1")
    assert bad["checks"]["vertical_caption_safe_zone"]["pass"] is False
    assert bad["verdict"] == "fail"
    good = run_final_qc(media, subtitle_bottom_fraction=0.70, work_dir=tmp_path / "w2")
    assert good["checks"]["vertical_caption_safe_zone"]["pass"] is True
    nosub = run_final_qc(media, work_dir=tmp_path / "w3")
    assert nosub["checks"]["vertical_caption_safe_zone"]["pass"] is None
    assert "vertical_caption_safe_zone" in nosub["skipped_checks"]


def test_registry_gate(tmp_path: Path) -> None:
    media = _moving(tmp_path / "moving.mp4")
    cap = caps.get("qa.final_qc_gate")
    result = cap.render_safe(
        {"media_path": str(media), "expected_width": 320, "expected_height": 180},
        tmp_path / "out", duration=4.0, aspect="16:9", seed=1,
    )
    assert result.qa["verdict"] == "pass"
    assert result.qa["failed_checks"] == []
