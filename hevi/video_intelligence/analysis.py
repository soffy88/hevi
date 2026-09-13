"""Canonical deterministic reel analysis pipeline."""

from __future__ import annotations

import itertools
import statistics
import uuid
from pathlib import Path

from .boundaries import ShotBoundaryDetector
from .models import (
    ReelAnalysis,
    ReelStatistics,
    ShotBoundaryEvidence,
    ShotObservation,
    ShotSemantic,
    VideoAnalysisProvenance,
)
from .motion import MotionAnalyzer
from .probe import probe_video, video_asset
from .quality import evaluate_reel_quality
from .rhythm import rhythm_for_position


def analyze_reel(
    path: str | Path,
    *,
    threshold: float = 0.35,
    minimum_shot_duration_ms: int = 500,
    semantic: bool = False,
) -> ReelAnalysis:
    """Analyze a real local video using only machine evidence by default.

    ``semantic`` intentionally does not invent labels; semantic enrichment is
    a separate optional provider contract and is not enabled by this core.
    """
    asset = video_asset(path)
    probe = probe_video(path, asset_id=asset.asset_id)
    boundaries = ShotBoundaryDetector(threshold, minimum_shot_duration_ms).detect(str(path), probe)
    cut_points = [0, *[item.timestamp_ms for item in boundaries], probe.duration_ms]
    ranges = list(itertools.pairwise(cut_points))
    shots: list[ShotObservation] = []
    for index, (start, end) in enumerate(ranges, start=1):
        shot_motion = MotionAnalyzer(sample_count=8).analyze(str(path), probe)
        shot_id = f"shot_{index:04d}"
        shots.append(ShotObservation(
            shot_id=shot_id,
            asset_id=asset.asset_id,
            start_ms=start,
            end_ms=end,
            duration_ms=end - start,
            boundary_evidence=[
                item for item in boundaries if start <= item.timestamp_ms <= end
            ] or [ShotBoundaryEvidence(
                timestamp_ms=start,
                method="PIPELINE_BOUNDARY",
                source="AUTO_SCENE_DETECT",
            )],
            motion_evidence=shot_motion,
            semantic=ShotSemantic(
                description=f"Observed shot {shot_id}; semantic provider={'requested' if semantic else 'not_requested'}",
            ),
            rhythm=rhythm_for_position(index - 1, len(ranges), end - start),
        ))
    durations = [shot.duration_ms for shot in shots]
    stats = ReelStatistics(
        shot_count=len(shots),
        average_shot_duration_ms=statistics.fmean(durations),
        median_shot_duration_ms=statistics.median(durations),
        cuts_per_minute=(len(shots) - 1) / (probe.duration_ms / 60000),
        shot_size_distribution={"UNKNOWN": len(shots)},
        category_distribution={"OTHER": len(shots)},
        camera_motion_distribution={"UNKNOWN": len(shots)},
        rhythm_distribution=(
            {
            role: sum(1 for shot in shots if shot.rhythm and shot.rhythm.role.value == role)
            for role in {shot.rhythm.role.value for shot in shots if shot.rhythm}
            }
            if any(shot.rhythm for shot in shots)
            else {}
        ),
        motion_distribution={
            state: sum(1 for shot in shots if shot.motion_evidence and shot.motion_evidence.motion_class.value == state)
            for state in {shot.motion_evidence.motion_class.value for shot in shots if shot.motion_evidence}
        },
    )
    quality = evaluate_reel_quality(shots, probe.duration_ms)
    return ReelAnalysis(
        analysis_id=f"analysis:{uuid.uuid4().hex}",
        video_asset=asset,
        video_probe=probe,
        shots=shots,
        statistics=stats,
        quality_report=quality,
        provenance=VideoAnalysisProvenance(
            source_asset_id=asset.asset_id,
            source_sha256=asset.sha256,
            probe_version="ffprobe-v1",
            boundary_detector_version="ffmpeg-scene-v1",
            motion_analyzer_version=MotionAnalyzer.version,
            evidence_refs=["ffprobe", "ffmpeg-scene", "ffmpeg-graydelta"],
        ),
    )


def save_analysis(analysis: ReelAnalysis, output_dir: str | Path) -> None:
    import json

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    payload = analysis.model_dump(mode="json")
    (destination / "analysis.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (destination / "shots.json").write_text(json.dumps(payload["shots"], ensure_ascii=False, indent=2), encoding="utf-8")
    (destination / "quality.json").write_text(json.dumps(payload["quality_report"], ensure_ascii=False, indent=2), encoding="utf-8")
    (destination / "provenance.json").write_text(json.dumps(payload["provenance"], ensure_ascii=False, indent=2), encoding="utf-8")
