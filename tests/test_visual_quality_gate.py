from __future__ import annotations

import subprocess
from pathlib import Path

from hevi.production.adapters import default_production_adapters
from hevi.production.visual_quality_workflow import execute_visual_quality_task
from hevi.quality.visual_quality import analyze_video, evaluate_visual_quality


def _video(path: Path, source: str, *, duration: float = 2.0, filtergraph: str | None = None) -> None:
    separator = ":" if source.startswith("color=") else "="
    command = ["ffmpeg", "-y", "-f", "lavfi", "-i", f"{source}{separator}duration={duration}:size=160x90:rate=10"]
    if filtergraph:
        command += ["-vf", filtergraph]
    command += ["-pix_fmt", "yuv420p", "-c:v", "libx264", str(path)]
    subprocess.run(command, check=True, capture_output=True)


def test_measurement_contract_uses_real_frames_and_normal_video_passes(tmp_path: Path) -> None:
    path = tmp_path / "normal.mp4"
    _video(path, "testsrc2")
    measured = analyze_video(path, max_frames=10)
    assert measured.analysis_frames == 10
    assert measured.frame_count > 0
    assert measured.black_frame_ratio == 0
    assert measured.freeze_frame_ratio < 0.9
    assert measured.camera_motion_score > 0.006
    assert evaluate_visual_quality(measured).status in {"PASS", "WARN"}


def test_black_and_freeze_segments_are_detected(tmp_path: Path) -> None:
    black = tmp_path / "black.mp4"
    _video(black, "color=c=black")
    black_measurement = analyze_video(black, max_frames=10)
    assert black_measurement.black_frame_ratio == 1
    assert evaluate_visual_quality(black_measurement).status == "BLOCK"

    freeze = tmp_path / "freeze.mp4"
    _video(freeze, "testsrc2", duration=1.0, filtergraph="tpad=stop_mode=clone:stop_duration=1")
    freeze_measurement = analyze_video(freeze, max_frames=10)
    assert freeze_measurement.freeze_frame_ratio > 0
    assert freeze_measurement.details["freeze_frame_count"] > 0


def test_luma_shot_budget_and_clock_evidence(tmp_path: Path) -> None:
    dark = tmp_path / "dark.mp4"
    _video(dark, "color=c=black", filtergraph="eq=brightness=0.1")
    measured = analyze_video(dark, max_frames=6, audio_duration_ms=1800, shot_boundaries_ms=[500, 1200])
    assert measured.low_luma_ratio >= 0
    assert measured.shot_count == 3
    assert measured.expected_frame_count == round(1.8 * measured.fps)
    assert measured.clock_drift_ms is not None


def test_visual_quality_is_a_single_production_adapter_and_blocks_without_promotion(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "bad.mp4"
    _video(path, "color=c=black")
    incident_db = tmp_path / "incidents.db"
    monkeypatch.setenv("HEVI_INCIDENT_DB", str(incident_db))
    result = __import__("asyncio").run(
        execute_visual_quality_task(
            {"id": "vq-task", "config_json": {"production_id": "vq", "source_video_path": str(path)}}, None
        )
    )
    assert result["status"] == "failed"
    assert result["report"]["repair_incident_id"]
    assert "visual_quality" in default_production_adapters().sources()
