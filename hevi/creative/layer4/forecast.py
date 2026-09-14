"""Non-canonical narrative forecast and branch comparison."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from hevi.obase.creative import (
    BranchBeat,
    BranchSnapshot,
    CreativeAuthority,
    IntentAlignment,
    NarrativeBranch,
    NarrativeCanon,
    NarrativeForecast,
    SelectedBranchPlan,
)


class StaleForecastError(ValueError):
    """Raised when a forecast no longer matches the canon revision."""


@dataclass(frozen=True)
class ForecastResult:
    forecast: NarrativeForecast
    branches: tuple[NarrativeBranch, ...]
    snapshots: tuple[BranchSnapshot, ...]


class ForecastEngine:
    """Simulate bounded alternatives without mutating canonical narrative state."""

    def create(
        self,
        *,
        project_id: UUID,
        canon: NarrativeCanon,
        alternatives: tuple[tuple[BranchBeat, ...], ...],
    ) -> ForecastResult:
        if not 2 <= len(alternatives) <= 5:
            raise ValueError("forecast requires between 2 and 5 alternatives")
        branches: list[NarrativeBranch] = []
        snapshots: list[BranchSnapshot] = []
        for index, beats in enumerate(alternatives, start=1):
            branch = NarrativeBranch(
                project_id=project_id,
                name=f"branch-{index}",
                base_canon_revision=canon.revision,
                beat_ids=tuple(beat.beat_id for beat in beats),
                projected_character_changes=tuple(beat.change for beat in beats),
                projected_world_changes=(),
                risks=(),
                intent_alignment=1.0 if beats else 0.0,
                authority=CreativeAuthority.PROPOSAL,
            )
            snapshot = BranchSnapshot(
                project_id=project_id,
                branch_id=branch.object_id,
                base_canon_revision=canon.revision,
                authority=CreativeAuthority.SNAPSHOT,
            )
            branches.append(branch)
            snapshots.append(snapshot)
        forecast = NarrativeForecast(
            project_id=project_id,
            canon_revision=canon.revision,
            branch_ids=tuple(branch.object_id for branch in branches),
            authority=CreativeAuthority.PROJECTION,
            refreshed_at=datetime.now(UTC),
        )
        return ForecastResult(forecast, tuple(branches), tuple(snapshots))

    def compare(self, left: NarrativeBranch, right: NarrativeBranch) -> IntentAlignment:
        if left.base_canon_revision != right.base_canon_revision:
            raise StaleForecastError("branches were generated from different canon revisions")
        left_ids = set(left.beat_ids)
        right_ids = set(right.beat_ids)
        union = left_ids | right_ids
        score = 1.0 if not union else len(left_ids & right_ids) / len(union)
        return IntentAlignment(score=score, reasons=("shared beat ratio",))

    def refresh(
        self,
        *,
        result: ForecastResult,
        canon: NarrativeCanon,
    ) -> ForecastResult:
        if result.forecast.canon_revision != canon.revision:
            raise StaleForecastError("FORECAST_STALE")
        return result

    def select(
        self,
        *,
        result: ForecastResult,
        branch_id: UUID,
        canon: NarrativeCanon,
    ) -> SelectedBranchPlan:
        if result.forecast.canon_revision != canon.revision:
            raise StaleForecastError("FORECAST_STALE")
        if branch_id not in result.forecast.branch_ids:
            raise ValueError("branch is not part of the forecast")
        return SelectedBranchPlan(
            project_id=canon.project_id,
            forecast_id=result.forecast.object_id,
            branch_id=branch_id,
            canon_revision=canon.revision,
            authority=CreativeAuthority.PROPOSAL,
        )


__all__ = ["ForecastEngine", "ForecastResult", "StaleForecastError"]
