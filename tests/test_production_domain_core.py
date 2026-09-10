from __future__ import annotations

import pytest

from hevi.production_graph import (
    ProductionGraphRepository,
    ProductionProject,
    SourceChunk,
    SourceDocument,
    stable_id,
)


def test_import_ids_are_stable_and_namespaced() -> None:
    assert stable_id("character", "C001") == stable_id("character", "C001")
    assert stable_id("character", "C001") != stable_id("event", "C001")
    with pytest.raises(ValueError):
        stable_id("", "C001")


@pytest.mark.asyncio
async def test_revisions_are_isolated_and_parented() -> None:
    repository = ProductionGraphRepository()
    first = await repository.create_project(ProductionProject(user_id="u", title="Gold"))
    document = SourceDocument(
        project_id=first.project.id,
        revision_id=first.revision.id,
        content_hash="hash",
    )
    chunk = SourceChunk(
        document_id=document.id,
        revision_id=first.revision.id,
        start_offset=0,
        end_offset=4,
        text_hash="text-hash",
        text="gold",
    )
    first_with_source = first.model_copy(update={"sources": [document], "source_chunks": [chunk]})
    second = await repository.append_revision(first_with_source, actor="director", reason="add source")

    assert second.revision.id != first.revision.id
    assert second.revision.parent_revision_id == first.revision.id
    assert second.revision.revision_no == 2
    parent = await repository.get_snapshot(first.project.id, revision_id=first.revision.id)
    assert parent is not None
    assert parent.sources == []
    # The in-memory repository keeps the active snapshot, while the caller's
    # original Pydantic object remains unchanged.
    active = await repository.get_snapshot(first.project.id)
    assert active is not None
    assert active.revision.id == second.revision.id
    assert first.sources == []


def test_source_chunk_rejects_reversed_span() -> None:
    with pytest.raises(ValueError, match="end_offset"):
        SourceChunk(document_id="doc", start_offset=5, end_offset=4, text_hash="x")
