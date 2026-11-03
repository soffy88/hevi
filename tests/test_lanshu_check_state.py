"""Offline tests for the lanshu-explainer evidence-gated state machine.

The ffprobe probe is stubbed; no media tools are needed to run these.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

SKILL_DIR = Path(__file__).resolve().parent.parent / "hevi" / "skills" / "lanshu-explainer"

spec = importlib.util.spec_from_file_location(
    "lanshu_check_state", SKILL_DIR / "tools" / "check_state.py"
)
check_state = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_state)


def fake_probe_factory(video: bool = True, audio: bool = True):
    kinds = set()
    if video:
        kinds.add("video")
    if audio:
        kinds.add("audio")

    def probe(path: Path) -> set[str]:
        assert Path(path).is_file()
        return set(kinds)

    return probe


def _make_job(tmp_path: Path) -> tuple[dict, Path]:
    job_dir = tmp_path / "job"
    (job_dir / "qa" / "reports").mkdir(parents=True)
    (job_dir / "docs").mkdir(parents=True)
    (job_dir / "assets" / "audio" / "final").mkdir(parents=True)
    (job_dir / "assets" / "video" / "selected").mkdir(parents=True)
    (job_dir / "film").mkdir(parents=True)
    (job_dir / "qa" / "reports" / "preflight.json").write_text(
        json.dumps({"ok": True}), encoding="utf-8")
    (job_dir / "docs" / "SCRIPT.md").write_text("script", encoding="utf-8")
    (job_dir / "docs" / "BEAT_SHEET.md").write_text("beats", encoding="utf-8")
    (job_dir / "assets" / "audio" / "final" / "narration.wav").write_bytes(b"\x00" * 64)
    (job_dir / "qa" / "reports" / "asr.json").write_text("{}", encoding="utf-8")
    (job_dir / "assets" / "audio" / "final" / "story.json").write_text(
        json.dumps({"draft": False, "lines": []}), encoding="utf-8")
    (job_dir / "docs" / "TIMELINE.md").write_text("timeline", encoding="utf-8")
    (job_dir / "docs" / "STORYBOARD.md").write_text("storyboard", encoding="utf-8")
    (job_dir / "film" / "index.html").write_text("<html></html>", encoding="utf-8")
    (job_dir / "qa" / "reports" / "visual.json").write_text("{}", encoding="utf-8")
    (job_dir / "qa" / "reports" / "composition.json").write_text("{}", encoding="utf-8")
    for name in ("rendered", "master", "share"):
        (job_dir / "assets" / "video" / "selected" / f"{name}.mp4").write_bytes(b"\x00" * 64)
    (job_dir / "qa" / "reports" / "delivery.json").write_text(
        json.dumps({"status": "verified", "loudness_passed": True}), encoding="utf-8")

    job = {
        "state": "intake",
        "creative": {"route": "styled"},
        "plan": {"status": "approved"},
        "artifacts": {
            "script": "docs/SCRIPT.md",
            "beat_sheet": "docs/BEAT_SHEET.md",
            "final_audio": "assets/audio/final/narration.wav",
            "story": "assets/audio/final/story.json",
            "timeline": "docs/TIMELINE.md",
            "storyboard": "docs/STORYBOARD.md",
            "film_project": "film",
            "rendered": "assets/video/selected/rendered.mp4",
            "master": "assets/video/selected/master.mp4",
            "share": "assets/video/selected/share.mp4",
        },
        "qa": {
            "asr_report": "qa/reports/asr.json",
            "manual_visual_review": "qa/reports/visual.json",
            "composition_report": "qa/reports/composition.json",
            "delivery_report": "qa/reports/delivery.json",
        },
    }
    return job, job_dir


def test_full_evidence_reaches_verified(tmp_path):
    job, job_dir = _make_job(tmp_path)
    result = check_state.compute_state(job, job_dir, probe=fake_probe_factory())
    assert result["evidenced_state"] == "verified"
    assert result["consistent"] is True  # recorded intake <= evidenced verified
    assert result["next_state"] is None


def test_missing_master_moves_state_back(tmp_path):
    job, job_dir = _make_job(tmp_path)
    (job_dir / "assets" / "video" / "selected" / "master.mp4").unlink()
    result = check_state.compute_state(job, job_dir, probe=fake_probe_factory())
    assert result["evidenced_state"] == "rendered"
    assert result["next_state"] == "verified"
    assert result["missing_for_next"], "must name what verified is missing"


def test_recorded_state_beyond_evidence_is_inconsistent(tmp_path):
    job, job_dir = _make_job(tmp_path)
    job["state"] = "verified"
    (job_dir / "assets" / "video" / "selected" / "master.mp4").unlink()
    result = check_state.compute_state(job, job_dir, probe=fake_probe_factory())
    assert result["consistent"] is False


def test_draft_story_blocks_audio_locked(tmp_path):
    job, job_dir = _make_job(tmp_path)
    (job_dir / "assets" / "audio" / "final" / "story.json").write_text(
        json.dumps({"draft": True}), encoding="utf-8")
    result = check_state.compute_state(job, job_dir, probe=fake_probe_factory())
    assert result["evidenced_state"] == "content_locked"
    assert any("draft" in m for m in result["missing_for_next"])


def test_undecodable_media_blocks(tmp_path):
    job, job_dir = _make_job(tmp_path)
    result = check_state.compute_state(
        job, job_dir, probe=fake_probe_factory(video=True, audio=False))
    assert result["evidenced_state"] == "content_locked"
    assert any("audio" in m for m in result["missing_for_next"])


def test_states_order_is_fixed():
    assert check_state.STATES[0] == "intake"
    assert check_state.STATES[-1] == "verified"
    assert len(check_state.STATES) == 8
