"""Unified HEVI creative production harness over existing runtime primitives."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from hevi.obase.creative import (
    CreativeArtifact,
    FailureRecord,
    ProductionRun,
    StageResult,
)


class ActionKind(StrEnum):
    READ = "READ"
    PLAN = "PLAN"
    WRITE = "WRITE"
    RENDER = "RENDER"
    PUBLISH = "PUBLISH"


class ActionProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    action_id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    capability: str
    kind: ActionKind
    summary: str
    input_refs: tuple[str, ...] = ()
    heavy: bool = False


class HeavyActionConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    action_id: UUID
    actor_id: str
    confirmed: bool


class ActionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    action_id: UUID
    status: str
    artifact_ids: tuple[UUID, ...] = ()
    run_id: UUID | None = None
    failure_code: str | None = None


@dataclass(frozen=True)
class ProductionOutcome:
    run: ProductionRun
    artifacts: tuple[CreativeArtifact, ...]
    result: ActionResult


ArtifactFactory = Callable[[ProductionRun], tuple[CreativeArtifact, ...]]


class ProductionHarness:
    """One semantic execution contract for service/UI/CLI/TUI callers."""

    def propose(
        self,
        *,
        project_id: UUID,
        capability: str,
        kind: ActionKind,
        summary: str,
        heavy: bool,
        input_refs: tuple[str, ...] = (),
    ) -> ActionProposal:
        return ActionProposal(
            project_id=project_id,
            capability=capability,
            kind=kind,
            summary=summary,
            heavy=heavy,
            input_refs=input_refs,
        )

    def execute(
        self,
        *,
        proposal: ActionProposal,
        run: ProductionRun,
        artifact_factory: ArtifactFactory,
        confirmation: HeavyActionConfirmation | None = None,
        max_attempts: int = 1,
        retryable_codes: tuple[str, ...] = ("ARTIFACT_REQUIRED_FOR_SUCCESS",),
    ) -> ProductionOutcome:
        if run.status == "CANCELLED":
            raise ValueError("RUN_CANCELLED")
        if max_attempts < 1:
            raise ValueError("INVALID_RETRY_BOUND")
        if proposal.heavy and (
            confirmation is None
            or confirmation.action_id != proposal.action_id
            or not confirmation.confirmed
        ):
            raise PermissionError("HEAVY_ACTION_CONFIRMATION_REQUIRED")
        stage = proposal.kind.value
        attempts: list[StageResult] = []
        for attempt in range(1, max_attempts + 1):
            artifacts = artifact_factory(run)
            if artifacts:
                attempts.append(
                    StageResult(
                        stage=stage,
                        status="SUCCEEDED",
                        artifact_ids=tuple(artifact.object_id for artifact in artifacts),
                    )
                )
                final_run = run.model_copy(
                    update={
                        "status": "SUCCEEDED",
                        "stage_results": (*run.stage_results, *attempts),
                        "failure": None,
                        "revision": run.revision + 1,
                    }
                )
                result = ActionResult(
                    action_id=proposal.action_id,
                    status="SUCCEEDED",
                    artifact_ids=tuple(artifact.object_id for artifact in artifacts),
                    run_id=run.object_id,
                )
                return ProductionOutcome(final_run, artifacts, result)
            code = "ARTIFACT_REQUIRED_FOR_SUCCESS"
            attempts.append(StageResult(stage=stage, status="FAILED", error_code=code))
            if code not in retryable_codes or attempt == max_attempts:
                failure = FailureRecord(
                    code=code,
                    message=f"{stage} produced no artifact after {attempt} attempt(s)",
                    retryable=code in retryable_codes,
                    stage=stage,
                )
                final_run = run.model_copy(
                    update={
                        "status": "FAILED",
                        "stage_results": (*run.stage_results, *attempts),
                        "failure": failure,
                        "revision": run.revision + 1,
                    }
                )
                result = ActionResult(
                    action_id=proposal.action_id,
                    status="FAILED",
                    run_id=run.object_id,
                    failure_code=code,
                )
                return ProductionOutcome(final_run, (), result)
        raise AssertionError("unreachable retry state")

    def cancel(
        self,
        *,
        proposal: ActionProposal,
        run: ProductionRun,
        reason: str = "ACTION_CANCELLED",
    ) -> ProductionOutcome:
        if run.status != "RUNNING":
            raise ValueError("RUN_NOT_CANCELLABLE")
        stage = proposal.kind.value
        cancelled = run.model_copy(
            update={
                "status": "CANCELLED",
                "stage_results": (*run.stage_results, StageResult(stage=stage, status="CANCELLED", error_code=reason)),
                "failure": FailureRecord(
                    code=reason,
                    message=f"{stage} cancelled by operator",
                    retryable=True,
                    stage=stage,
                ),
                "revision": run.revision + 1,
            }
        )
        result = ActionResult(
            action_id=proposal.action_id,
            status="CANCELLED",
            run_id=run.object_id,
            failure_code=reason,
        )
        return ProductionOutcome(cancelled, (), result)

    def resume(self, *, run: ProductionRun) -> ProductionRun:
        if run.status not in ("FAILED", "CANCELLED"):
            raise ValueError("RUN_NOT_RESUMABLE")
        return run.model_copy(
            update={"status": "RUNNING", "failure": None, "revision": run.revision + 1}
        )


__all__ = [
    "ActionKind",
    "ActionProposal",
    "ActionResult",
    "HeavyActionConfirmation",
    "ProductionHarness",
    "ProductionOutcome",
]
