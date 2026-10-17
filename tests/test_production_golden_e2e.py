import json
from pathlib import Path

import pytest

from hevi.compiler import ProductionCompiler, ProviderCapabilities, ResourceBudget
from hevi.production.artifacts import Artifact, ArtifactManifest, verify_local_manifest
from hevi.production_graph import (
    AdaptationDecision,
    AdaptationPlan,
    Beat,
    CameraSpec,
    CanonicalShot,
    CharacterState,
    ContinuityConstraint,
    DirectorDecision,
    DirectorSession,
    Episode,
    ExecutionAttempt,
    GenerationIntent,
    Location,
    LocationState,
    LookVariant,
    PlotThread,
    ProductionGraphRepository,
    ProductionGraphSnapshot,
    ProductionMode,
    ProductionPlan,
    ProductionProject,
    ProductionRevision,
    Prop,
    PropState,
    ReadinessContext,
    ReferenceBundle,
    ReferenceItem,
    ReferenceRole,
    Scene,
    SourceReference,
    World,
    action_keyframes,
    prepare_shot,
    provenance_chain,
)
from hevi.production_graph.adapters.tongjian import (
    chapter_characters,
    chapter_to_narrative,
    source_document_from_text,
)
from hevi.studio.slate_bridge import production_plan_to_slate
from hevi.tongjian.schemas import ChapterIR, ChapterMeta, CharacterIR, EventIR

GOLDEN = Path(__file__).parent / "golden"


def _chapter(data: dict) -> ChapterIR:
    return ChapterIR(
        meta=ChapterMeta(source=data["title"], char_count=len(data["source_text"])),
        characters=[CharacterIR.model_validate(item) for item in data["characters"]],
        events=[EventIR.model_validate(item) for item in data["events"]],
    )


def _compiler() -> ProviderCapabilities:
    return ProviderCapabilities(
        provider_id="gold-local",
        model="deterministic-cpu",
        supported_intents={GenerationIntent.IMAGE_TO_VIDEO, GenerationIntent.REMOTION},
        supported_reference_roles={
            ReferenceRole.CHARACTER_IDENTITY,
            ReferenceRole.CHARACTER_LOOK,
            ReferenceRole.LOCATION,
            ReferenceRole.PROP,
            ReferenceRole.STYLE,
            ReferenceRole.START_FRAME,
            ReferenceRole.PEAK_FRAME,
            ReferenceRole.END_FRAME,
            ReferenceRole.AUDIO,
        },
        max_duration_s=20,
        supported_resolutions={"720p"},
        default_resolution="720p",
        supports_audio=True,
    )


@pytest.mark.asyncio
async def test_gold_a_historical_source_to_slate_and_provenance(tmp_path: Path) -> None:
    data = json.loads((GOLDEN / "gold_a_historical.json").read_text())
    project = ProductionProject(id="gold-a", user_id="gold-user", title=data["title"])
    repo = ProductionGraphRepository()
    initial = await repo.create_project(project)
    document, chunk = source_document_from_text(
        project_id=project.id,
        revision_id=initial.revision.id,
        title=data["title"],
        text=data["source_text"],
    )
    chapter = _chapter(data)
    narrative = chapter_to_narrative(
        chapter,
        project_id=project.id,
        revision_id=initial.revision.id,
        source_document_id=document.id,
    )
    characters = chapter_characters(chapter, project_id=project.id, revision_id=initial.revision.id)
    episode = Episode(id="gold-a-episode", project_id=project.id, title="The gate")
    world = World(id="gold-a-world", project_id=project.id, name="Council world")
    location = Location(id="gold-a-gate", project_id=project.id, world_id=world.id, name="old gate")
    prop = Prop(id="gold-a-letter", project_id=project.id, name="sealed letter")
    look = LookVariant(
        id="gold-a-envoy-look",
        project_id=project.id,
        character_id=characters[0].id,
        name="dawn travel",
        costume="dark cloak",
        lifecycle="SELECTED",
    )
    scene = Scene(
        id="gold-a-scene",
        project_id=project.id,
        episode_id=episode.id,
        location_id=location.id,
        character_ids=[item.id for item in characters],
        prop_ids=[prop.id],
        narrative_event_ids=[item.id for item in narrative.events],
    )
    beat = Beat(
        id="gold-a-beat",
        project_id=project.id,
        scene_id=scene.id,
        action="The envoy crosses the gate with the sealed letter.",
        source_refs=[
            SourceReference(
                document_id=document.id, chunk_id=chunk.id, start_offset=56, end_offset=98
            )
        ],
    )
    shot = CanonicalShot(
        id="gold-a-shot",
        project_id=project.id,
        scene_id=scene.id,
        beat_ids=[beat.id],
        narrative_event_ids=[narrative.events[1].id],
        character_ids=[characters[0].id],
        location_id=location.id,
        prop_ids=[prop.id],
        camera=CameraSpec(shot_size="medium", movement="slow_push_in", azimuth_deg=90, lens_mm=50),
        action_description="The envoy crosses the old gate carrying the sealed letter.",
        cinematography_notes="Tense dawn push-in.",
        generation_intent=GenerationIntent.IMAGE_TO_VIDEO,
    )
    bundle = ReferenceBundle(
        id="gold-a-refs",
        project_id=project.id,
        shot_id=shot.id,
        items=[
            ReferenceItem(
                role=ReferenceRole.CHARACTER_IDENTITY,
                production_entity_id=characters[0].id,
                artifact_id="sha:envoy",
            ),
            ReferenceItem(
                role=ReferenceRole.CHARACTER_LOOK,
                production_entity_id=look.id,
                artifact_id="sha:look",
            ),
            ReferenceItem(
                role=ReferenceRole.LOCATION,
                production_entity_id=location.id,
                artifact_id="sha:gate",
            ),
            ReferenceItem(
                role=ReferenceRole.PROP, production_entity_id=prop.id, artifact_id="sha:letter"
            ),
            ReferenceItem(role=ReferenceRole.STYLE, artifact_id="sha:style"),
            ReferenceItem(role=ReferenceRole.AUDIO, artifact_id="sha:narration"),
        ],
    )
    shot = shot.model_copy(update={"reference_bundle_id": bundle.id})
    keyframes = action_keyframes(shot)
    shot = shot.model_copy(update={"keyframe_ids": [item.id for item in keyframes]})
    states = [
        CharacterState(
            id="gold-a-state",
            project_id=project.id,
            character_id=characters[0].id,
            scene_id=scene.id,
            location_id=location.id,
            look_variant_id=look.id,
            possessions=[prop.id],
        )
    ]
    location_state = LocationState(
        id="gold-a-location-state",
        project_id=project.id,
        location_id=location.id,
        scene_id=scene.id,
        time_of_day="dawn",
    )
    prop_state = PropState(
        id="gold-a-prop-state",
        project_id=project.id,
        prop_id=prop.id,
        scene_id=scene.id,
        owner_character_id=characters[0].id,
    )
    prepared, readiness = prepare_shot(
        shot,
        ReadinessContext(
            required_reference_roles={
                ReferenceRole.CHARACTER_IDENTITY,
                ReferenceRole.CHARACTER_LOOK,
                ReferenceRole.LOCATION,
                ReferenceRole.PROP,
            },
            available_reference_roles=bundle.roles(),
        ),
    )
    assert readiness.passed and prepared.readiness_state.value == "READY"
    plan = ProductionCompiler().compile(
        prepared,
        bundle,
        _compiler(),
        ResourceBudget(resolution="720p", resource_profile={"gpu": False}),
    )
    production_plan = ProductionPlan(
        id="gold-a-plan", project_id=project.id, revision_id=initial.revision.id, shot_ids=[shot.id]
    )
    adaptation_decision = AdaptationDecision(
        id="gold-a-adaptation",
        project_id=project.id,
        source_event_ids=[narrative.events[1].id],
        target_episode_id=episode.id,
        rationale="retain the turning point",
    )
    adaptation_plan = AdaptationPlan(
        id="gold-a-adaptation-plan",
        project_id=project.id,
        revision_id=initial.revision.id,
        source_event_ids=[narrative.events[1].id],
        decision_ids=[adaptation_decision.id],
        target_episode_ids=[episode.id],
    )
    director_session = DirectorSession(
        id="gold-a-director-session",
        project_id=project.id,
        current_revision_id=initial.revision.id,
        objective="make the turning point tense",
    )
    director_decision = DirectorDecision(
        id="gold-a-director-decision",
        revision_id=initial.revision.id,
        session_id=director_session.id,
        project_id=project.id,
        decision_type="shot_design",
        rationale="push in as the letter is revealed",
    )
    artifact_path = tmp_path / "gold-a-final-manifest.json"
    artifact_path.write_text('{"gold": "A"}', encoding="utf-8")
    artifact = Artifact.from_path(
        artifact_path,
        kind="production_manifest",
        primary=True,
        logical_role="final_artifact",
    ).model_copy(update={"artifact_id": "gold-a-artifact"})
    artifact_manifest = ArtifactManifest(
        production_id=project.id,
        revision_id=initial.revision.id,
        attempt_id="gold-a-attempt",
        artifacts=[artifact],
    )
    verified_artifact = verify_local_manifest(
        artifact_manifest, require_primary=True, require_video_stream=False
    ).artifacts[0]
    attempt = ExecutionAttempt(
        id="gold-a-attempt",
        project_id=project.id,
        revision_id=initial.revision.id,
        shot_id=shot.id,
        execution_plan_id=plan.id,
        status="succeeded",
        idempotency_key=plan.idempotency_key,
        artifact_ids=[verified_artifact.artifact_id or ""],
    )
    slate = production_plan_to_slate(production_plan, line_id="explainer")
    build_revision = ProductionRevision(
        id="gold-a-built-revision",
        project_id=project.id,
        parent_revision_id=initial.revision.id,
        revision_no=2,
        actor="golden",
        reason="historical golden production",
    )
    build_project = initial.project.model_copy(update={"current_revision_id": build_revision.id})
    snapshot = ProductionGraphSnapshot(
        project=build_project,
        revision=build_revision,
        sources=[document],
        source_chunks=[chunk],
        narrative=narrative,
        adaptation_plans=[adaptation_plan],
        adaptation_decisions=[adaptation_decision],
        characters=characters,
        character_states=states,
        look_variants=[look],
        worlds=[world],
        locations=[location],
        location_states=[location_state],
        props=[prop],
        prop_states=[prop_state],
        episodes=[episode],
        scenes=[scene],
        beats=[beat],
        shots=[prepared],
        keyframes=keyframes,
        reference_bundles=[bundle],
        continuity_constraints=[
            ContinuityConstraint(
                project_id=project.id, type="LOCATION", scope=shot.id, expected=location.id
            )
        ],
        readiness_results=[readiness],
        director_sessions=[director_session],
        director_decisions=[director_decision],
        production_plans=[production_plan.model_copy(update={"revision_id": build_revision.id})],
        execution_plans=[plan.model_copy(update={"revision_id": build_revision.id})],
        execution_attempts=[attempt],
        provenance_links=provenance_chain(
            project.id,
            [
                ("SourceDocument", document.id),
                ("NarrativeEvent", narrative.events[1].id),
                ("AdaptationDecision", adaptation_decision.id),
                ("Scene", scene.id),
                ("Shot", prepared.id),
                ("DirectorDecision", director_decision.id),
                ("ReferenceBundle", bundle.id),
                ("ExecutionPlan", plan.id),
                ("ExecutionAttempt", attempt.id),
                ("Artifact", verified_artifact.artifact_id or ""),
            ],
        ),
    )
    snapshot.validate_referential_integrity()
    await repo.save_snapshot(snapshot)
    reopened = await repo.get_snapshot(project.id)
    assert reopened is not None
    assert reopened.execution_attempts[0].artifact_ids == ["gold-a-artifact"]
    assert [link.target_type for link in snapshot.provenance_links][-1] == "Artifact"
    assert verified_artifact.integrity_ok()
    assert plan.shot_revision_id == prepared.revision_id
    assert slate.slots["canonical_shot_ids"] == [shot.id]


def test_gold_b_long_form_cross_episode_identity_and_state() -> None:
    data = json.loads((GOLDEN / "gold_b_novel.json").read_text())
    project = ProductionProject(id="gold-b", user_id="gold-user", title=data["title"])
    from hevi.production_graph import ProductionRevision

    revision = ProductionRevision(id="gold-b-revision", project_id=project.id)
    project = project.model_copy(update={"current_revision_id": revision.id})
    chapters = [
        ChapterIR(
            meta=ChapterMeta(source=item["source"]),
            characters=[
                CharacterIR(character_id="hero", canonical_name="Hero") for _ in item["characters"]
            ],
            events=[
                EventIR(
                    event_id=event["id"],
                    summary=event["summary"],
                    actors=["hero"],
                    source_span=tuple(event["span"]),
                )
                for event in item["events"]
            ],
        )
        for item in data["chapters"]
    ]
    graphs = [
        chapter_to_narrative(
            chapter,
            project_id=project.id,
            revision_id=revision.id,
            source_document_id=f"doc-{index}",
        )
        for index, chapter in enumerate(chapters)
    ]
    hero_ids = [
        chapter_characters(chapter, project_id=project.id, revision_id=revision.id)[0].id
        for chapter in chapters
    ]
    assert hero_ids[0] == hero_ids[1]
    look_one = LookVariant(
        id="gold-b-look-one",
        project_id=project.id,
        character_id=hero_ids[0],
        name="arrival",
        costume="clean",
    )
    look_two = LookVariant(
        id="gold-b-look-two",
        project_id=project.id,
        character_id=hero_ids[0],
        name="return",
        costume="damaged",
    )
    episode_one = Episode(id="gold-b-ep-one", project_id=project.id, number=1)
    episode_two = Episode(id="gold-b-ep-two", project_id=project.id, number=2)
    scene_one = Scene(
        id="gold-b-scene-one",
        project_id=project.id,
        episode_id=episode_one.id,
        character_ids=[hero_ids[0]],
    )
    scene_two = Scene(
        id="gold-b-scene-two",
        project_id=project.id,
        episode_id=episode_two.id,
        character_ids=[hero_ids[0]],
    )
    states = [
        CharacterState(
            id="gold-b-state-one",
            project_id=project.id,
            character_id=hero_ids[0],
            scene_id=scene_one.id,
            look_variant_id=look_one.id,
        ),
        CharacterState(
            id="gold-b-state-two",
            project_id=project.id,
            character_id=hero_ids[0],
            scene_id=scene_two.id,
            look_variant_id=look_two.id,
        ),
    ]
    thread = PlotThread(
        id="gold-b-thread",
        project_id=project.id,
        title="Identity arc",
        introduced_event_id=graphs[0].events[0].id,
        resolution_event_id=graphs[1].events[0].id,
    )
    assert states[0].look_variant_id != states[1].look_variant_id
    assert thread.introduced_event_id != thread.resolution_event_id
    assert graphs[0].events[0].source_refs[0].document_id == "doc-0"
    assert graphs[1].events[0].source_refs[0].document_id == "doc-1"


def test_gold_c_one_prompt_compiles_without_gpu_dependency() -> None:
    data = json.loads((GOLDEN / "gold_c_one_prompt.json").read_text())
    project = ProductionProject(
        id="gold-c",
        user_id="gold-user",
        title=data["title"],
        creative_brief=data["creative_brief"],
        target_duration=data["target_duration"],
        aspect_ratio=data["aspect_ratio"],
        production_mode=ProductionMode.AUTO,
    )
    episode = Episode(id="gold-c-episode", project_id=project.id)
    scene = Scene(id="gold-c-scene", project_id=project.id, episode_id=episode.id)
    beat = Beat(
        id="gold-c-beat", project_id=project.id, scene_id=scene.id, action=data["creative_brief"]
    )
    shot = CanonicalShot(
        id="gold-c-shot",
        project_id=project.id,
        scene_id=scene.id,
        beat_ids=[beat.id],
        action_description=data["creative_brief"],
        generation_intent=GenerationIntent.REMOTION,
    )
    bundle = ReferenceBundle(id="gold-c-refs", project_id=project.id, shot_id=shot.id)
    shot, readiness = prepare_shot(shot, ReadinessContext())
    assert readiness.passed
    plan = ProductionCompiler().compile(
        shot, bundle, _compiler(), ResourceBudget(resources_available=True)
    )
    assert plan.capability == GenerationIntent.REMOTION.value
    assert plan.resource_profile.get("gpu") is None
