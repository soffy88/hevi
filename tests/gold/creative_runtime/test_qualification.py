"""Real synthetic qualification for the HEVI creative runtime domains."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from hevi.creative.omodul import (
    Action,
    ForecastEngine,
    HorizonReport,
    InteractiveFilmGraph,
    InteractiveFilmModule,
    LongHorizonQualifier,
    PlayEngine,
    TranslationModule,
)
from hevi.creative.oprim import (
    CreativeMemoryIndex,
    MemoryRecord,
    ProjectLock,
    ResourceBusy,
    TargetNotUnique,
    preview_exact_edit,
)
from hevi.obase.creative import (
    BranchBeat,
    Choice,
    InteractiveFilm,
    InteractiveWorld,
    NarrativeCanon,
    StoryNode,
)

GOLD_ROOT = Path(__file__).parent


def test_gold_case_catalog_has_twenty_owned_domains() -> None:
    cases = json.loads((GOLD_ROOT / "cases.json").read_text(encoding="utf-8"))
    assert len(cases) == 20
    assert len({case["id"] for case in cases}) == 20
    assert all(case["happy"] and case["failure"] for case in cases)


def test_long_horizon_fifty_chapters() -> None:
    chapters = tuple(
        {"character": "Mara knows the route", "world": "winter port", "hook": f"hook-{index}"}
        for index in range(50)
    )
    report = LongHorizonQualifier().qualify(chapters)
    assert isinstance(report, HorizonReport)
    assert report.chapter_count == 50
    assert report.hook_loss == 0
    assert report.duplicate_hook == 0
    assert report.contradiction_rate == 0


def test_longform_production_graph_completes_all_governed_stages() -> None:
    from hevi.creative.omodul import LONGFORM_STAGES, LongFormWorkflow

    project_id = uuid4()
    workflow = LongFormWorkflow()
    run = workflow.start(project_id=project_id, run_key="longform-gold")
    for stage in LONGFORM_STAGES:
        run = workflow.advance(run, stage)
    assert run.status == "SUCCEEDED"
    assert len(run.stage_results) == len(LONGFORM_STAGES)


def test_interactive_film_thirty_nodes_three_endings_and_all_paths() -> None:
    project_id = uuid4()
    start = StoryNode(title="start")
    nodes: list[StoryNode] = [start]
    choices: list[Choice] = []
    branch_ends: list[StoryNode] = []
    branch_first: list[StoryNode] = []
    for branch in range(3):
        chain = [StoryNode(title=f"branch-{branch}-{index}") for index in range(9)]
        ending = StoryNode(title=f"ending-{branch}", ending=True)
        chain.append(ending)
        branch_first.append(chain[0])
        for index, node in enumerate(chain[:-1]):
            choice = Choice(label=f"step-{branch}-{index}", target_node_id=chain[index + 1].node_id)
            choices.append(choice)
            chain[index] = node.model_copy(update={"choice_ids": (choice.choice_id,)})
        nodes.extend(chain)
        branch_ends.append(ending)
    start_choices = tuple(
        Choice(label=f"branch-{index}", target_node_id=first.node_id)
        for index, first in enumerate(branch_first)
    )
    choices.extend(start_choices)
    nodes[0] = start.model_copy(
        update={"choice_ids": tuple(choice.choice_id for choice in start_choices)}
    )
    film = InteractiveFilm(
        project_id=project_id,
        title="gold",
        start_node_id=nodes[0].node_id,
        node_ids=tuple(node.node_id for node in nodes),
        choice_ids=tuple(choice.choice_id for choice in choices),
        ending_node_ids=tuple(node.node_id for node in branch_ends),
    )
    result = InteractiveFilmModule().validate(
        InteractiveFilmGraph(film, tuple(nodes), tuple(choices))
    )
    assert len(nodes) == 31
    assert result.status == "PASS"
    assert len(result.reachable_endings) == 3


def test_play_fifty_turns_persist_and_restore(tmp_path: Path) -> None:
    world = InteractiveWorld(
        project_id=uuid4(), title="gold world", world_contract="stable", clock="turn"
    )
    engine = PlayEngine()
    state = engine.start(world, player_id="player", location="start").state
    path = tmp_path / "play.json"
    for _ in range(50):
        state, _ = engine.step(state, Action(kind="CHOICE", label="continue"))
        engine.persist_turn(path, state)
    restored = engine.restore(path)
    assert restored.revision == 50
    assert len(restored.turn_history) == 50


def test_translation_real_txt_markdown_epub_and_pdf_inputs(tmp_path: Path) -> None:
    module = TranslationModule()
    txt = tmp_path / "source.txt"
    md = tmp_path / "source.md"
    pdf = tmp_path / "source.pdf"
    txt.write_text("One\n\nTwo", encoding="utf-8")
    md.write_text("# Chapter\n\nOne\n\nTwo", encoding="utf-8")
    pdf.write_bytes(_minimal_pdf("One PDF"))
    for source in (txt, md, pdf):
        project, segments = module.ingest_path(
            project_id=uuid4(),
            source_artifact_id=uuid4(),
            path=source,
            source_language="en",
            target_language="zh",
        )
        project, segments = module.translate(
            project,
            segments,
            translator=lambda text, *_: text + "-translated",
        )
        assert project.status == "REVIEW"
        assert all(segment.translated_text for segment in segments)
        assert module.export_text(segments, fmt="txt")
        assert module.export_text(segments, fmt="markdown")
        assert module.export_text(segments, fmt="epub").startswith(b"PK")


def test_fault_injection_and_security_gates(tmp_path: Path) -> None:
    project_id = uuid4()
    memory = CreativeMemoryIndex()
    memory.add(MemoryRecord(project_id, "one", "canon", "safe fact", "canon:1"))
    with pytest.raises(ValueError, match="CREDENTIAL"):
        memory.add(MemoryRecord(project_id, "secret", "secret", "token", "x", credential=True))
    lock = ProjectLock(tmp_path / "project.lock", "run-a")
    lock.acquire()
    with pytest.raises(ResourceBusy):
        ProjectLock(tmp_path / "project.lock", "run-b").acquire()
    lock.release()
    with pytest.raises(TargetNotUnique):
        preview_exact_edit("x x", "x", "y")
    canon = NarrativeCanon(project_id=project_id)
    forecast = ForecastEngine().create(
        project_id=project_id,
        canon=canon,
        alternatives=(
            (BranchBeat(beat_id=uuid4(), description="a", change="a"),),
            (BranchBeat(beat_id=uuid4(), description="b", change="b"),),
        ),
    )
    next_canon = canon.model_copy(update={"revision": 1})
    with pytest.raises(ValueError, match="FORECAST_STALE"):
        ForecastEngine().refresh(result=forecast, canon=next_canon)


def test_remaining_gold_domains_execute_real_typed_paths() -> None:
    from hevi.creative.omodul import (
        CoverModule,
        ExportModule,
        FanficModule,
        GenreModule,
        ReviewMode,
        ReviewWorkflow,
        StyleModule,
        calculate_analytics,
    )
    from hevi.obase.creative import (
        AuditFinding,
        CoverBrief,
        CreativeArtifact,
        CreativeSource,
        GenreProfile,
        NarrativeAudit,
        ProductionRun,
    )

    project_id = uuid4()
    parent = NarrativeCanon(project_id=project_id)
    derived = FanficModule().import_parent(
        project_id=project_id,
        parent=parent,
        snapshot_hash="a" * 64,
        allow_deviation=True,
        inherited_fact_types=("CHARACTER",),
    )
    assert (
        FanficModule()
        .deviate(
            derived=derived,
            subject="ending",
            original="A",
            replacement="B",
            reason="AU",
        )
        .authority.value
        == "PROPOSAL"
    )

    brief = CoverBrief(project_id=project_id, title="Cover", visual_concept="abstract")
    cover = CoverModule().create(brief=brief, provider=lambda _: (b"image", "image/png"))
    source = CreativeSource(project_id=project_id, title="draft", source_type="GENERATED")
    artifact = CreativeArtifact(
        project_id=project_id,
        artifact_type="draft",
        uri="hevi://draft",
        media_type="text/plain",
        sha256="b" * 64,
        provenance=(),
        quality_gate_status="PASS",
    )
    audit = NarrativeAudit(
        project_id=project_id,
        artifact_id=artifact.object_id,
        status="WARN",
        findings=(
            AuditFinding(
                severity="WARN",
                dimension="PACING",
                recommendation="vary pacing",
            ),
        ),
    )
    approval = ReviewWorkflow().decide(
        project_id=project_id,
        target=artifact,
        audit=audit,
        actor_id="reviewer",
        mode=ReviewMode.MANUAL,
    )
    assert approval.decision == "REVISION_REQUEST"
    assert StyleModule().audit_naturalness("a clear sentence").status == "PASS"
    assert GenreModule().audit(GenreProfile(project_id=project_id, name="safe"), "clean") == ()
    export = ExportModule().export_text(
        project_id=project_id,
        source=artifact,
        title="draft",
        chapters=("one",),
        fmt="markdown",
    )
    assert export.export_format == "MARKDOWN"
    analytics = calculate_analytics(
        texts=("one two",),
        audits=(audit,),
        runs=(ProductionRun(project_id=project_id, run_key="r", capability="x"),),
        revision_count=1,
    )
    assert analytics.word_count == 2
    assert cover.artifact.quality_gate_status == "PASS"
    assert source.source_type == "GENERATED"


def _minimal_pdf(text: str) -> bytes:
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{index} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    output.extend(b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets[1:]))
    output.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return bytes(output)
