"""Behavior tests for the first creative runtime modules."""

from __future__ import annotations

from uuid import uuid4

import pytest

from hevi.creative.omodul import (
    ContextBudget,
    ContextBuildError,
    ContextCandidate,
    CreativeContextCompiler,
    LongFormWorkflow,
    NarrativeAuditEngine,
    NarrativeObservationEngine,
    NarrativeStage,
    RevisionEngine,
)
from hevi.creative.oprim import (
    CreativeStateDelta,
    StaleRevisionError,
    StateOperation,
    apply_state_delta,
    persist_model,
    restore_model,
)
from hevi.obase.creative import (
    CreativeArtifact,
    CreativeAuthority,
    NarrativeCanon,
    NarrativeObservation,
    NarrativeProject,
    ObservationFact,
    ProvenanceRef,
    SceneIntent,
)


def test_stale_delta_is_rejected_without_mutating_canonical_state() -> None:
    project_id = uuid4()
    current = NarrativeProject(project_id=project_id, title="before", revision=2)
    delta = CreativeStateDelta(
        target_id=str(current.object_id),
        project_id=str(project_id),
        target_type="NarrativeProject",
        base_revision=1,
        operations=(StateOperation(path="title", value="after"),),
    )

    with pytest.raises(ValueError, match="STALE_REVISION"):
        apply_state_delta(current, delta)
    assert current.title == "before"
    assert current.revision == 2


def test_atomic_persistence_rejects_silent_overwrite(tmp_path) -> None:
    project_id = uuid4()
    first = NarrativeProject(project_id=project_id, title="first", revision=1)
    second = first.model_copy(update={"title": "second", "revision": 1})
    path = tmp_path / "project.json"

    persist_model(path, first)
    with pytest.raises(StaleRevisionError):
        persist_model(path, second)
    assert restore_model(path, NarrativeProject).title == "first"


def test_context_budget_preserves_protected_and_records_drops() -> None:
    project_id = uuid4()
    protected = ContextCandidate(
        ref=ProvenanceRef(ref_id="canon", ref_type="CANON"),
        text="canonical constraint",
        priority="P0",
        protected=True,
    )
    optional = ContextCandidate(
        ref=ProvenanceRef(ref_id="old", ref_type="SUMMARY"),
        text="old context " * 20,
        priority="P3",
    )

    manifest = CreativeContextCompiler().compile(
        project_id=project_id,
        task="draft",
        candidates=(protected, optional),
        budget=ContextBudget(max_tokens=10),
    )

    assert [item.ref.ref_id for item in manifest.selected] == ["canon"]
    assert [ref.ref_id for ref in manifest.dropped_refs] == ["old"]
    assert manifest.truncated is True

    with pytest.raises(ContextBuildError):
        CreativeContextCompiler().compile(
            project_id=project_id,
            task="draft",
            candidates=(protected,),
            budget=ContextBudget(max_tokens=1),
        )


def test_observation_requires_explicit_settlement() -> None:
    project_id = uuid4()
    canon = NarrativeCanon(project_id=project_id)
    observation = NarrativeObservation(
        project_id=project_id,
        artifact_id=uuid4(),
        canon_revision=0,
        extractor="test",
        authority=CreativeAuthority.PROJECTION,
        facts=(
            ObservationFact(
                fact_type="CHARACTER",
                statement="Mara knows the route",
                confidence=1.0,
            ),
        ),
    )
    engine = NarrativeObservationEngine()
    delta = engine.propose_delta(observation=observation, canon=canon)
    next_canon, facts = engine.settle(canon=canon, delta=delta, approved_fact_indexes=(0,))

    assert canon.revision == 0
    assert next_canon.revision == 1
    assert len(facts) == 1
    assert facts[0].object_id in next_canon.continuity_fact_ids


def test_long_form_workflow_is_ordered_and_resumable() -> None:
    project_id = uuid4()
    workflow = LongFormWorkflow()
    run = workflow.start(project_id=project_id, run_key="run-1")
    run = workflow.advance(run, NarrativeStage.RESEARCH)
    snapshot = workflow.snapshot(run)

    assert snapshot.current_stage is NarrativeStage.ARCHITECT
    assert snapshot.completed_stages == (NarrativeStage.RESEARCH,)


def test_audit_is_fail_closed_and_revision_is_proposal_only() -> None:
    project_id = uuid4()
    artifact = CreativeArtifact(
        project_id=project_id,
        artifact_type="draft",
        uri="hevi://draft/1",
        media_type="text/plain",
        sha256="a" * 64,
        authority=CreativeAuthority.CANONICAL,
    )
    audit = NarrativeAuditEngine().audit(
        project_id=project_id,
        artifact=artifact,
        canon=NarrativeCanon(project_id=project_id),
        scene_intents=(SceneIntent(project_id=project_id, sequence=1, purpose="", objective=""),),
        text="",
    )

    assert audit.status == "FAIL"
    proposal = RevisionEngine().propose(
        project_id=project_id,
        asset_id=artifact.object_id,
        base_revision=0,
        audit=audit,
    )
    assert proposal.authority is CreativeAuthority.PROPOSAL
