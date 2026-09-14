"""Behavior gates for additive creative capability modules."""

from __future__ import annotations

from uuid import uuid4

import pytest

from hevi.creative.omodul import (
    Action,
    ForecastEngine,
    GenreModule,
    GraphValidation,
    ImportModule,
    InteractiveFilmGraph,
    InteractiveFilmModule,
    PlayEngine,
    ResearchModule,
    ScriptModule,
    StoryboardModule,
    StyleModule,
    TranslationModule,
)
from hevi.creative.oprim import (
    CreativeMemoryIndex,
    MemoryRecord,
    TargetNotUnique,
    preview_exact_edit,
)
from hevi.obase.creative import (
    BranchBeat,
    Choice,
    CreativeAuthority,
    GenreProfile,
    InteractiveFilm,
    InteractiveWorld,
    NarrativeCanon,
    ProvenanceRef,
    SceneIntent,
    StoryNode,
)


def test_forecast_selection_does_not_change_canon() -> None:
    project_id = uuid4()
    canon = NarrativeCanon(project_id=project_id)
    result = ForecastEngine().create(
        project_id=project_id,
        canon=canon,
        alternatives=(
            (BranchBeat(beat_id=uuid4(), description="a", change="x"),),
            (BranchBeat(beat_id=uuid4(), description="b", change="y"),),
        ),
    )
    selection = ForecastEngine().select(
        result=result,
        branch_id=result.branches[0].object_id,
        canon=canon,
    )
    assert selection.authority is CreativeAuthority.PROPOSAL
    assert canon.revision == 0


def test_research_requires_explicit_claim_acceptance() -> None:
    project_id = uuid4()
    module = ResearchModule()
    report = module.create_report(project_id=project_id, query="era")
    report, source = module.add_source(report, title="owned source", uri="hevi://source/1")
    report, evidence = module.add_claim(report, source=source, claim="a reviewed fact")
    assert report.evidence_ids == (evidence.object_id,)
    assert module.accept_claim(evidence).statement == "a reviewed fact"


def test_import_splits_chapters_into_project_state() -> None:
    result = ImportModule().import_text(title="Imported", text="# One\n\nA\n\n# Two\n\nB")
    assert result.project.canon_id == result.canon.object_id
    assert result.chapters == ("A", "B")
    assert result.unresolved


def test_script_and_storyboard_are_structured() -> None:
    project_id = uuid4()
    scene = SceneIntent(project_id=project_id, sequence=1, purpose="turn", objective="open door")
    script = ScriptModule().create(project_id=project_id, title="S", scenes=(scene,))
    storyboard = StoryboardModule().create(
        project_id=project_id,
        script=script.script,
        scenes=script.scenes,
    )
    assert storyboard.storyboard.script_id == script.script.object_id
    assert storyboard.shots[0].duration_ms > 0


def test_interactive_film_graph_detects_dead_nodes() -> None:
    project_id = uuid4()
    start = StoryNode(title="start")
    ending = StoryNode(title="end", ending=True)
    dead = StoryNode(title="dead")
    choice = Choice(label="go", target_node_id=ending.node_id)
    start = start.model_copy(update={"choice_ids": (choice.choice_id,)})
    film = InteractiveFilm(
        project_id=project_id,
        title="film",
        start_node_id=start.node_id,
        node_ids=(start.node_id, ending.node_id, dead.node_id),
        choice_ids=(choice.choice_id,),
    )
    result = InteractiveFilmModule().validate(
        InteractiveFilmGraph(film, (start, ending, dead), (choice,))
    )
    assert isinstance(result, GraphValidation)
    assert result.status == "FAIL"
    assert dead.node_id in result.unreachable_nodes


def test_play_turn_is_durable_state_transition() -> None:
    project_id = uuid4()
    world = InteractiveWorld(
        project_id=project_id, title="world", world_contract="rules", clock="turn"
    )
    state = PlayEngine().start(world, player_id="p", location="home").state
    next_state, result = PlayEngine().step(state, Action(kind="CHOICE", label="look"))
    assert next_state.revision == 1
    assert result.turn.number == 0
    assert len(next_state.turn_history) == 1


def test_translation_resume_and_export() -> None:
    module = TranslationModule()
    project, segments = module.ingest(
        project_id=uuid4(),
        source_artifact_id=uuid4(),
        text="one\n\ntwo",
        source_language="en",
        target_language="zh",
    )
    partial = segments[0].model_copy(update={"translated_text": "一"})
    project, translated = module.resume(
        project,
        (partial, segments[1]),
        translator=lambda text, *_: text + "-zh",
    )
    assert project.status == "REVIEW"
    assert all(segment.translated_text for segment in translated)
    assert module.export_text(translated, fmt="txt").decode().endswith("two-zh")


def test_style_and_genre_quality_checks_are_structured() -> None:
    style = StyleModule()
    profile = style.analyze(
        project_id=uuid4(), name="measured", text="A short sentence. Another one."
    )
    assert style.apply(profile).profile_id == profile.object_id
    genre = GenreModule().audit(
        GenreProfile(project_id=profile.project_id, name="safe", forbidden_patterns=("secret",)),
        "The secret is here.",
    )
    assert genre[0].code == "FORBIDDEN_PATTERN"


def test_memory_is_project_isolated_and_rejects_credentials() -> None:
    index = CreativeMemoryIndex()
    project_id = uuid4()
    index.add(MemoryRecord(project_id, "a", "chapter", "route through north", "chapter:1"))
    assert len(index.recall(project_id=project_id, query="north")) == 1
    assert not index.recall(project_id=uuid4(), query="north")
    with pytest.raises(ValueError, match="CREDENTIAL"):
        index.add(
            MemoryRecord(project_id, "secret", "credential", "token", "secret", credential=True)
        )


def test_targeted_editing_fails_closed_when_ambiguous() -> None:
    with pytest.raises(TargetNotUnique):
        preview_exact_edit("same same", "same", "new")


def test_materials_and_market_radar_remain_project_scoped_evidence() -> None:
    from hevi.creative.omodul import MarketRadar, MaterialModule, TrendEvidence

    project_id = uuid4()
    material, source = MaterialModule().import_material(
        project_id=project_id,
        name="notes",
        material_type="TEXT",
        uri="hevi://material/1",
    )
    assert material.source_id == source.object_id
    evidence = TrendEvidence(
        topic="genre",
        value="rising",
        confidence=0.8,
        source=ProvenanceRef(ref_id=str(source.object_id), ref_type="MATERIAL"),
    )
    snapshot = MarketRadar().snapshot(project_id=project_id, evidence=(evidence,))
    assert MarketRadar().summarize(snapshot)[0].topic == "genre"


def test_production_harness_requires_artifact_and_confirmation() -> None:
    from hevi.creative.omodul import HeavyActionConfirmation, ProductionHarness
    from hevi.obase.creative import ProductionRun

    project_id = uuid4()
    harness = ProductionHarness()
    proposal = harness.propose(
        project_id=project_id,
        capability="SCRIPT",
        kind="RENDER",
        summary="render draft",
        heavy=True,
    )
    run = ProductionRun(project_id=project_id, run_key="r", capability="SCRIPT")
    with pytest.raises(PermissionError):
        harness.execute(proposal=proposal, run=run, artifact_factory=lambda _: ())
    result = harness.execute(
        proposal=proposal,
        run=run,
        confirmation=HeavyActionConfirmation(
            action_id=proposal.action_id,
            actor_id="owner",
            confirmed=True,
        ),
        artifact_factory=lambda _: (),
    )
    assert result.result.status == "FAILED"


def test_short_fiction_is_a_structured_production_package() -> None:
    from hevi.creative.omodul import ShortFictionModule

    production = ShortFictionModule().create(
        project_id=uuid4(),
        title="Short",
        direction="a choice",
        genre="mystery",
        chapter_count=2,
        length=10,
        language="en",
    )
    assert len(production.manuscript) == 2


def test_intent_comparison_does_not_turn_not_evaluable_into_pass() -> None:
    from hevi.creative.omodul.comparison import ComparisonModule
    from hevi.obase.creative import ArtifactProfile, NarrativeIntentProfile

    project_id = uuid4()
    intent = NarrativeIntentProfile(project_id=project_id, goal="goal")
    artifact = ArtifactProfile(project_id=project_id, artifact_id=uuid4())
    comparison = ComparisonModule().compare(intent=intent, artifact=artifact)
    assert comparison.status == "NOT_EVALUABLE"


def test_length_governance_has_hard_range_and_bounded_normalization() -> None:
    from hevi.creative.omodul import LengthModule, LengthPolicy

    policy = LengthPolicy(target_words=5, soft_min=4, soft_max=6, hard_min=2, hard_max=8)
    module = LengthModule()
    assert module.inspect("one two", policy).status == "WARN"
    text, report = module.normalize(
        "one two",
        policy,
        generator=lambda current, _direction, target: (
            current + " three four five" if target == 5 else current
        ),
    )
    assert len(text.split()) == 5
    assert report.passes == 1


def test_policy_skill_run_snapshot_workspace_backup_routing_webhook_and_service(tmp_path) -> None:
    from hevi.creative.omodul import BackgroundRunController, PolicyModule
    from hevi.creative.oprim import (
        AtomicWorkspace,
        ModelRouter,
        Route,
        WebhookLedger,
        WebhookSigner,
        backup_workspace,
        claim_delivery,
    )
    from hevi.creative.oservi import CreativeServiceSurface, ServiceRequest, ServiceResult
    from hevi.creative.oskill import default_skill
    from hevi.obase.creative import CreativePolicy, ProductionRun, RunSnapshot

    project_id = uuid4()
    skill = default_skill("long-form-writing", project_id)
    assert skill.can_write_state is False
    policy = CreativePolicy(project_id=project_id, name="base", scope="PROJECT", rules=("safe",))
    updated = policy.model_copy(update={"rules": ("safe", "concise"), "version": 2})
    assert PolicyModule().diff(policy, updated).added == ("concise",)
    run = ProductionRun(project_id=project_id, run_key="r", capability="x", status="RUNNING")
    cancelled = BackgroundRunController().cancel(run)
    assert cancelled.status == "CANCELLED"
    snapshot = RunSnapshot(
        project_id=project_id, run_id=run.object_id, stage="draft", state_hash="h"
    )
    assert snapshot.run_id == run.object_id
    workspace_root = tmp_path / "workspace"
    workspace = AtomicWorkspace(workspace_root)
    workspace.begin()
    workspace.stage_json("state.json", {"project": str(project_id)})
    workspace.commit()
    assert (workspace_root / "state.json").is_file()
    backup = backup_workspace(workspace_root, tmp_path / "backup")
    assert (backup / "manifest.json").is_file()
    route = ModelRouter(Route(provider="OPENAI_COMPATIBLE", model="veya1.2-free"))
    route.set_capability("script", Route(provider="LOCAL", model="creative"))
    assert route.resolve(capability="script").model == "creative"
    signer = WebhookSigner(b"test")
    signature = signer.sign("event", {"status": "done"})
    assert signer.verify(signature, "event", {"status": "done"})
    ledger = WebhookLedger()
    assert claim_delivery(ledger, "event") is True
    assert claim_delivery(ledger, "event") is False
    surface = CreativeServiceSurface()

    def handler(request: ServiceRequest) -> ServiceResult:
        return ServiceResult(
            request_id=request.request_id, service=request.service, status="SUCCEEDED"
        )

    surface.register("creative.export", handler)
    request = ServiceRequest(
        service="creative.export",
        project_id=project_id,
        idempotency_key="x",
    )
    assert surface.call(request).status == "SUCCEEDED"
