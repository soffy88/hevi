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


# ---------------------------------------------------------------- stale timeline + generation consistency (audit fix 8)

def _consistency_artifacts() -> dict:
    from hevi.capabilities.prompt_eval_harness import (
        build_generation_consistency_fixture,
    )

    return build_generation_consistency_fixture()


def test_stale_timeline_fails_when_edited_without_fresh_transcript(tmp_path: Path) -> None:
    media = _moving(tmp_path / "moving.mp4")
    stale = run_final_qc(
        media, expected_duration_sec=4.0, work_dir=tmp_path / "w1",
        edited=True, transcript_source="pre_edit_timeline",
    )
    assert stale["checks"]["stale_timeline"]["pass"] is False
    assert stale["verdict"] == "fail"
    assert "stale_timeline" in stale["failed_checks"]
    missing = run_final_qc(
        media, expected_duration_sec=4.0, work_dir=tmp_path / "w2", edited=True,
    )
    assert missing["checks"]["stale_timeline"]["pass"] is False
    assert missing["verdict"] == "fail"
    fresh = run_final_qc(
        media, expected_duration_sec=4.0, work_dir=tmp_path / "w3",
        edited=True, transcript_source="post_edit_retranscription",
    )
    assert fresh["checks"]["stale_timeline"]["pass"] is True
    assert fresh["verdict"] == "pass"


def test_stale_timeline_skipped_when_no_edit_declared(tmp_path: Path) -> None:
    media = _moving(tmp_path / "moving.mp4")
    report = run_final_qc(media, expected_duration_sec=4.0, work_dir=tmp_path / "w")
    assert report["checks"]["stale_timeline"]["pass"] is None
    assert "stale_timeline" in report["skipped_checks"]


def test_generation_consistency_from_offline_artifacts(tmp_path: Path) -> None:
    media = _moving(tmp_path / "moving.mp4")
    good = run_final_qc(
        media, expected_duration_sec=4.0, work_dir=tmp_path / "w1",
        generation_artifacts=_consistency_artifacts(),
    )
    assert good["checks"]["generation_consistency"]["pass"] is True
    assert good["generation_consistency"]["verdict"] == "pass"
    assert good["verdict"] == "pass"
    bad_artifacts = _consistency_artifacts()
    bad_artifacts["asr_text"] = "完全不相干的旁白。"
    bad = run_final_qc(
        media, expected_duration_sec=4.0, work_dir=tmp_path / "w2",
        generation_artifacts=bad_artifacts,
    )
    assert bad["checks"]["generation_consistency"]["pass"] is False
    assert bad["verdict"] == "fail"
    partial = run_final_qc(
        media, expected_duration_sec=4.0, work_dir=tmp_path / "w3",
        generation_artifacts={"prompt": {"expected_lines": ["玉兰开了"]}},
    )
    assert partial["checks"]["generation_consistency"]["pass"] is False
    skipped = run_final_qc(media, expected_duration_sec=4.0, work_dir=tmp_path / "w4")
    assert skipped["checks"]["generation_consistency"]["pass"] is None


def test_vo_asr_from_transcript_and_timings(tmp_path: Path) -> None:
    media = _moving(tmp_path / "moving.mp4")
    good = run_final_qc(
        media, expected_duration_sec=4.0, work_dir=tmp_path / "w1",
        expected_vo_lines=["玉兰开了"], asr_text="玉兰开了，春天来了。",
    )
    assert good["checks"]["vo_asr"]["pass"] is True
    bad = run_final_qc(
        media, expected_duration_sec=4.0, work_dir=tmp_path / "w2",
        expected_vo_lines=["玉兰开了"], asr_text="完全不相干的旁白。",
    )
    assert bad["checks"]["vo_asr"]["pass"] is False
    assert bad["verdict"] == "fail"
    timed = run_final_qc(
        media, expected_duration_sec=4.0, work_dir=tmp_path / "w3",
        expected_vo_lines=["玉兰开了"],
        vo_word_timings=[{"text": "玉兰开了", "start_ms": 0, "end_ms": 900}],
    )
    assert timed["checks"]["vo_asr"]["pass"] is True
