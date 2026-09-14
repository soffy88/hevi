"""Gold behaviour for the unified production harness runtime."""

from __future__ import annotations

from uuid import uuid4

import pytest

from hevi.creative.omodul import (
    ActionKind,
    HeavyActionConfirmation,
    ProductionHarness,
)
from hevi.obase.creative import CreativeArtifact, ProductionRun, ProvenanceRef


def _artifact(project_id):
    return CreativeArtifact(
        project_id=project_id,
        artifact_type="CREATIVE_TEXT",
        uri=f"memory://harness/{uuid4()}",
        media_type="text/plain",
        sha256="0" * 64,
        provenance=(ProvenanceRef(ref_id="fixture", ref_type="QUALIFICATION_INPUT"),),
        quality_gate_status="PASS",
    )


def _running_run(project_id):
    return ProductionRun(
        project_id=project_id,
        run_key="harness-gold",
        capability="creative.harness",
        status="RUNNING",
    )


def test_heavy_action_requires_confirmation() -> None:
    project_id = uuid4()
    harness = ProductionHarness()
    proposal = harness.propose(
        project_id=project_id,
        capability="creative.harness",
        kind=ActionKind.RENDER,
        summary="render",
        heavy=True,
    )
    with pytest.raises(PermissionError):
        harness.execute(
            proposal=proposal,
            run=_running_run(project_id),
            artifact_factory=lambda _: (),
        )


def test_cancel_refuses_execution_and_resume_restores() -> None:
    project_id = uuid4()
    harness = ProductionHarness()
    run = _running_run(project_id)
    proposal = harness.propose(
        project_id=project_id,
        capability="creative.harness",
        kind=ActionKind.WRITE,
        summary="write",
        heavy=False,
    )
    cancelled = harness.cancel(proposal=proposal, run=run)
    assert cancelled.result.status == "CANCELLED"
    assert cancelled.run.status == "CANCELLED"
    with pytest.raises(ValueError, match="RUN_CANCELLED"):
        harness.execute(
            proposal=proposal,
            run=cancelled.run,
            artifact_factory=lambda _: (_artifact(project_id),),
        )
    resumed = harness.resume(run=cancelled.run)
    assert resumed.status == "RUNNING"
    assert resumed.failure is None
    outcome = harness.execute(
        proposal=proposal,
        run=resumed,
        artifact_factory=lambda _: (_artifact(project_id),),
    )
    assert outcome.result.status == "SUCCEEDED"
    assert outcome.run.status == "SUCCEEDED"


def test_bounded_retry_stops_at_bound() -> None:
    project_id = uuid4()
    harness = ProductionHarness()
    proposal = harness.propose(
        project_id=project_id,
        capability="creative.harness",
        kind=ActionKind.RENDER,
        summary="flaky",
        heavy=False,
    )
    outcome = harness.execute(
        proposal=proposal,
        run=_running_run(project_id),
        artifact_factory=lambda _: (),
        max_attempts=3,
    )
    assert outcome.result.status == "FAILED"
    assert len(outcome.run.stage_results) == 3
    assert outcome.run.failure is not None
    assert outcome.run.failure.retryable is True


def test_retry_bound_must_be_positive() -> None:
    project_id = uuid4()
    harness = ProductionHarness()
    proposal = harness.propose(
        project_id=project_id,
        capability="creative.harness",
        kind=ActionKind.READ,
        summary="read",
        heavy=False,
    )
    with pytest.raises(ValueError, match="INVALID_RETRY_BOUND"):
        harness.execute(
            proposal=proposal,
            run=_running_run(project_id),
            artifact_factory=lambda _: (),
            max_attempts=0,
        )


def test_heavy_confirmation_actor_is_recorded() -> None:
    project_id = uuid4()
    harness = ProductionHarness()
    proposal = harness.propose(
        project_id=project_id,
        capability="creative.harness",
        kind=ActionKind.PUBLISH,
        summary="publish",
        heavy=True,
    )
    confirmation = HeavyActionConfirmation(
        action_id=proposal.action_id, actor_id="owner", confirmed=True
    )
    outcome = harness.execute(
        proposal=proposal,
        run=_running_run(project_id),
        confirmation=confirmation,
        artifact_factory=lambda _: (_artifact(project_id),),
    )
    assert outcome.result.status == "SUCCEEDED"
