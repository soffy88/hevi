"""Unified HEVI creative production harness over existing runtime primitives."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from hevi.obase.creative import CreativeArtifact, ProductionRun


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
    ) -> ProductionOutcome:
        if proposal.heavy and (
            confirmation is None
            or confirmation.action_id != proposal.action_id
            or not confirmation.confirmed
        ):
            raise PermissionError("HEAVY_ACTION_CONFIRMATION_REQUIRED")
        artifacts = artifact_factory(run)
        if not artifacts:
            result = ActionResult(
                action_id=proposal.action_id,
                status="FAILED",
                run_id=run.object_id,
                failure_code="ARTIFACT_REQUIRED_FOR_SUCCESS",
            )
            return ProductionOutcome(run, (), result)
        result = ActionResult(
            action_id=proposal.action_id,
            status="SUCCEEDED",
            artifact_ids=tuple(artifact.object_id for artifact in artifacts),
            run_id=run.object_id,
        )
        return ProductionOutcome(run, artifacts, result)


__all__ = [
    "ActionKind",
    "ActionProposal",
    "ActionResult",
    "HeavyActionConfirmation",
    "ProductionHarness",
    "ProductionOutcome",
]
