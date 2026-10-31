"""Tests for qa.prompt_eval_harness: frozen samples + unmeasured stub."""

from __future__ import annotations

from pathlib import Path

from hevi.capabilities.prompt_eval_harness import (
    CONSISTENCY_MEASUREMENTS,
    SAMPLE_VERSION,
    build_frozen_samples,
    build_generation_consistency_fixture,
    evaluate_sample,
    measure_generation_consistency,
    run_frozen_samples,
)
from hevi.capabilities.registry import get


def test_frozen_samples_all_match_expectation(tmp_path: Path) -> None:
    report = run_frozen_samples(tmp_path)
    assert report["sample_version"] == SAMPLE_VERSION
    assert report["verdict"] == "pass", report["samples"]
    assert report["matched"] == report["total"] == 10
    names = [s["name"] for s in report["samples"]]
    assert "good_beat_episode" in names
    assert "repeated_beats_fail" in names
    assert "chinese_dialogue_without_voice_fails" in names
    assert "scene_reference_without_duration_fails" in names


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
    assert result["verdict"] == "planned_not_measured"
    assert len(result["measurements"]) == len(CONSISTENCY_MEASUREMENTS) == 4
    assert all(m["value"] is None for m in result["measurements"])


def test_scene_sample_execution_fields_are_written(tmp_path: Path) -> None:
    samples = build_frozen_samples(tmp_path)
    report = evaluate_sample(next(s for s in samples if s["name"] == "good_scene_reference"))
    assert report["verdict"] == "pass"
    assert report["measurements"]["frames"] == 243
    assert report["measurements"]["execution_in_text"] is True


def test_generation_consistency_fixed_sample_is_measured() -> None:
    result = measure_generation_consistency(build_generation_consistency_fixture())
    assert result["status"] == "measured"
    assert result["verdict"] == "pass"
    assert result["measured_count"] == 4
    by_name = {m["name"]: m for m in result["measurements"]}
    assert by_name["dialogue_asr"]["value"] == 1.0
    assert by_name["character_consistency"]["value"] >= 0.8
    assert by_name["motion_frame_diff"]["value"] == 1.0
    assert by_name["ban_violation"]["value"] == 0.0
    assert all(m["verdict"] == "pass" for m in result["measurements"])


def test_generation_consistency_partial_evidence_is_not_scored() -> None:
    result = measure_generation_consistency({
        "prompt": {"expected_lines": ["玉兰开了"]},
        "asr_text": "玉兰开了，春天来了。",
    })
    assert result["status"] == "partially_measured"
    by_name = {m["name"]: m for m in result["measurements"]}
    assert by_name["dialogue_asr"]["status"] == "measured"
    assert by_name["character_consistency"]["status"] == "planned_not_measured"
    assert by_name["character_consistency"]["value"] is None
    assert by_name["motion_frame_diff"]["value"] is None
    assert by_name["ban_violation"]["value"] is None


def test_generation_consistency_mismatch_fails_with_named_measurements() -> None:
    artifacts = build_generation_consistency_fixture()
    artifacts["asr_text"] = "完全不相干的旁白，与台词无关。"
    artifacts["frames"] = [
        {**frame, "anchor_agreement": 0.2, "banned": ["watermark"]}
        for frame in artifacts["frames"]
    ]
    result = measure_generation_consistency(artifacts)
    assert result["status"] == "measured"
    assert result["verdict"] == "fail"
    by_name = {m["name"]: m for m in result["measurements"]}
    assert by_name["dialogue_asr"]["verdict"] == "fail"
    assert by_name["character_consistency"]["verdict"] == "fail"
    assert by_name["ban_violation"]["verdict"] == "fail"
    assert by_name["ban_violation"]["violating_frames"] == [0, 1, 2, 3]


def test_generation_consistency_timings_only_measure_dialogue() -> None:
    artifacts = build_generation_consistency_fixture()
    artifacts.pop("asr_text")
    result = measure_generation_consistency(artifacts)
    by_name = {m["name"]: m for m in result["measurements"]}
    assert by_name["dialogue_asr"]["status"] == "measured"
    assert by_name["dialogue_asr"]["value"] == 1.0


def test_harness_capability_registered() -> None:
    assert get("qa.prompt_eval_harness") is not None
