"""Phase 1 contract tests for the HEVI-native creative runtime."""

from __future__ import annotations

from uuid import uuid4

import pytest

from hevi.obase.creative import (
    CREATIVE_CONTRACT_VERSION,
    CreativeAuthority,
    NarrativeBranch,
    NarrativeCanon,
    NarrativeProject,
    ProvenanceRef,
    StoryBible,
)


def test_canonical_objects_round_trip_with_stable_schema() -> None:
    project_id = uuid4()
    canon = NarrativeCanon(project_id=project_id)
    bible = StoryBible(
        project_id=project_id,
        premise="A courier chooses what to preserve.",
        canon_id=canon.object_id,
    )
    project = NarrativeProject(
        project_id=project_id,
        title="The Archive Road",
        story_bible_id=bible.object_id,
        canon_id=canon.object_id,
    )

    restored = NarrativeProject.model_validate_json(project.model_dump_json())

    assert restored == project
    assert restored.schema_version == CREATIVE_CONTRACT_VERSION
    assert restored.project_id == project_id
    assert restored.object_id == project.object_id
    assert restored.calculated_hash() == project.calculated_hash()


def test_provenance_is_explicit_and_hash_validated() -> None:
    ref = ProvenanceRef(
        ref_id="source-1",
        ref_type="SOURCE",
        uri="hevi://source/1",
        sha256="a" * 64,
        locator="page:2",
    )
    project = NarrativeProject(project_id=uuid4(), title="Traceable", provenance=(ref,))

    assert project.provenance[0].ref_type == "SOURCE"
    assert project.provenance[0].sha256 == "a" * 64

    with pytest.raises(ValueError):
        ProvenanceRef(ref_id="bad", ref_type="SOURCE", sha256="not-a-sha")


def test_forecast_branch_cannot_be_canonical() -> None:
    with pytest.raises(ValueError, match="non-canonical"):
        NarrativeBranch(project_id=uuid4(), name="bad", base_canon_revision=0)

    branch = NarrativeBranch(
        project_id=uuid4(),
        name="possible path",
        base_canon_revision=0,
        authority=CreativeAuthority.PROPOSAL,
    )
    assert branch.authority is CreativeAuthority.PROPOSAL


def test_canonical_objects_reject_unknown_fields() -> None:
    with pytest.raises(ValueError):
        NarrativeProject(project_id=uuid4(), title="strict", accidental_state="bad")
