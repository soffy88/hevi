from hevi.video_intelligence.comparison import compare_intent_to_artifact
from hevi.video_intelligence.models import (
    GateStatus,
    IntentProfile,
    ReelAnalysis,
    ShotObservation,
)
from hevi.video_intelligence.quality import evaluate_reel_quality


def test_shot_schema_roundtrip_and_machine_duration():
    shot = ShotObservation(
        shot_id="shot_0001", asset_id="video:one", start_ms=0, end_ms=1000, duration_ms=1000,
        boundary_evidence=[{"timestamp_ms": 0, "method": "test", "source": "AUTO_SCENE_DETECT"}],
        motion_evidence={
            "median_frame_delta": 0.01, "mean_frame_delta": 0.01, "p90_frame_delta": 0.02,
            "motion_class": "STATIC", "sample_count": 2,
        },
    )
    assert ShotObservation.model_validate_json(shot.model_dump_json()).duration_ms == 1000


def test_quality_fails_closed_on_gap():
    shots = [
        ShotObservation(
            shot_id="shot_0001", asset_id="video:one", start_ms=0, end_ms=1000, duration_ms=1000,
            boundary_evidence=[{"timestamp_ms": 0, "method": "test", "source": "AUTO_SCENE_DETECT"}],
            motion_evidence={
                "median_frame_delta": 0.01, "mean_frame_delta": 0.01, "p90_frame_delta": 0.02,
                "motion_class": "STATIC", "sample_count": 2,
            },
        ),
        ShotObservation(
            shot_id="shot_0002", asset_id="video:one", start_ms=1200, end_ms=2000, duration_ms=800,
            boundary_evidence=[{"timestamp_ms": 1200, "method": "test", "source": "AUTO_SCENE_DETECT"}],
            motion_evidence={
                "median_frame_delta": 0.01, "mean_frame_delta": 0.01, "p90_frame_delta": 0.02,
                "motion_class": "STATIC", "sample_count": 2,
            },
        ),
    ]
    report = evaluate_reel_quality(shots, 2000)
    assert report.status == GateStatus.FAIL
    assert any(item.code == "TIMELINE_CONTINUITY" for item in report.findings)


def test_not_evaluable_dimension_is_not_silently_passed():
    analysis = ReelAnalysis.model_validate({
        "analysis_id": "analysis:test", "video_asset": {
            "asset_id": "video:test", "uri": "x", "local_path": "x", "sha256": "a" * 64,
            "duration_s": 1, "width": 1, "height": 1,
        }, "video_probe": {"path": "x", "duration_ms": 1000}, "shots": [],
        "statistics": {"shot_count": 0, "average_shot_duration_ms": 0,
                        "median_shot_duration_ms": 0, "cuts_per_minute": 0},
        "quality_report": {"status": "PASS"},
        "provenance": {"source_asset_id": "video:test", "source_sha256": "a" * 64,
                        "probe_version": "x", "boundary_detector_version": "x",
                        "motion_analyzer_version": "x"},
    })
    comparison = compare_intent_to_artifact(
        IntentProfile(intent_id="i", visual_intents=["cinematic"]), analysis
    )
    assert comparison.status.value == "NOT_EVALUABLE"
    assert comparison.dimensions["VISUAL_INTENT"]["status"] == "NOT_EVALUABLE"
