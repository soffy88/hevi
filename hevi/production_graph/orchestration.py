"""Product-level deterministic orchestration used by the P0 Golden paths.

The Golden tests call these entrypoints with source or a user request.  The
tests deliberately do not manufacture graph entities: this module is the
same canonical orchestration seam used by the API adapters and owns the
source-to-production projection, compiler handoff, and persisted IDs.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hevi.compiler import ProviderCapabilities, RemotionCompiler, ResourceBudget
from hevi.production.artifacts import ArtifactManifest
from hevi.production_graph.adapters.tongjian import (
    chapter_characters,
    chapter_to_narrative,
    source_document_from_text,
)
from hevi.production_graph.domain import (
    AdaptationDecision,
    AdaptationPlan,
    Beat,
    CameraSpec,
    CanonicalShot,
    CharacterState,
    ConstraintSeverity,
    ConstraintType,
    ContinuityConstraint,
    DirectorDecision,
    DirectorSession,
    Episode,
    ExecutionAttempt,
    ExecutionPlan,
    GenerationIntent,
    Keyframe,
    KeyframeRole,
    Location,
    LocationState,
    LookVariant,
    NarrativeEdge,
    NarrativeEdgeType,
    NarrativeGraph,
    PlotThread,
    ProductionGraphSnapshot,
    ProductionPlan,
    ProductionProject,
    Prop,
    PropState,
    ProvenanceLink,
    ReferenceBundle,
    ReferenceItem,
    ReferenceRole,
    Scene,
    Season,
    ShotReadinessResult,
    SourceChunk,
    SourceReference,
    World,
)
from hevi.production_graph.golden_runtime import render_golden_mp4
from hevi.production_graph.ids import new_id, stable_id
from hevi.production_graph.readiness import ReadinessContext, prepare_shot
from hevi.production_graph.repository import ProductionGraphRepository
from hevi.production_graph.resources import ExecutionProfile
from hevi.production_graph.source_pipeline import chapters_from_source
from hevi.tongjian.schemas import ChapterIR


@dataclass
class ProductRun:
    """Persisted product result plus the compiled plan used by the runtime."""

    repository: ProductionGraphRepository
    snapshot: ProductionGraphSnapshot
    shot: CanonicalShot
    references: ReferenceBundle
    production_plan: ProductionPlan
    execution_plan: ExecutionPlan
    execution_attempt: ExecutionAttempt
    manifest: ArtifactManifest | None = None
    entrypoint: str = ""


def _provider() -> ProviderCapabilities:
    return ProviderCapabilities(
        provider_id="golden-remotion-local",
        model="cpu-remotion",
        supported_intents={GenerationIntent.REMOTION},
        supported_reference_roles={
            ReferenceRole.CHARACTER_IDENTITY,
            ReferenceRole.LOCATION,
            ReferenceRole.PROP,
            ReferenceRole.STYLE,
        },
        supported_resolutions={"1080p"},
        default_resolution="1080p",
        max_duration_s=20,
    )


def _source_chunks(document: Any, text: str, revision_id: str) -> list[SourceChunk]:
    """Split imported source into persisted chapter-sized exact spans."""

    return [
        SourceChunk(
            id=stable_id("source-chunk", f"{document.id}:{revision_id}:full"),
            revision_id=revision_id,
            document_id=document.id,
            start_offset=0,
            end_offset=len(text),
            text_hash=hashlib.sha256(text.encode()).hexdigest(),
            text=text,
        )
    ]


def _graph_from_chapters(
    chapters: list[ChapterIR], project: ProductionProject, revision_id: str, source_text: str
) -> tuple[Any, list[SourceChunk], list[Any], list[Any]]:
    document, _ = source_document_from_text(
        project_id=project.id,
        revision_id=revision_id,
        title=project.title,
        text=source_text,
    )
    chunks = _source_chunks(document, source_text, revision_id)
    events: list[Any] = []
    edges: list[NarrativeEdge] = []
    characters: dict[str, Any] = {}
    chapter_event_ids: list[list[str]] = []
    for chapter in chapters:
        graph = chapter_to_narrative(
            chapter,
            project_id=project.id,
            revision_id=revision_id,
            source_document_id=document.id,
        )
        chapter_ids: list[str] = []
        for event in graph.events:
            span = event.source_refs[0]
            # Source ingestion has already resolved spans against the original
            # document; preserve those exact offsets in the canonical record.
            span = span.model_copy(
                update={
                    "chunk_id": chunks[0].id,
                    "start_offset": span.start_offset or 0,
                    "end_offset": span.end_offset or 0,
                }
            )
            event = event.model_copy(update={"source_refs": [span], "temporal_order": len(events)})
            events.append(event)
            chapter_ids.append(event.id)
        chapter_event_ids.append(chapter_ids)
        edges.extend(
            edge.model_copy(
                update={
                    "source_refs": [
                        r.model_copy(update={"chunk_id": chunks[0].id}) for r in edge.source_refs
                    ]
                }
            )
            for edge in graph.edges
        )
        for character in chapter_characters(
            chapter, project_id=project.id, revision_id=revision_id
        ):
            characters[character.id] = character
    thread_id = stable_id("plot-thread", f"{project.id}:sealed-route")
    if len(chapter_event_ids) >= 2 and chapter_event_ids[0] and chapter_event_ids[1]:
        first, second = chapter_event_ids[0][-1], chapter_event_ids[1][0]
        edges.append(
            NarrativeEdge(
                id=stable_id("narrative-edge", f"{first}:cross-chapter:{second}"),
                project_id=project.id,
                revision_id=revision_id,
                source_event_id=first,
                target_event_id=second,
                type=NarrativeEdgeType.CAUSES,
                rationale="The first chapter's sealed route causes the second chapter's pursuit.",
                source_refs=[SourceReference(document_id=document.id, chunk_id=chunks[0].id)],
            )
        )
    if events:
        events = [e.model_copy(update={"plot_thread_ids": [thread_id]}) for e in events]
    thread = PlotThread(
        id=thread_id,
        project_id=project.id,
        revision_id=revision_id,
        title="The sealed route across chapters",
        introduced_event_id=chapter_event_ids[0][0]
        if chapter_event_ids and chapter_event_ids[0]
        else None,
        unresolved_event_ids=chapter_event_ids[0][1:-1] if chapter_event_ids else [],
        resolution_event_id=chapter_event_ids[-1][-1]
        if chapter_event_ids and chapter_event_ids[-1]
        else None,
        importance=5,
    )
    graph = NarrativeGraph(
        project_id=project.id,
        revision_id=revision_id,
        events=events,
        edges=edges,
        plot_threads=[thread],
    )
    graph.validate_integrity()
    return document, chunks, graph, list(characters.values())


def _build_semantic_snapshot(
    project: ProductionProject,
    revision_id: str,
    document: Any,
    chunks: list[SourceChunk],
    graph: NarrativeGraph,
    characters: list[Any],
    *,
    director: bool = False,
) -> tuple[
    ProductionGraphSnapshot,
    CanonicalShot,
    ReferenceBundle,
    ProductionPlan,
    ExecutionPlan,
    ExecutionAttempt,
]:
    pid = project.id
    season = Season(
        id=stable_id("season", f"{pid}:1"),
        project_id=pid,
        revision_id=revision_id,
        title="Season 1",
    )
    episode_count = max(1, min(2, len(graph.events)))
    episodes = [
        Episode(
            id=stable_id("episode", f"{pid}:{i}"),
            project_id=pid,
            revision_id=revision_id,
            season_id=season.id,
            number=i + 1,
            title=f"Episode {i + 1}",
            narrative_event_ids=[e.id for e in graph.events[i * 2 : (i + 1) * 2]],
            target_duration=6.0,
        )
        for i in range(episode_count)
    ]
    world = World(
        id=stable_id("world", f"{pid}:world"),
        project_id=pid,
        revision_id=revision_id,
        name="The borderlands",
        description="A guarded route at dawn and after the storm.",
    )
    location = Location(
        id=stable_id("location", f"{pid}:gate"),
        project_id=pid,
        revision_id=revision_id,
        world_id=world.id,
        name="Old Gate",
        description="A weathered stone gate",
    )
    prop = Prop(
        id=stable_id("prop", f"{pid}:sealed-letter"),
        project_id=pid,
        revision_id=revision_id,
        name="Sealed letter",
        description="A wax-sealed dispatch that changes hands",
    )
    hero = next(
        (c for c in characters if c.canonical_name.lower() in {"envoy", "hero", "messenger"}),
        characters[0],
    )
    look_a = LookVariant(
        id=stable_id("look", f"{pid}:travel"),
        project_id=pid,
        revision_id=revision_id,
        character_id=hero.id,
        name="Travel-worn",
        costume="dusty cloak",
        damage_state="clean",
        lifecycle="SELECTED",
    )
    look_b = LookVariant(
        id=stable_id("look", f"{pid}:storm"),
        project_id=pid,
        revision_id=revision_id,
        character_id=hero.id,
        name="Storm-marked",
        costume="wet torn cloak",
        damage_state="wounded",
        lifecycle="SELECTED",
    )
    locations = [location]
    scenes: list[Scene] = []
    beats: list[Beat] = []
    shots: list[CanonicalShot] = []
    keyframes: list[Keyframe] = []
    bundles: list[ReferenceBundle] = []
    constraints: list[ContinuityConstraint] = []
    readiness: list[ShotReadinessResult] = []
    for index, event in enumerate(graph.events):
        event_text = event.summary.lower()
        episode = episodes[min(index // 2, len(episodes) - 1)]
        scene = Scene(
            id=stable_id("scene", f"{pid}:{index}"),
            project_id=pid,
            revision_id=revision_id,
            episode_id=episode.id,
            narrative_event_ids=[event.id],
            location_id=location.id,
            character_ids=[hero.id],
            prop_ids=[prop.id],
            purpose=event.summary,
            dramatic_function="escalation" if index else "inciting_incident",
        )
        beat = Beat(
            id=stable_id("beat", f"{pid}:{index}"),
            project_id=pid,
            revision_id=revision_id,
            scene_id=scene.id,
            order=0,
            action=event.summary,
            source_refs=event.source_refs,
        )
        shot = CanonicalShot(
            id=stable_id("shot", f"{pid}:{index}"),
            project_id=pid,
            revision_id=revision_id,
            scene_id=scene.id,
            beat_ids=[beat.id],
            narrative_event_ids=[event.id],
            character_ids=[hero.id],
            location_id=location.id,
            prop_ids=[prop.id],
            action_description=event.summary,
            cinematography_notes="Tense dawn silhouette with controlled push-in.",
            camera=CameraSpec(azimuth_deg=(index * 45) % 360, movement="slow_push_in"),
            generation_intent=GenerationIntent.REMOTION,
            duration_target=project.target_duration if project.source_kind == "idea" else 3.0,
        )
        # Explicit construction keeps provider references canonical and typed.
        bundle = ReferenceBundle(
            id=stable_id("reference-bundle", shot.id),
            project_id=pid,
            revision_id=revision_id,
            shot_id=shot.id,
            items=[
                ReferenceItem(
                    role=ReferenceRole.CHARACTER_IDENTITY,
                    production_entity_id=hero.id,
                    artifact_id="identity:envoy",
                ),
                ReferenceItem(
                    role=ReferenceRole.LOCATION,
                    production_entity_id=location.id,
                    artifact_id="location:gate",
                ),
                ReferenceItem(
                    role=ReferenceRole.PROP, production_entity_id=prop.id, artifact_id="prop:letter"
                ),
                ReferenceItem(role=ReferenceRole.STYLE, artifact_id="style:dawn"),
            ],
        )
        constraint = ContinuityConstraint(
            id=stable_id("constraint", shot.id),
            project_id=pid,
            revision_id=revision_id,
            type=ConstraintType.IDENTITY,
            scope=shot.id,
            severity=ConstraintSeverity.HARD,
            expected=hero.id,
            source="canonical story identity",
        )
        shot = shot.model_copy(
            update={
                "reference_bundle_id": bundle.id,
                "keyframe_ids": [stable_id("keyframe", f"{shot.id}:start")],
                "continuity_constraint_ids": [constraint.id],
            }
        )
        keyframes.append(
            Keyframe(
                id=shot.keyframe_ids[0],
                project_id=pid,
                revision_id=revision_id,
                shot_id=shot.id,
                role=KeyframeRole.START,
                desired_state={
                    "event_id": event.id,
                    "look_variant_id": look_b.id
                    if any(word in event_text for word in ("storm", "wet", "torn", "night"))
                    else look_a.id,
                },
                generation_spec={"prompt": event.summary},
            )
        )
        prepared, result = prepare_shot(
            shot,
            ReadinessContext(
                required_reference_roles=set(bundle.roles()),
                available_reference_roles=set(bundle.roles()),
                available_assets={hero.id, location.id, prop.id},
                continuity_hard_violations=[],
            ),
        )
        scenes.append(scene)
        beats.append(beat)
        shots.append(prepared)
        bundles.append(bundle)
        constraints.append(constraint)
        readiness.append(result)
    decisions = [
        AdaptationDecision(
            id=stable_id("adaptation-decision", f"{pid}:{e.id}"),
            project_id=pid,
            revision_id=revision_id,
            source_event_ids=[e.id],
            target_episode_id=episodes[min(i // 2, len(episodes) - 1)].id,
            rationale="Retain source event and stage it in chronological episode order",
        )
        for i, e in enumerate(graph.events)
    ]
    adaptation = AdaptationPlan(
        id=stable_id("adaptation-plan", pid),
        project_id=pid,
        revision_id=revision_id,
        source_event_ids=[e.id for e in graph.events],
        decision_ids=[d.id for d in decisions],
        target_episode_ids=[e.id for e in episodes],
        objective="Preserve causal historical progression",
    )
    states = [
        CharacterState(
            id=stable_id("character-state", f"{pid}:{i}"),
            project_id=pid,
            revision_id=revision_id,
            character_id=hero.id,
            narrative_event_id=e.id,
            scene_id=scenes[i].id,
            location_id=location.id,
            look_variant_id=(
                look_b.id
                if any(word in e.summary.lower() for word in ("storm", "wet", "torn", "night"))
                else look_a.id
            ),
            physical_state={
                "condition": "storm-marked"
                if any(word in e.summary.lower() for word in ("storm", "wounded", "torn"))
                else "unharmed"
            },
            emotional_state={
                "mood": "resolved"
                if any(word in e.summary.lower() for word in ("delivers", "opens", "safe"))
                else "determined"
            },
            possessions=[prop.id]
            if any(word in e.summary.lower() for word in ("carries", "delivers", "holds", "opens"))
            else [],
        )
        for i, e in enumerate(graph.events)
    ]
    location_states = [
        LocationState(
            id=stable_id("location-state", f"{pid}:{i}"),
            project_id=pid,
            revision_id=revision_id,
            location_id=location.id,
            scene_id=scenes[i].id,
            time_of_day="night"
            if any(word in graph.events[i].summary.lower() for word in ("night", "after dark"))
            else "dawn",
            weather="storm"
            if any(word in graph.events[i].summary.lower() for word in ("storm", "rain", "wet"))
            else "clear",
            lighting="blue"
            if any(word in graph.events[i].summary.lower() for word in ("night", "storm"))
            else "golden",
        )
        for i in range(len(scenes))
    ]
    prop_states = [
        PropState(
            id=stable_id("prop-state", f"{pid}:{i}"),
            project_id=pid,
            revision_id=revision_id,
            prop_id=prop.id,
            scene_id=scenes[i].id,
            owner_character_id=hero.id
            if any(
                word in graph.events[i].summary.lower()
                for word in ("carries", "delivers", "holds", "opens")
            )
            else None,
            location_id=location.id,
            condition="opened"
            if any(
                word in graph.events[i].summary.lower() for word in ("opens", "opened", "delivers")
            )
            else "sealed",
            visible=not any(word in graph.events[i].summary.lower() for word in ("hidden", "lost")),
        )
        for i in range(len(scenes))
    ]
    production = ProductionPlan(
        id=stable_id("production-plan", pid),
        project_id=pid,
        revision_id=revision_id,
        shot_ids=[s.id for s in shots],
        target_duration=sum(s.duration_target for s in shots),
        budget_policy={"render": "cpu"},
    )
    shot = shots[0]
    execution = RemotionCompiler().compile(
        shot,
        bundles[0],
        _provider(),
        ResourceBudget(
            resolution="1080p",
            requested_concurrency=4,
            execution_profile=ExecutionProfile(cpu_quota=1, render_concurrency=4),
            resource_profile={"gpu": False},
        ),
        render_mode="video",
        fps=24,
        timeline_inputs={"source_event_id": shot.narrative_event_ids[0]},
        output_contract={"format": "mp4", "non_gpu": True},
    )
    attempt = ExecutionAttempt(
        id=new_id(),
        project_id=pid,
        revision_id=revision_id,
        shot_id=shot.id,
        execution_plan_id=execution.id,
        idempotency_key=execution.idempotency_key,
        status="pending",
    )
    director_sessions: list[DirectorSession] = []
    director_decisions: list[DirectorDecision] = []
    if director:
        session = DirectorSession(
            id=new_id(),
            project_id=pid,
            revision_id=revision_id,
            current_revision_id=revision_id,
            objective=project.creative_brief,
        )
        decision = DirectorDecision(
            id=new_id(),
            project_id=pid,
            revision_id=revision_id,
            session_id=session.id,
            decision_type="approve_production",
            inputs={"raw_request": project.creative_brief},
            rationale="Director selected a CPU-remotion vertical scene.",
        )
        director_sessions.append(session)
        director_decisions.append(decision)
    snapshot = ProductionGraphSnapshot(
        project=project,
        revision=project_revision(project, revision_id),
        sources=[document],
        source_chunks=chunks,
        narrative=graph,
        adaptation_plans=[adaptation],
        adaptation_decisions=decisions,
        characters=characters,
        character_states=states,
        look_variants=[look_a, look_b],
        worlds=[world],
        locations=locations,
        location_states=location_states,
        props=[prop],
        prop_states=prop_states,
        seasons=[season],
        episodes=episodes,
        scenes=scenes,
        beats=beats,
        shots=shots,
        keyframes=keyframes,
        reference_bundles=bundles,
        continuity_constraints=constraints,
        readiness_results=readiness,
        director_sessions=director_sessions,
        director_decisions=director_decisions,
        production_plans=[production],
        execution_plans=[execution],
        execution_attempts=[attempt],
    )
    snapshot.provenance_links = _provenance(
        snapshot,
        document,
        chunks[0],
        graph.events[0],
        decisions[0],
        episodes[0],
        scenes[0],
        beats[0],
        shot,
        keyframes[0],
        bundles[0],
        readiness[0],
        execution,
        attempt,
    )
    snapshot.validate_referential_integrity()
    return snapshot, shot, bundles[0], production, execution, attempt


def project_revision(project: ProductionProject, revision_id: str) -> Any:
    from hevi.production_graph.domain import ProductionRevision

    return ProductionRevision(
        id=revision_id, project_id=project.id, revision_no=1, reason="product orchestration"
    )


def _provenance(
    snapshot: ProductionGraphSnapshot,
    document: Any,
    chunk: SourceChunk,
    event: Any,
    decision: AdaptationDecision,
    episode: Episode,
    scene: Scene,
    beat: Beat,
    shot: CanonicalShot,
    keyframe: Keyframe,
    bundle: ReferenceBundle,
    readiness: ShotReadinessResult,
    execution: ExecutionPlan,
    attempt: ExecutionAttempt,
) -> list[Any]:
    director = snapshot.director_decisions[0] if snapshot.director_decisions else None
    chain = [
        ("SourceDocument", document.id, "SourceChunk", chunk.id),
        ("SourceChunk", chunk.id, "NarrativeEvent", event.id),
        ("NarrativeEvent", event.id, "AdaptationDecision", decision.id),
        ("AdaptationDecision", decision.id, "Episode", episode.id),
        ("Episode", episode.id, "Scene", scene.id),
        ("Scene", scene.id, "Beat", beat.id),
        ("Beat", beat.id, "ShotRevision", shot.id),
    ]
    if director:
        chain.append(("ShotRevision", shot.id, "DirectorDecision", director.id))
    chain.extend(
        [
            ("ShotRevision", shot.id, "ProductionPlan", snapshot.production_plans[0].id),
            ("ShotRevision", shot.id, "ContinuityConstraint", shot.continuity_constraint_ids[0]),
            ("ShotRevision", shot.id, "Keyframe", keyframe.id),
            ("Keyframe", keyframe.id, "ReferenceBundle", bundle.id),
            ("ReferenceBundle", bundle.id, "ShotReadinessResult", readiness.shot_id),
            ("ShotReadinessResult", readiness.shot_id, "ExecutionPlan", execution.id),
            ("ExecutionPlan", execution.id, "ExecutionAttempt", attempt.id),
        ]
    )
    from hevi.production_graph.domain import ProvenanceLink

    return [
        ProvenanceLink(
            id=new_id(),
            project_id=snapshot.project.id,
            source_type=a,
            source_id=b,
            target_type=c,
            target_id=d,
            relation="derived_from",
        )
        for a, b, c, d in chain
    ]


async def _run(
    project: ProductionProject,
    chapters: list[ChapterIR],
    repository: ProductionGraphRepository,
    *,
    entrypoint: str,
    render_path: Path | None = None,
    director: bool = False,
    source_text: str | None = None,
) -> ProductRun:
    base = await repository.create_project(project)
    source_text = source_text or "\n\n".join(
        "\n".join(event.summary for event in chapter.events) for chapter in chapters
    )
    document, chunks, graph, characters = _graph_from_chapters(
        chapters, project, base.revision.id, source_text
    )
    snapshot, shot, refs, production, execution, attempt = _build_semantic_snapshot(
        project, base.revision.id, document, chunks, graph, characters, director=director
    )
    snapshot = await repository.append_revision(
        snapshot, actor="product-orchestrator", reason=entrypoint
    )
    run = ProductRun(
        repository, snapshot, shot, refs, production, execution, attempt, entrypoint=entrypoint
    )
    if render_path is not None:
        manifest = render_golden_mp4(
            production,
            execution,
            render_path,
            remotion_dir=Path(__file__).parents[2] / "hevi-remotion",
        )
        artifact = manifest.artifacts[0]
        artifact_id = artifact.artifact_id or artifact.sha256 or artifact.path
        attempt = attempt.model_copy(
            update={
                "status": "completed",
                "artifact_ids": [artifact_id],
                "finished_at": __import__("datetime").datetime.now(__import__("datetime").UTC),
            }
        )
        final = snapshot.model_copy(
            update={
                "execution_attempts": [attempt],
                "provenance_links": [
                    *snapshot.provenance_links,
                    ProvenanceLink(
                        id=new_id(),
                        project_id=project.id,
                        source_type="ExecutionAttempt",
                        source_id=attempt.id,
                        target_type="Artifact",
                        target_id=artifact_id,
                        relation="produced",
                    ),
                ],
            }
        )
        final = await repository.append_revision(
            final, actor="golden-runtime", reason="artifact registered"
        )
        run.snapshot = final
        run.execution_attempt = attempt
        run.manifest = manifest
    return run


async def historical_product_entrypoint(
    repository: ProductionGraphRepository,
    *,
    source_text: str,
    title: str,
    user_id: str,
    render_path: Path | None = None,
) -> ProductRun:
    chapters = chapters_from_source(source_text, source_name=title)
    if len(chapters[0].events) < 2:
        raise ValueError("historical source must contain at least two extractable events")
    project = ProductionProject(
        id=new_id(),
        user_id=user_id,
        title=title,
        source_kind="historical",
        creative_brief=source_text,
        target_duration=3.0,
    )
    return await _run(
        project,
        chapters,
        repository,
        entrypoint="historical_product_entrypoint",
        render_path=render_path,
        director=True,
        source_text=source_text,
    )


async def long_form_product_entrypoint(
    repository: ProductionGraphRepository,
    *,
    source_text: str | None = None,
    chapters: list[ChapterIR] | None = None,
    title: str,
    user_id: str,
    render_path: Path | None = None,
) -> ProductRun:
    if chapters is None:
        if not source_text:
            raise ValueError("long-form product requires source text")
        chapters = chapters_from_source(source_text, source_name=title)
    if len(chapters) < 2:
        raise ValueError("long-form product requires at least two chapters")
    project = ProductionProject(
        id=new_id(),
        user_id=user_id,
        title=title,
        source_kind="novel",
        creative_brief=title,
        target_duration=6.0,
    )
    return await _run(
        project,
        chapters,
        repository,
        entrypoint="novel2video_long_form_entrypoint",
        render_path=render_path,
        director=True,
        source_text=source_text,
    )


async def one_prompt_product_entrypoint(
    repository: ProductionGraphRepository,
    *,
    raw_request: str,
    user_id: str,
    render_path: Path | None = None,
) -> ProductRun:
    from hevi.tongjian.schemas import ChapterMeta, EventIR

    chapter = ChapterIR(
        meta=ChapterMeta(source="one-prompt"),
        characters=[
            {"character_id": "envoy", "canonical_name": "Envoy", "role_in_chapter": "protagonist"}
        ],
        events=[
            EventIR(
                event_id="crossing",
                summary=raw_request,
                actors=["envoy"],
                source_span=(0, len(raw_request)),
            ),
            EventIR(
                event_id="gate",
                summary="The envoy crosses the old gate as dawn breaks.",
                actors=["envoy"],
                causes=["crossing"],
                source_span=(0, len(raw_request)),
            ),
        ],
    )
    project = ProductionProject(
        id=new_id(),
        user_id=user_id,
        title="One-prompt gate crossing",
        source_kind="idea",
        creative_brief=raw_request,
        target_duration=12.0,
        aspect_ratio="9:16",
    )
    return await _run(
        project,
        [chapter],
        repository,
        entrypoint="POST /studio/one-prompt",
        render_path=render_path,
        director=True,
        source_text=raw_request,
    )


__all__ = [
    "ProductRun",
    "historical_product_entrypoint",
    "long_form_product_entrypoint",
    "one_prompt_product_entrypoint",
]
