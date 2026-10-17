import pytest

from hevi.production_graph import (
    CanonicalShot,
    Episode,
    ProductionGraphSnapshot,
    ProductionProject,
    RevisionPatch,
    RevisionPatchError,
    RevisionPatchOperation,
    Scene,
    apply_revision_patch,
    create_director_session,
    record_director_decision,
)


def _snapshot() -> ProductionGraphSnapshot:
    project = ProductionProject(id="project-director", user_id="user", title="Director test")
    revision_id = "revision-director"
    project = project.model_copy(update={"current_revision_id": revision_id})
    from hevi.production_graph import ProductionRevision

    revision = ProductionRevision(id=revision_id, project_id=project.id)
    episode = Episode(id="episode-director", project_id=project.id)
    scene = Scene(id="scene-director", project_id=project.id, episode_id=episode.id)
    return ProductionGraphSnapshot(
        project=project, revision=revision, episodes=[episode], scenes=[scene]
    )


def test_director_decision_is_inspectable_and_patch_creates_child_revision() -> None:
    snapshot = _snapshot()
    session = create_director_session(snapshot.project, objective="Tighten the opening")
    shot = CanonicalShot(
        id="shot-director",
        project_id=snapshot.project.id,
        scene_id="scene-director",
        action_description="walks",
    )
    # An add operation is validated as a canonical model before persistence.
    patch = RevisionPatch(
        id="patch-director",
        project_id=snapshot.project.id,
        base_revision_id=snapshot.revision.id,
        actor="director",
        reason="tighten opening",
        operations=[
            RevisionPatchOperation(op="add", path="/shots/-", value=shot.model_dump(mode="json"))
        ],
    )
    decision = record_director_decision(
        session,
        decision_type="creative_revision",
        rationale="Start closer to the action",
        patch=patch,
    )
    child = apply_revision_patch(snapshot, patch)
    assert decision.output_patch_id == patch.id
    assert child.revision.parent_revision_id == snapshot.revision.id
    assert child.revision.revision_no == 2
    assert child.shots[0].action_description == "walks"
    assert child.shots[0].revision_id == child.revision.id
    assert snapshot.shots == []


def test_stale_patch_and_locked_shot_are_rejected() -> None:
    snapshot = _snapshot()
    shot = CanonicalShot(
        id="shot-locked",
        project_id=snapshot.project.id,
        scene_id="scene-director",
        readiness_state="LOCKED",
    )
    snapshot = snapshot.model_copy(update={"shots": [shot]})
    locked_patch = RevisionPatch(
        project_id=snapshot.project.id,
        base_revision_id=snapshot.revision.id,
        actor="director",
        reason="overwrite",
        operations=[
            RevisionPatchOperation(
                op="replace", path=f"/shots/{shot.id}/action_description", value="new"
            )
        ],
    )
    with pytest.raises(RevisionPatchError, match="locked shot"):
        apply_revision_patch(snapshot, locked_patch)
    stale = locked_patch.model_copy(update={"base_revision_id": "old-revision"})
    with pytest.raises(RevisionPatchError, match="stale"):
        apply_revision_patch(snapshot.model_copy(update={"shots": []}), stale)


def test_director_cannot_record_a_decision_from_closed_session() -> None:
    snapshot = _snapshot()
    session = create_director_session(snapshot.project, objective="Review")
    closed = session.model_copy(update={"status": "CLOSED"})
    with pytest.raises(RevisionPatchError, match="not OPEN"):
        record_director_decision(closed, decision_type="approval")
