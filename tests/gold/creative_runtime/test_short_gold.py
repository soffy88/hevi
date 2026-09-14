"""Gold behaviour for the short-fiction production package runtime."""

from __future__ import annotations

from uuid import uuid4

import pytest

from hevi.creative.omodul import (
    ExportModule,
    GenreModule,
    LengthModule,
    LengthPolicy,
    RevisionEngine,
    RevisionLimitError,
    RevisionPolicy,
)
from hevi.obase.creative import AuditFinding, CreativeArtifact, NarrativeAudit, ProvenanceRef


def _passing_artifact():
    project_id = uuid4()
    return project_id, CreativeArtifact(
        project_id=project_id,
        artifact_type="CREATIVE_TEXT",
        uri=f"memory://short/{uuid4()}",
        media_type="text/plain",
        sha256="0" * 64,
        provenance=(ProvenanceRef(ref_id="fixture", ref_type="QUALIFICATION_INPUT"),),
        quality_gate_status="PASS",
    )


def test_genre_plan_drives_length_policy() -> None:
    project_id = uuid4()
    planner = GenreModule()
    plan = planner.plan(
        planner.profile(project_id=project_id, name="mystery"),
        brief="a key in the harbour",
        chapter_count=3,
    )
    target = plan.target_words_per_chapter
    policy = LengthPolicy(
        target_words=target,
        soft_min=int(target * 0.8),
        soft_max=int(target * 1.2),
        hard_min=int(target * 0.5),
        hard_max=int(target * 2.0),
    )

    def expand(current: str, _direction: str, word_target: int) -> str:
        words = current.split()
        while len(words) < word_target:
            words.append(plan.beats[len(words) % len(plan.beats)])
        return " ".join(words)

    text, report = LengthModule().normalize("short chapter", policy, generator=expand)
    assert report.status == "PASS"
    assert report.word_count == target
    assert any(beat in text for beat in plan.beats)


def test_export_rejects_failed_gate_and_roundtrips() -> None:
    project_id, artifact = _passing_artifact()
    module = ExportModule()
    chapters = ("Chapter one.", "Chapter two.")
    exported = {
        fmt: module.export_text(
            project_id=project_id,
            source=artifact,
            title="Owned",
            chapters=chapters,
            fmt=fmt,
        )
        for fmt in ("txt", "markdown", "epub")
    }
    assert exported["txt"].source_ids == (artifact.object_id,)
    assert exported["epub"].export_format == "EPUB"
    assert module._epub("Owned", chapters).startswith(b"PK")

    rejected = artifact.model_copy(update={"quality_gate_status": "FAIL"})
    with pytest.raises(ValueError, match="QUALITY_GATE"):
        module.export_text(
            project_id=project_id, source=rejected, title="Owned", chapters=chapters, fmt="txt"
        )
    recovered = module.export_text(
        project_id=project_id, source=artifact, title="Owned", chapters=chapters, fmt="txt"
    )
    assert recovered.sha256 == exported["txt"].sha256


def test_revision_repairs_repeat_and_enforces_limit() -> None:
    project_id, artifact = _passing_artifact()
    engine = RevisionEngine(RevisionPolicy(max_passes=2))
    audit = NarrativeAudit(
        project_id=project_id,
        artifact_id=artifact.object_id,
        status="FAIL",
        findings=(
            AuditFinding(
                severity="WARN",
                dimension="REPETITION",
                recommendation="collapse the repeated phrase",
                code="RP_REPEATED_PHRASE",
            ),
        ),
    )
    plan = engine.plan(
        asset_id=artifact.object_id, base_revision=0, audit=audit, change_type="POLISH"
    )
    execution = engine.execute(
        asset_id=artifact.object_id,
        base_revision=0,
        plan=plan,
        text="alpha alpha alpha alpha beta",
        change_type="POLISH",
    )
    assert execution.resolved_codes == ("RP_REPEATED_PHRASE",)
    assert execution.original_hash != execution.revised_hash
    with pytest.raises(RevisionLimitError, match="REVISION_LIMIT"):
        engine.candidate(
            project_id=project_id, asset_id=artifact.object_id, base_revision=0, pass_number=3
        )
