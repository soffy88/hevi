"""Read-only ShotPlan projections for observed-artifact comparison."""

from __future__ import annotations

from typing import Any

from hevi.cinematic.shot_intelligence.models import ShotPlan


def expected_shot_profile(plan: ShotPlan) -> dict[str, Any]:
    return {
        "shot_count": len(plan.shots),
        "shot_types": [shot.shot_type for shot in plan.shots],
        "durations": [shot.duration_range_s for shot in plan.shots],
        "schema_version": plan.shot_plan_schema_version,
    }
