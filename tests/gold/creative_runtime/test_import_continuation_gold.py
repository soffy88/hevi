"""Gold behaviour for existing-work import, reconstruction, and continuation."""

from __future__ import annotations

from uuid import uuid4

import pytest

from hevi.creative.omodul import ImportModule, NarrativeObservationEngine
from hevi.obase.creative import CreativeArtifact, CreativeAuthority, ProvenanceRef

MANUSCRIPT = "\n\n".join(
    f"# Chapter {number}\nMara records chapter {number} at the winter harbour."
    for number in range(1, 21)
)


def _artifact(project_id):  # type: ignore[no-untyped-def]
    digest = "a" * 64
    return CreativeArtifact(
        project_id=project_id,
        artifact_type="CREATIVE_TEXT",
        uri="mem://continuation.txt",
        media_type="text/plain",
        sha256=digest,
        provenance=(ProvenanceRef(ref_id="continuation", ref_type="TEST", sha256=digest),),
        quality_gate_status="PASS",
        authority=CreativeAuthority.EVIDENCE,
    )


def test_reconstruction_is_deterministic() -> None:
    module = ImportModule()
    project_id = uuid4()
    result = module.import_text(title="Owned", text=MANUSCRIPT, project_id=project_id)
    first = module.reconstruct(result)
    second = module.reconstruct(result)

    assert [character.name for character in first.characters] == ["Mara"]
    assert [rule.statement for rule in first.world_rules] == ["winter harbour"]
    assert [character.name for character in second.characters] == ["Mara"]
    assert [rule.statement for rule in second.world_rules] == ["winter harbour"]
    assert first.timeline.current_marker == "chapter-20"
    assert len(first.hooks) == 1
    assert len(first.summaries) == 20


def test_canon_links_all_reconstructed_state() -> None:
    module = ImportModule()
    project_id = uuid4()
    result = module.import_text(title="Owned", text=MANUSCRIPT, project_id=project_id)
    state = module.reconstruct(result)

    assert state.canon.character_ids == tuple(c.object_id for c in state.characters)
    assert state.canon.world_rule_ids == tuple(r.object_id for r in state.world_rules)
    assert state.canon.hook_ids == tuple(h.object_id for h in state.hooks)
    assert state.canon.timeline_state_id == state.timeline.object_id
    assert state.canon.revision == result.canon.revision + 1
    assert all(
        summary.character_ids == state.canon.character_ids for summary in state.summaries
    )


def test_continuation_commits_to_canon() -> None:
    module = ImportModule()
    project_id = uuid4()
    result = module.import_text(title="Owned", text=MANUSCRIPT, project_id=project_id)
    state = module.reconstruct(result)
    chapters = module.draft_continuation(result, state, count=3)
    assert chapters == (
        "Mara continues the account in chapter 21.",
        "Mara continues the account in chapter 22.",
        "Mara continues the account in chapter 23.",
    )
    observation = module.continuation_observation(
        state, chapters=chapters, artifact=_artifact(project_id)
    )
    engine = NarrativeObservationEngine()
    delta = engine.propose_delta(observation=observation, canon=state.canon)
    committed, facts = engine.settle(
        canon=state.canon,
        delta=delta,
        approved_fact_indexes=tuple(range(len(chapters))),
    )

    assert len(facts) == 3
    assert committed.revision == state.canon.revision + 1
    assert len(committed.continuity_fact_ids) == 3
    assert all(fact.authority is CreativeAuthority.CANONICAL for fact in facts)
    assert all(fact.provenance for fact in facts)


def test_stale_continuation_rejected() -> None:
    module = ImportModule()
    project_id = uuid4()
    result = module.import_text(title="Owned", text=MANUSCRIPT, project_id=project_id)
    state = module.reconstruct(result)
    chapters = module.draft_continuation(result, state, count=1)
    observation = module.continuation_observation(
        state, chapters=chapters, artifact=_artifact(project_id)
    )
    engine = NarrativeObservationEngine()
    delta = engine.propose_delta(observation=observation, canon=state.canon)
    committed, _ = engine.settle(
        canon=state.canon, delta=delta, approved_fact_indexes=(0,)
    )

    with pytest.raises(ValueError, match="STALE_REVISION"):
        engine.propose_delta(observation=observation, canon=committed)


def test_cross_project_continuation_rejected() -> None:
    module = ImportModule()
    result = module.import_text(title="Owned", text=MANUSCRIPT, project_id=uuid4())
    state = module.reconstruct(result)
    other = module.import_text(title="Other", text=MANUSCRIPT, project_id=uuid4())
    other_state = module.reconstruct(other)
    chapters = module.draft_continuation(other, other_state, count=1)
    observation = module.continuation_observation(
        other_state, chapters=chapters, artifact=_artifact(other.project.project_id)
    )

    with pytest.raises(ValueError, match="different projects"):
        NarrativeObservationEngine().propose_delta(observation=observation, canon=state.canon)


def test_empty_import_rejected() -> None:
    with pytest.raises(ValueError, match="IMPORT_EMPTY_SOURCE"):
        ImportModule().import_text(title="Empty", text="   ")
