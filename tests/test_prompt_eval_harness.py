"""Tests for qa.prompt_eval_harness: frozen samples + unmeasured stub."""

from __future__ import annotations

from pathlib import Path

from hevi.capabilities.prompt_eval_harness import (
    CONSISTENCY_MEASUREMENTS,
    SAMPLE_VERSION,
    build_frozen_samples,
    evaluate_sample,
    measure_generation_consistency,
    run_frozen_samples,
)
from hevi.capabilities.registry import get


def test_frozen_samples_all_match_expectation(tmp_path: Path) -> None:
    report = run_frozen_samples(tmp_path)
    assert report["sample_version"] == SAMPLE_VERSION
    assert report["verdict"] == "pass", report["samples"]
    assert report["matched"] == report["total"] == 9
    names = [s["name"] for s in report["samples"]]
    assert "good_beat_episode" in names
    assert "repeated_beats_fail" in names
    assert "chinese_dialogue_without_voice_fails" in names


def test_good_sample_measurements_are_real_numbers(tmp_path: Path) -> None:
    samples = build_frozen_samples(tmp_path)
    good = next(s for s in samples if s["name"] == "good_beat_episode")
    report = evaluate_sample(good)
    assert report["verdict"] == "pass"
    assert report["measurements"]["anchor_in_prompt"] is True
    assert report["measurements"]["frames_in_prompt"] is True
    assert report["measurements"]["clip_camera_state_constraints"] is True
    assert report["measurements"]["negative_coverage"] == 1.0


def test_bad_samples_fail_with_named_issues(tmp_path: Path) -> None:
    samples = build_frozen_samples(tmp_path)
    for name in ("no_anchor_fails", "no_provider_fails", "over_provider_cap_fails"):
        report = evaluate_sample(next(s for s in samples if s["name"] == name))
        assert report["verdict"] == "fail", name
        assert report["issues"], name


def test_generation_consistency_is_never_scored() -> None:
    result = measure_generation_consistency({})
    assert result["status"] == "planned_not_measured"
    assert len(result["measurements"]) == len(CONSISTENCY_MEASUREMENTS) == 4
    assert all(m["value"] is None for m in result["measurements"])


def test_harness_capability_registered() -> None:
    assert get("qa.prompt_eval_harness") is not None
