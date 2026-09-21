"""Closure gates for the canonical subtitle timeline path."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from hevi.assembly.subtitle_timeline_atoms import (
    CueMs,
    align_cues,
    cues_to_ass,
    cues_to_srt,
    validate_ass,
    validate_srt,
)
from hevi.production.subtitle_timeline_workflow import execute_subtitle_timeline_task


def test_timestamp_srt_ass_are_deterministic() -> None:
    cues = align_cues(
        [{"start": 0.0, "end": 1.2, "text": "中文"}, {"start": 1.2, "end": 2.0, "text": "第二句"}],
        audio_duration_ms=2000,
        fps=25,
        unit="s",
    )
    assert cues == [CueMs(0, 1200, "中文"), CueMs(1200, 2000, "第二句")]
    srt = cues_to_srt(cues)
    ass = cues_to_ass(
        cues, width=320, height=240, font_size=20, margin_l=10, margin_r=10, margin_v=10
    )
    assert validate_srt(srt, audio_duration_ms=2000) == cues
    assert validate_ass(ass, audio_duration_ms=2000) == cues


@pytest.mark.asyncio
async def test_real_subtitle_timeline_e2e(tmp_path: Path) -> None:
    for name, color in (("a", "red"), ("b", "blue")):
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                f"color=c={color}:s=320x240:d=1.5",
                "-an",
                "-pix_fmt",
                "yuv420p",
                str(tmp_path / f"{name}.mp4"),
            ],
            check=True,
        )
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=2.8",
            "-c:a",
            "pcm_s16le",
            str(tmp_path / "audio.wav"),
        ],
        check=True,
    )
    result = await execute_subtitle_timeline_task(
        {
            "id": "subtitle-timeline-test",
            "config_json": {
                "source_video_paths": [str(tmp_path / "a.mp4"), str(tmp_path / "b.mp4")],
                "source_audio_path": str(tmp_path / "audio.wav"),
                "output_path": str(tmp_path / "final.mp4"),
                "output_dir": str(tmp_path),
                "asr_cues": [
                    {"start_ms": 0, "end_ms": 1400, "text": "第一段"},
                    {"start_ms": 1400, "end_ms": 2700, "text": "第二段"},
                ],
                "width": 320,
                "height": 240,
                "fps": 24,
            },
        },
        None,
    )
    assert result["status"] == "completed"
    assert Path(result["result_video_path"]).stat().st_size > 0
    report = result["config_json"]["timeline_report"]
    assert report["subtitle_render_real_smoke"] == "PASS"
    assert report["timeline_output_validation"] == "PASS"
    assert report["clock_drift_ms"] <= 100
