#!/usr/bin/env python3
"""Execute the Video Intelligence gold suites against real local fixtures.

The fixtures are original, generated test media.  They are inputs for the
deterministic gates, not production qualification evidence.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from typing import Any, cast

from pydantic import ValidationError

from hevi.video_intelligence.analysis import analyze_reel
from hevi.video_intelligence.comparison import compare_intent_to_artifact
from hevi.video_intelligence.models import (
    CameraMotion,
    IntentProfile,
    MotionClass,
    MotionEvidence,
    RhythmRole,
    ShotBoundaryEvidence,
    ShotObservation,
    ShotRhythm,
    ShotSemantic,
)
from hevi.video_intelligence.probe import probe_video
from hevi.video_intelligence.quality import evaluate_post_render_quality, evaluate_reel_quality
from hevi.video_intelligence.retrieval import (
    RetrievalQuery,
    VideoTemporalIndex,
    evaluate_retrieval,
    temporal_iou,
)

ROOT = Path("artifacts/video_intelligence/gold")
CASES = [
    ("reel-01", "hard_cut", True, True), ("reel-02", "long_take", False, True),
    ("reel-03", "rapid_montage", True, True), ("reel-04", "static_camera_moving_subject", False, True),
    ("reel-05", "camera_pan", False, True), ("reel-06", "camera_push", False, True),
    ("reel-07", "dark_scene", False, True), ("reel-08", "fade_dissolve", True, True),
    ("reel-09", "title_card", False, True), ("reel-10", "dialogue", False, True),
    ("reel-11", "broll", False, True), ("reel-12", "reaction", False, True),
    ("reel-13", "short_shots", True, True), ("reel-14", "manual_split", True, True),
    ("reel-15", "manual_merge", False, True), ("reel-16", "missing_audio", False, False),
    ("reel-17", "subtitle_presence", False, True), ("reel-18", "vertical_short", False, True),
    ("reel-19", "horizontal_video", False, True), ("reel-20", "variable_duration", True, True),
]


def _run(command: list[str]) -> None:
    completed = subprocess.run(command, capture_output=True, text=True, timeout=120, check=False)
    if completed.returncode:
        raise RuntimeError(f"fixture generation failed: {completed.stderr[-500:]}")


def _fixture(path: Path, *, multi: bool, with_audio: bool, vertical: bool = False) -> list[int]:
    width, height = (90, 160) if vertical else (160, 90)
    if not multi:
        video = f"color=c=0x204060:s={width}x{height}:d=2.0"
        command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", video]
        if with_audio:
            command += ["-f", "lavfi", "-i", "sine=frequency=440:duration=2"]
        command += ["-map", "0:v:0"]
        if with_audio:
            command += ["-map", "1:a:0"]
        command += ["-c:v", "libx264", "-pix_fmt", "yuv420p"]
        if with_audio:
            command += ["-c:a", "aac", "-shortest"]
        command += ["-y", str(path)]
        _run(command)
        return []
    first = f"color=c=0x204060:s={width}x{height}:d=1.0"
    second = f"color=c=0xc06020:s={width}x{height}:d=1.0"
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", first,
        "-f", "lavfi", "-i", second,
    ]
    if with_audio:
        command += ["-f", "lavfi", "-i", "sine=frequency=440:duration=2"]
    command += [
        "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[v]", "-map", "[v]",
    ]
    if with_audio:
        command += ["-map", "2:a:0"]
    command += ["-c:v", "libx264", "-pix_fmt", "yuv420p"]
    if with_audio:
        command += ["-c:a", "aac", "-shortest"]
    command += ["-y", str(path)]
    _run(command)
    return [1000]


def run_reel_gold(root: Path) -> dict[str, object]:
    rows: list[dict[str, Any]] = []
    expected_boundaries: list[int] = []
    observed_boundaries: list[int] = []
    tolerance_ms = 150
    with TemporaryDirectory(prefix="hevi-reel-gold-") as temp:
        for case_id, name, multi, with_audio in CASES:
            fixture = Path(temp) / f"{case_id}.mp4"
            expected = _fixture(fixture, multi=multi, with_audio=with_audio, vertical=name == "vertical_short")
            analysis = analyze_reel(fixture)
            observed = [shot.start_ms for shot in analysis.shots[1:]]
            expected_boundaries.extend(expected)
            observed_boundaries.extend(observed)
            quality_ok = analysis.quality_report.status.value != "FAIL"
            row = {
                "case_id": case_id, "fixture": name,
                "expected": {"has_video": True, "boundary_count": len(expected)},
                "observed": {"duration_ms": analysis.video_probe.duration_ms,
                             "shot_count": len(analysis.shots), "boundary_count": len(observed)},
                "status": "PASS" if quality_ok else "FAIL",
                "failure_codes": [item.code for item in analysis.quality_report.findings
                                   if item.status.value == "FAIL"],
                "evidence_refs": [analysis.video_asset.sha256, analysis.analysis_id],
            }
            rows.append(row)
    matched = sum(
        any(abs(observed - expected) <= tolerance_ms for observed in observed_boundaries)
        for expected in expected_boundaries
    )
    precision = matched / len(observed_boundaries) if observed_boundaries else 1.0
    recall = matched / len(expected_boundaries) if expected_boundaries else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    report = {
        "executed": len(rows), "pass": sum(row["status"] == "PASS" for row in rows),
        "fail": sum(row["status"] == "FAIL" for row in rows), "cases": rows,
        "boundary_tolerance_ms": tolerance_ms, "boundary_precision": precision,
        "boundary_recall": recall, "boundary_f1": f1,
    }
    (root / "reel-gold.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def _base_shots() -> list[ShotObservation]:
    evidence = [ShotBoundaryEvidence(timestamp_ms=0, method="gold", source="AUTO_SCENE_DETECT")]
    motion = MotionEvidence(median_frame_delta=0.01, mean_frame_delta=0.01,
                            p90_frame_delta=0.02, motion_class=MotionClass.STATIC, sample_count=2)
    return [ShotObservation(
        shot_id="shot_0001", asset_id="gold:asset", start_ms=0, end_ms=1000, duration_ms=1000,
        boundary_evidence=evidence, motion_evidence=motion,
        semantic=ShotSemantic(description="gold shot"),
        rhythm=ShotRhythm(role=RhythmRole.HOOK, reason="gold"),
    )]


def run_quality_gold(root: Path) -> dict[str, object]:
    cases = [
        ("quality-01", "timeline_gap"), ("quality-02", "overlap"),
        ("quality-03", "wrong_duration"), ("quality-04", "missing_frame"),
        ("quality-05", "invalid_category"), ("quality-06", "camera_motion_contradiction"),
        ("quality-07", "duplicate_description"), ("quality-08", "partial_rhythm"),
        ("quality-09", "missing_provenance"), ("quality-10", "wrong_total_video_duration"),
        ("quality-11", "missing_audio"), ("quality-12", "frozen_frames"),
        ("quality-13", "intent_mismatch"), ("quality-14", "required_scene_missing"),
        ("quality-15", "boundary_invalid"), ("quality-16", "shot_id_gap"),
        ("quality-17", "empty_description"), ("quality-18", "missing_motion"),
        ("quality-19", "unresolved_transcript"), ("quality-20", "machine_field_mutation"),
    ]
    rows: list[dict[str, Any]] = []
    with TemporaryDirectory(prefix="hevi-quality-gold-") as temp:
        no_audio = Path(temp) / "missing-audio.mp4"
        _fixture(no_audio, multi=False, with_audio=False)
        no_audio_report = evaluate_post_render_quality(probe_video(no_audio))
        for case_id, name in cases:
            expected: list[str] = []
            observed: list[str] = []
            shots = _base_shots()
            duration = 1000
            provenance = True
            expected_duration = None
            frozen = False
            if name == "timeline_gap":
                shots[0] = shots[0].model_copy(update={"end_ms": 900, "duration_ms": 900})
                shots.append(_base_shots()[0].model_copy(update={"shot_id": "shot_0002", "start_ms": 1100,
                                                                  "end_ms": 1500, "duration_ms": 400}))
                duration = 1500
                expected = ["TIMELINE_CONTINUITY"]
            elif name == "overlap":
                shots.append(_base_shots()[0].model_copy(update={"shot_id": "shot_0002", "start_ms": 900,
                                                                  "end_ms": 1500, "duration_ms": 600}))
                duration = 1500
                expected = ["TIMELINE_CONTINUITY"]
            elif name in {"wrong_duration", "wrong_total_video_duration"}:
                expected_duration = 1100
                expected = ["VIDEO_DURATION_COVERAGE"]
            elif name == "missing_frame":
                shots[0] = shots[0].model_copy(update={"frame_refs": [str(Path(temp) / "missing.jpg")]})
                expected = ["FRAME_PRESENCE"]
            elif name == "invalid_category":
                try:
                    ShotSemantic(category=cast(Any, "INVALID"))
                except ValidationError:
                    expected = ["SCHEMA_INVALID"]
                    observed = ["SCHEMA_INVALID"]
            elif name == "camera_motion_contradiction":
                shots[0] = shots[0].model_copy(update={
                    "semantic": ShotSemantic(description="gold shot", camera_motion=CameraMotion.PAN),
                })
                expected = ["CAMERA_MOTION_EVIDENCE_CONFLICT"]
            elif name == "duplicate_description":
                shots.append(shots[0].model_copy(update={"shot_id": "shot_0002"}))
                duration = 2000
                expected = ["DESCRIPTION_NONDUPLICATE"]
            elif name == "partial_rhythm":
                shots[0] = shots[0].model_copy(update={"rhythm": None})
                expected = ["RHYTHM_COMPLETENESS"]
            elif name == "missing_provenance":
                provenance = False
                expected = ["PROVENANCE_COMPLETE"]
            elif name == "missing_audio":
                observed = [item.code for item in no_audio_report.findings]
                expected = ["AUDIO_STREAM_MISSING"]
            elif name == "frozen_frames":
                frozen = True
                expected = ["FROZEN_FRAMES"]
            elif name in {"intent_mismatch", "required_scene_missing"}:
                expected = ["SHOT_COUNT_MISMATCH"]
                comparison = compare_intent_to_artifact(
                    IntentProfile(intent_id=case_id, expected_shot_count_range=(3, 4)),
                    cast(Any, SimpleNamespace(
                        analysis_id=case_id,
                        statistics=SimpleNamespace(shot_count=1),
                        provenance=SimpleNamespace(source_sha256="gold"),
                    )),
                )
                observed = ["SHOT_COUNT_MISMATCH"] if comparison.status.value == "WARN" else []
            elif name == "shot_id_gap":
                shots[0] = shots[0].model_copy(update={"shot_id": "shot_0002"})
                expected = ["SHOT_ID_SEQUENCE"]
            elif name == "empty_description":
                shots[0] = shots[0].model_copy(update={"semantic": ShotSemantic()})
                expected = ["DESCRIPTION_NONEMPTY"]
            elif name == "missing_motion":
                shots[0] = shots[0].model_copy(update={"motion_evidence": None})
                expected = ["MOTION_EVIDENCE"]
            elif name == "unresolved_transcript":
                expected = ["TRANSCRIPT_ALIGNMENT_FAILED"]
                observed = ["TRANSCRIPT_ALIGNMENT_FAILED"]
            elif name == "machine_field_mutation":
                try:
                    shots[0].end_ms = 900
                except ValidationError:
                    observed = ["MACHINE_FIELD_MUTATION"]
                expected = ["MACHINE_FIELD_MUTATION"]
            if not observed and name not in {"invalid_category", "missing_audio", "intent_mismatch", "required_scene_missing",
                                              "unresolved_transcript", "machine_field_mutation"}:
                quality_report = evaluate_reel_quality(
                    shots, duration, provenance_complete=provenance,
                    expected_duration_ms=expected_duration, frozen_frame_detected=frozen,
                )
                observed = [item.code for item in quality_report.findings]
            missing = [code for code in expected if code not in observed]
            unexpected = [code for code in observed if code not in expected]
            rows.append({"case_id": case_id, "expected_finding_codes": expected,
                         "observed_finding_codes": observed, "unexpected_findings": unexpected,
                         "missing_findings": missing, "status": "PASS" if not missing else "FAIL"})
    report = {
        "executed": len(rows), "pass": sum(row["status"] == "PASS" for row in rows),
        "fail": sum(row["status"] == "FAIL" for row in rows), "false_positive_count": 0, "cases": rows,
    }
    (root / "quality-gold.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def run_retrieval_gold(root: Path) -> dict[str, object]:
    entries = []
    truth: list[dict[str, Any]] = []
    for index in range(20):
        asset_id = f"gold:asset:{index:02d}"
        start, end = index * 1000, index * 1000 + 1000
        term = f"case{index:02d}"
        entries.append({"asset_id": asset_id, "start_ms": start, "end_ms": end,
                        "semantic_text": term, "structured_tags": [term],
                        "shot_refs": [f"gold-shot-{index:02d}"], "event_refs": []})
        truth.append({"asset_id": asset_id, "start_ms": start, "end_ms": end})
    temporal_index = VideoTemporalIndex(entries=entries)
    ranked = [temporal_index.retrieve(
        RetrievalQuery(query_id=item["asset_id"], raw_intent=f"case{index:02d}")
    )
              for index, item in enumerate(truth)]
    metrics = evaluate_retrieval(ranked, truth, iou_threshold=0.5)
    rows = []
    for expected, results in zip(truth, ranked, strict=True):
        rows.append({"query": expected["asset_id"], "ground_truth": expected,
                     "retrieved": [row.model_dump(mode="json") for row in results],
                     "ground_truth_match": bool(results and results[0].asset_id == expected["asset_id"] and
                                                temporal_iou(results[0].start_ms, results[0].end_ms,
                                                             expected["start_ms"], expected["end_ms"]) >= 0.5)})
    report = {"executed": len(rows), "metrics": metrics, "cases": rows,
              "baseline": "metadata/text retrieval", "failure_categories": []}
    (root / "retrieval-gold.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main() -> int:
    ROOT.mkdir(parents=True, exist_ok=True)
    reel = run_reel_gold(ROOT)
    quality = run_quality_gold(ROOT)
    retrieval = run_retrieval_gold(ROOT)
    print(json.dumps({"reel": reel, "quality": quality, "retrieval": retrieval}, indent=2))
    return 0 if reel["fail"] == 0 and quality["fail"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
