"""Gold behaviour for structured creative export packages."""

from __future__ import annotations

import hashlib
from uuid import uuid4

import pytest

from hevi.creative.omodul import ExportModule
from hevi.obase.creative import Choice, CreativeArtifact, InteractiveFilm, ProvenanceRef, StoryNode


def _source(project_id, *, status="PASS"):
    return CreativeArtifact(
        project_id=project_id,
        artifact_type="CREATIVE_TEXT",
        uri=f"memory://export-source/{project_id}",
        media_type="text/plain",
        sha256="0" * 64,
        provenance=(ProvenanceRef(ref_id="fixture", ref_type="QUALIFICATION_INPUT"),),
        quality_gate_status=status,
    )


def test_structured_playable_export_hashes_and_provenance() -> None:
    project_id = uuid4()
    source = _source(project_id)
    start = StoryNode(title="start")
    ending = StoryNode(title="ending", ending=True)
    finish = Choice(label="finish", target_node_id=ending.node_id)
    start = start.model_copy(update={"choice_ids": (finish.choice_id,)})
    film = InteractiveFilm(
        project_id=project_id,
        title="Owned Export",
        start_node_id=start.node_id,
        node_ids=(start.node_id, ending.node_id),
        choice_ids=(finish.choice_id,),
        ending_node_ids=(ending.node_id,),
    )
    payload = {"film": film.model_dump(mode="json"), "choices": [finish.model_dump(mode="json")]}
    module = ExportModule()
    artifact = module.export_structured(
        project_id=project_id, source=source, value=payload, export_format="PLAYABLE"
    )
    written = module.export_json(payload)
    assert artifact.export_format == "PLAYABLE"
    assert artifact.sha256 == hashlib.sha256(written).hexdigest()
    assert artifact.source_ids == (source.object_id,)
    assert artifact.quality_gate_status == "PASS"


def test_structured_export_requires_passing_gate() -> None:
    project_id = uuid4()
    with pytest.raises(ValueError, match="EXPORT_SOURCE_QUALITY_GATE_REQUIRED"):
        ExportModule().export_structured(
            project_id=project_id,
            source=_source(project_id, status="FAIL"),
            value={"ok": True},
        )
