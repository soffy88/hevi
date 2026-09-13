"""Reference-video abstraction without copying source content."""

from __future__ import annotations

import statistics
import uuid

from .models import ReelAnalysis, ReferenceProfile


def build_reference_profile(analysis: ReelAnalysis) -> ReferenceProfile:
    durations = [shot.duration_ms for shot in analysis.shots]
    total = max(1, len(analysis.shots))
    return ReferenceProfile(
        profile_id=f"reference:{uuid.uuid4().hex}",
        source_analysis_id=analysis.analysis_id,
        shot_duration_profile={
            "mean_ms": statistics.fmean(durations),
            "median_ms": statistics.median(durations),
            "p90_ms": sorted(durations)[min(len(durations) - 1, round(len(durations) * 0.9) - 1)],
        },
        cut_frequency=analysis.statistics.cuts_per_minute,
        shot_size_profile={key: value / total for key, value in analysis.statistics.shot_size_distribution.items()},
        camera_profile={key: value / total for key, value in analysis.statistics.camera_motion_distribution.items()},
        rhythm_profile={key: value / total for key, value in analysis.statistics.rhythm_distribution.items()},
        motion_profile={key: value / total for key, value in analysis.statistics.motion_distribution.items()},
        semantic_sequence=[shot.semantic.category.value for shot in analysis.shots],
        visual_pattern_summary="Abstract structural profile only; no source dialogue or source frames copied.",
        provenance_ref=analysis.provenance.source_sha256,
    )


def reference_to_shot_constraints(profile: ReferenceProfile) -> dict[str, object]:
    return {
        "target_asl_ms": profile.shot_duration_profile["mean_ms"],
        "cut_frequency": profile.cut_frequency,
        "shot_size_distribution": profile.shot_size_profile,
        "camera_tendencies": profile.camera_profile,
        "rhythm_distribution": profile.rhythm_profile,
        "motion_distribution": profile.motion_profile,
    }
