"""Long-form narrative stages and observation settlement."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from hevi.obase.creative import (
    ContinuityFact,
    CreativeAuthority,
    NarrativeCanon,
    NarrativeDelta,
    NarrativeObservation,
    ObservationFact,
    ProductionRun,
    StageResult,
)


class NarrativeStage(StrEnum):
    RESEARCH = "RESEARCH"
    ARCHITECT = "ARCHITECT"
    PLAN = "PLAN"
    COMPOSE = "COMPOSE"
    DRAFT = "DRAFT"
    OBSERVE = "OBSERVE"
    REFLECT = "REFLECT"
    NORMALIZE = "NORMALIZE"
    AUDIT = "AUDIT"
    REVISE = "REVISE"
    RE_AUDIT = "RE_AUDIT"
    SETTLEMENT = "SETTLEMENT"
    STATE_COMMIT = "STATE_COMMIT"


LONGFORM_STAGES: tuple[NarrativeStage, ...] = tuple(NarrativeStage)


class ObservationValidationError(ValueError):
    """Raised when an observation cannot become a proposed delta."""


class WorkflowSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: UUID
    current_stage: NarrativeStage | None = None
    completed_stages: tuple[NarrativeStage, ...] = ()
    status: str
    revision: int = Field(ge=0)


class LongFormWorkflow:
    """A bounded, resumable stage sequence; stages are not autonomous agents."""

    def start(self, *, project_id: UUID, run_key: str) -> ProductionRun:
        return ProductionRun(
            project_id=project_id,
            run_key=run_key,
            capability="LONGFORM_NARRATIVE",
            status="RUNNING",
        )

    def advance(
        self,
        run: ProductionRun,
        stage: NarrativeStage,
        *,
        artifact_ids: tuple[UUID, ...] = (),
    ) -> ProductionRun:
        completed = [item.stage for item in run.stage_results if item.status == "SUCCEEDED"]
        expected_index = len(completed)
        if expected_index >= len(LONGFORM_STAGES) or LONGFORM_STAGES[expected_index] is not stage:
            raise ValueError(
                f"invalid narrative stage transition: expected "
                f"{LONGFORM_STAGES[expected_index] if expected_index < len(LONGFORM_STAGES) else 'COMPLETE'}"
            )
        result = StageResult(stage=stage.value, status="SUCCEEDED", artifact_ids=artifact_ids)
        return run.model_copy(
            update={
                "stage_results": (*run.stage_results, result),
                "revision": run.revision + 1,
                "updated_at": datetime.now(UTC),
                "status": "SUCCEEDED" if len(completed) + 1 == len(LONGFORM_STAGES) else "RUNNING",
            }
        )

    def snapshot(self, run: ProductionRun) -> WorkflowSnapshot:
        completed = tuple(
            NarrativeStage(item.stage)
            for item in run.stage_results
            if item.status == "SUCCEEDED"
        )
        current = LONGFORM_STAGES[len(completed)] if len(completed) < len(LONGFORM_STAGES) else None
        return WorkflowSnapshot(
            run_id=run.object_id,
            current_stage=current,
            completed_stages=completed,
            status=run.status,
            revision=run.revision,
        )


class NarrativeObservationEngine:
    """Validate proposed observed facts before an explicit canon settlement."""

    def propose_delta(
        self,
        *,
        observation: NarrativeObservation,
        canon: NarrativeCanon,
    ) -> NarrativeDelta:
        if observation.project_id != canon.project_id:
            raise ObservationValidationError("observation and canon belong to different projects")
        if observation.canon_revision != canon.revision:
            raise ObservationValidationError("STALE_REVISION")
        if not observation.facts:
            raise ObservationValidationError("empty narrative observation")
        return NarrativeDelta(
            project_id=canon.project_id,
            observation_id=observation.object_id,
            base_canon_revision=canon.revision,
            proposed_facts=observation.facts,
            authority=CreativeAuthority.PROPOSAL,
        )

    def settle(
        self,
        *,
        canon: NarrativeCanon,
        delta: NarrativeDelta,
        approved_fact_indexes: tuple[int, ...],
    ) -> tuple[NarrativeCanon, tuple[ContinuityFact, ...]]:
        if delta.project_id != canon.project_id:
            raise ObservationValidationError("delta and canon belong to different projects")
        if delta.base_canon_revision != canon.revision:
            raise ObservationValidationError("STALE_REVISION")
        if not approved_fact_indexes:
            raise ObservationValidationError("no facts approved for canonical settlement")
        if any(index < 0 or index >= len(delta.proposed_facts) for index in approved_fact_indexes):
            raise ObservationValidationError("approved fact index is out of range")

        facts = tuple(
            self._fact_to_canonical(canon.project_id, delta.proposed_facts[index])
            for index in approved_fact_indexes
        )
        next_canon = canon.model_copy(
            update={
                "continuity_fact_ids": (*canon.continuity_fact_ids, *(fact.object_id for fact in facts)),
                "revision": canon.revision + 1,
                "updated_at": datetime.now(UTC),
            }
        )
        return next_canon, facts

    @staticmethod
    def _fact_to_canonical(project_id: UUID, fact: ObservationFact) -> ContinuityFact:
        source_ref = fact.source_ref
        provenance = (source_ref,) if source_ref is not None else ()
        return ContinuityFact(
            project_id=project_id,
            statement=fact.statement,
            provenance=provenance,
            authority=CreativeAuthority.CANONICAL,
        )


__all__ = [
    "LONGFORM_STAGES",
    "LongFormWorkflow",
    "NarrativeObservationEngine",
    "NarrativeStage",
    "ObservationValidationError",
    "WorkflowSnapshot",
]
