"""Canonical, provider-independent Film Production Domain.

This module is the semantic owner for P0.  Legacy Tongjian, Script2Video and
Cinematic models are deliberately not imported here: adapters translate them
into these records and retain their source identifiers in provenance.  Binary
assets are referenced by ArtifactStore/Vault IDs and are never copied here.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .ids import CanonicalId, new_id


def _now() -> datetime:
    return datetime.now(UTC)


class DomainModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Entity(DomainModel):
    id: CanonicalId = Field(default_factory=new_id, min_length=1)
    revision_id: CanonicalId | None = None


class ProductionMode(StrEnum):
    AUTO = "AUTO"
    KEYFRAME_REVIEW = "KEYFRAME_REVIEW"
    SHOT_REVIEW = "SHOT_REVIEW"
    MANUAL_DIRECTOR = "MANUAL_DIRECTOR"


class ProjectStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"


class ProductionProject(Entity):
    user_id: str
    title: str = "Untitled production"
    source_kind: str = "idea"
    creative_brief: str = ""
    target_platform: str = ""
    aspect_ratio: str = "9:16"
    target_duration: float | None = Field(default=None, ge=0)
    visual_style: str = ""
    language: str = "zh-CN"
    budget_policy: dict[str, Any] = Field(default_factory=dict)
    production_mode: ProductionMode = ProductionMode.AUTO
    current_revision_id: CanonicalId | None = None
    status: ProjectStatus = ProjectStatus.DRAFT
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class ProductionRevision(Entity):
    project_id: CanonicalId
    parent_revision_id: CanonicalId | None = None
    revision_no: int = Field(default=1, ge=1)
    actor: str = "system"
    reason: str = "created"
    snapshot_hash: str = ""
    created_at: datetime = Field(default_factory=_now)
    locked: bool = False

    def with_snapshot_hash(self, snapshot: Any) -> ProductionRevision:
        value = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, default=str)
        return self.model_copy(update={"snapshot_hash": hashlib.sha256(value.encode()).hexdigest()})


class SourceKind(StrEnum):
    IDEA = "idea"
    SCRIPT = "script"
    NOVEL = "novel"
    HISTORICAL = "historical"
    REFERENCE = "reference"


class SourceDocument(Entity):
    project_id: CanonicalId
    kind: str = SourceKind.IDEA
    title: str = ""
    content_hash: str
    raw_artifact_id: str | None = None
    provenance: dict[str, Any] = Field(default_factory=dict)


class SourceChunk(Entity):
    document_id: CanonicalId
    start_offset: int = Field(ge=0)
    end_offset: int = Field(ge=0)
    text_hash: str
    text: str = ""

    @field_validator("end_offset")
    @classmethod
    def end_after_start(cls, value: int, info: Any) -> int:
        start = info.data.get("start_offset")
        if start is not None and value < start:
            raise ValueError("source chunk end_offset must be >= start_offset")
        return value


class NarrativeEdgeType(StrEnum):
    CAUSES = "CAUSES"
    ENABLES = "ENABLES"
    CONFLICTS_WITH = "CONFLICTS_WITH"
    RESOLVES = "RESOLVES"
    FORESHADOWS = "FORESHADOWS"
    PARALLELS = "PARALLELS"
    PRECEDES = "PRECEDES"


class SourceReference(DomainModel):
    document_id: CanonicalId
    chunk_id: CanonicalId | None = None
    start_offset: int | None = Field(default=None, ge=0)
    end_offset: int | None = Field(default=None, ge=0)
    quote: str = ""


class NarrativeEvent(Entity):
    project_id: CanonicalId
    source_refs: list[SourceReference] = Field(default_factory=list)
    summary: str
    temporal_order: int = 0
    character_ids: list[CanonicalId] = Field(default_factory=list)
    location_id: CanonicalId | None = None
    causes: list[CanonicalId] = Field(default_factory=list)
    effects: list[CanonicalId] = Field(default_factory=list)
    dramatic_weight: int = Field(default=3, ge=1, le=5)
    plot_thread_ids: list[CanonicalId] = Field(default_factory=list)
    status: str = "active"
    legacy_ids: dict[str, str] = Field(default_factory=dict)


class NarrativeEdge(Entity):
    project_id: CanonicalId
    source_event_id: CanonicalId
    target_event_id: CanonicalId
    type: NarrativeEdgeType
    rationale: str = ""
    source_refs: list[SourceReference] = Field(default_factory=list)


class PlotThread(Entity):
    project_id: CanonicalId
    title: str
    introduced_event_id: CanonicalId | None = None
    unresolved_event_ids: list[CanonicalId] = Field(default_factory=list)
    resolution_event_id: CanonicalId | None = None
    importance: int = Field(default=3, ge=1, le=5)


class AdaptationDecision(Entity):
    """Traceable decision mapping source events into production episodes."""

    project_id: CanonicalId
    source_event_ids: list[CanonicalId] = Field(default_factory=list)
    action: Literal["RETAIN", "MERGE", "OMIT", "REORDER"] = "RETAIN"
    target_episode_id: CanonicalId | None = None
    rationale: str = ""


class AdaptationPlan(Entity):
    project_id: CanonicalId
    source_event_ids: list[CanonicalId] = Field(default_factory=list)
    decision_ids: list[CanonicalId] = Field(default_factory=list)
    target_episode_ids: list[CanonicalId] = Field(default_factory=list)
    target_duration: float | None = Field(default=None, ge=0)
    objective: str = ""


class NarrativeGraph(DomainModel):
    project_id: CanonicalId
    revision_id: CanonicalId
    events: list[NarrativeEvent] = Field(default_factory=list)
    edges: list[NarrativeEdge] = Field(default_factory=list)
    plot_threads: list[PlotThread] = Field(default_factory=list)

    def validate_integrity(self) -> None:
        event_ids = {event.id for event in self.events}
        thread_ids = {thread.id for thread in self.plot_threads}
        for event in self.events:
            if any(ref.document_id == "" for ref in event.source_refs):
                raise ValueError(f"event {event.id} contains an empty source reference")
            missing = set(event.causes + event.effects) - event_ids
            if missing:
                raise ValueError(f"event {event.id} references unknown events: {sorted(missing)}")
            missing_threads = set(event.plot_thread_ids) - thread_ids
            if missing_threads:
                raise ValueError(
                    f"event {event.id} references unknown plot threads: {sorted(missing_threads)}"
                )
        for edge in self.edges:
            if edge.source_event_id not in event_ids or edge.target_event_id not in event_ids:
                raise ValueError(f"edge {edge.id} references an unknown narrative event")
        for thread in self.plot_threads:
            refs = [thread.introduced_event_id, thread.resolution_event_id, *thread.unresolved_event_ids]
            if any(ref is not None and ref not in event_ids for ref in refs):
                raise ValueError(f"plot thread {thread.id} references an unknown event")


class Character(Entity):
    project_id: CanonicalId
    canonical_name: str
    aliases: list[str] = Field(default_factory=list)
    immutable_traits: dict[str, Any] = Field(default_factory=dict)
    biography: str = ""
    role: str = "supporting"
    identity_pack_id: str | None = None
    voice_profile_id: str | None = None
    legacy_ids: dict[str, str] = Field(default_factory=dict)


class LookVariant(Entity):
    project_id: CanonicalId
    character_id: CanonicalId
    name: str
    costume: str = ""
    hairstyle: str = ""
    makeup: str = ""
    age_variant: str = ""
    damage_state: str = ""
    identity_pack_refs: list[str] = Field(default_factory=list)
    lifecycle: Literal["CANDIDATE", "SELECTED", "LOCKED", "REJECTED", "ARCHIVED"] = "CANDIDATE"


class CharacterState(Entity):
    project_id: CanonicalId
    character_id: CanonicalId
    narrative_event_id: CanonicalId | None = None
    scene_id: CanonicalId | None = None
    location_id: CanonicalId | None = None
    look_variant_id: CanonicalId | None = None
    physical_state: dict[str, Any] = Field(default_factory=dict)
    emotional_state: dict[str, Any] = Field(default_factory=dict)
    possessions: list[CanonicalId] = Field(default_factory=list)
    relationships_snapshot: dict[str, Any] = Field(default_factory=dict)


class World(Entity):
    project_id: CanonicalId
    name: str
    description: str = ""


class WorldRule(Entity):
    project_id: CanonicalId
    world_id: CanonicalId
    rule: str
    severity: Literal["HARD", "SOFT", "ADVISORY"] = "HARD"


class Location(Entity):
    project_id: CanonicalId
    world_id: CanonicalId | None = None
    name: str
    description: str = ""
    reference_artifact_ids: list[str] = Field(default_factory=list)


class LocationState(Entity):
    project_id: CanonicalId
    location_id: CanonicalId
    scene_id: CanonicalId | None = None
    time_of_day: str = ""
    weather: str = ""
    lighting: str = ""
    damage_state: str = ""
    population_state: str = ""


class Prop(Entity):
    project_id: CanonicalId
    name: str
    description: str = ""
    reference_artifact_ids: list[str] = Field(default_factory=list)


class PropState(Entity):
    project_id: CanonicalId
    prop_id: CanonicalId
    scene_id: CanonicalId | None = None
    owner_character_id: CanonicalId | None = None
    location_id: CanonicalId | None = None
    condition: str = ""
    visible: bool = True


class Season(Entity):
    project_id: CanonicalId
    number: int = Field(default=1, ge=1)
    title: str = ""


class Episode(Entity):
    project_id: CanonicalId
    season_id: CanonicalId | None = None
    number: int = Field(default=1, ge=1)
    title: str = ""
    narrative_event_ids: list[CanonicalId] = Field(default_factory=list)
    target_duration: float | None = Field(default=None, ge=0)
    legacy_ids: dict[str, str] = Field(default_factory=dict)


class Scene(Entity):
    project_id: CanonicalId
    episode_id: CanonicalId
    narrative_event_ids: list[CanonicalId] = Field(default_factory=list)
    location_id: CanonicalId | None = None
    character_ids: list[CanonicalId] = Field(default_factory=list)
    prop_ids: list[CanonicalId] = Field(default_factory=list)
    purpose: str = ""
    dramatic_function: str = ""
    emotional_target: str = ""
    continuity_entry_state: dict[str, Any] = Field(default_factory=dict)
    continuity_exit_state: dict[str, Any] = Field(default_factory=dict)
    legacy_ids: dict[str, str] = Field(default_factory=dict)


class Beat(Entity):
    project_id: CanonicalId
    scene_id: CanonicalId
    order: int = Field(default=0, ge=0)
    action: str = ""
    dialogue: str = ""
    speaker_id: CanonicalId | None = None
    target_id: CanonicalId | None = None
    emotion: str = ""
    performance: dict[str, Any] = Field(default_factory=dict)
    source_refs: list[SourceReference] = Field(default_factory=list)
    legacy_ids: dict[str, str] = Field(default_factory=dict)


class ShotSize(StrEnum):
    WIDE = "wide"
    FULL = "full"
    MEDIUM = "medium"
    MEDIUM_CLOSE = "medium_close"
    CLOSE_UP = "close_up"
    EXTREME_CLOSE = "extreme_close"


class CameraSpec(DomainModel):
    shot_size: ShotSize = ShotSize.MEDIUM
    movement: str = "static"
    angle: str = "eye_level"
    azimuth_deg: float | None = Field(default=None, ge=-360, le=360)
    elevation_deg: float | None = Field(default=None, ge=-90, le=90)
    lens_mm: float | None = Field(default=None, gt=0)
    focal_style: str = ""
    subject_distance: str = ""
    framing: str = ""
    composition: str = ""
    axis_id: str | None = None
    screen_direction: Literal["left", "right", "front", "back", "neutral"] | None = None
    eyeline_target: CanonicalId | None = None
    start_pose: str = ""
    end_pose: str = ""


class GenerationIntent(StrEnum):
    TEXT_TO_VIDEO = "TEXT_TO_VIDEO"
    IMAGE_TO_VIDEO = "IMAGE_TO_VIDEO"
    FIRST_LAST_FRAME = "FIRST_LAST_FRAME"
    REFERENCE_TO_VIDEO = "REFERENCE_TO_VIDEO"
    MULTIMODAL = "MULTIMODAL"
    ANIMATION = "ANIMATION"
    REMOTION = "REMOTION"
    AVATAR = "AVATAR"


class ReadinessState(StrEnum):
    DRAFT = "DRAFT"
    ANALYZED = "ANALYZED"
    ASSETS_PENDING = "ASSETS_PENDING"
    REFERENCES_PENDING = "REFERENCES_PENDING"
    PREFLIGHT_FAILED = "PREFLIGHT_FAILED"
    READY = "READY"
    QUEUED = "QUEUED"
    GENERATING = "GENERATING"
    GENERATED = "GENERATED"
    QA_FAILED = "QA_FAILED"
    QA_PASSED = "QA_PASSED"
    APPROVED = "APPROVED"
    LOCKED = "LOCKED"


class CanonicalShot(Entity):
    project_id: CanonicalId
    scene_id: CanonicalId
    beat_ids: list[CanonicalId] = Field(default_factory=list)
    narrative_event_ids: list[CanonicalId] = Field(default_factory=list)
    character_ids: list[CanonicalId] = Field(default_factory=list)
    location_id: CanonicalId | None = None
    prop_ids: list[CanonicalId] = Field(default_factory=list)
    blocking: list[str] = Field(default_factory=list)
    camera: CameraSpec = Field(default_factory=CameraSpec)
    performance: dict[str, Any] = Field(default_factory=dict)
    dialogue: list[str] = Field(default_factory=list)
    audio_intent: str = ""
    duration_target: float = Field(default=5.0, gt=0)
    action_description: str = ""
    cinematography_notes: str = ""
    generation_intent: GenerationIntent = GenerationIntent.IMAGE_TO_VIDEO
    readiness_state: ReadinessState = ReadinessState.DRAFT
    keyframe_ids: list[CanonicalId] = Field(default_factory=list)
    reference_bundle_id: CanonicalId | None = None
    continuity_constraint_ids: list[CanonicalId] = Field(default_factory=list)
    legacy_ids: dict[str, str] = Field(default_factory=dict)


Shot = CanonicalShot


class KeyframeRole(StrEnum):
    START = "START"
    PEAK = "PEAK"
    END = "END"
    REFERENCE = "REFERENCE"


class Keyframe(Entity):
    project_id: CanonicalId
    shot_id: CanonicalId
    role: KeyframeRole
    desired_state: dict[str, Any] = Field(default_factory=dict)
    asset_id: str | None = None
    generation_spec: dict[str, Any] = Field(default_factory=dict)
    state_version: int = Field(default=1, ge=1)
    locked: bool = False
    qa: dict[str, Any] = Field(default_factory=dict)


class ReferenceRole(StrEnum):
    CHARACTER_IDENTITY = "CHARACTER_IDENTITY"
    CHARACTER_LOOK = "CHARACTER_LOOK"
    LOCATION = "LOCATION"
    PROP = "PROP"
    STYLE = "STYLE"
    START_FRAME = "START_FRAME"
    PEAK_FRAME = "PEAK_FRAME"
    END_FRAME = "END_FRAME"
    VIDEO_MOTION = "VIDEO_MOTION"
    AUDIO = "AUDIO"
    CAMERA = "CAMERA"


class ReferenceItem(Entity):
    role: ReferenceRole
    artifact_id: str | None = None
    production_entity_id: CanonicalId | None = None
    subject_id: str | None = None
    priority: int = Field(default=0, ge=0)
    locked: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class ReferenceBundle(Entity):
    project_id: CanonicalId
    shot_id: CanonicalId
    items: list[ReferenceItem] = Field(default_factory=list)
    locked: bool = False

    def roles(self) -> set[ReferenceRole]:
        return {item.role for item in self.items}


class ConstraintSeverity(StrEnum):
    HARD = "HARD"
    SOFT = "SOFT"
    ADVISORY = "ADVISORY"


class ConstraintType(StrEnum):
    IDENTITY = "IDENTITY"
    WARDROBE = "WARDROBE"
    HAIR = "HAIR"
    PROP = "PROP"
    LOCATION = "LOCATION"
    TIME = "TIME"
    WEATHER = "WEATHER"
    POSITION = "POSITION"
    SCREEN_DIRECTION = "SCREEN_DIRECTION"
    EYELINE = "EYELINE"
    CAMERA_AXIS = "CAMERA_AXIS"
    LIGHTING = "LIGHTING"
    INJURY_STATE = "INJURY_STATE"
    NARRATIVE_FACT = "NARRATIVE_FACT"


class ContinuityConstraint(Entity):
    project_id: CanonicalId
    type: ConstraintType | str
    scope: str
    severity: ConstraintSeverity = ConstraintSeverity.HARD
    expected: Any = None
    source: str = ""
    depends_on_ids: list[CanonicalId] = Field(default_factory=list)


class ShotReadinessResult(DomainModel):
    shot_id: CanonicalId
    revision_id: CanonicalId
    state: ReadinessState
    passed: bool
    blockers: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    checks: dict[str, bool] = Field(default_factory=dict)
    evaluated_at: datetime = Field(default_factory=_now)


class DirectorSessionStatus(StrEnum):
    OPEN = "OPEN"
    PAUSED = "PAUSED"
    CLOSED = "CLOSED"


class DirectorSession(Entity):
    project_id: CanonicalId
    current_revision_id: CanonicalId
    objective: str
    constraints: list[str] = Field(default_factory=list)
    status: DirectorSessionStatus = DirectorSessionStatus.OPEN
    memory_scope: str = "PROJECT"
    created_at: datetime = Field(default_factory=_now)


class DirectorDecision(Entity):
    session_id: CanonicalId
    project_id: CanonicalId
    decision_type: str
    inputs: dict[str, Any] = Field(default_factory=dict)
    rationale: str = ""
    output_patch_id: CanonicalId | None = None
    created_at: datetime = Field(default_factory=_now)


class RevisionPatchOperation(DomainModel):
    op: Literal["add", "replace", "remove"]
    path: str
    value: Any = None


class RevisionPatch(Entity):
    project_id: CanonicalId
    base_revision_id: CanonicalId
    actor: str
    reason: str
    operations: list[RevisionPatchOperation] = Field(default_factory=list)
    decision_id: CanonicalId | None = None


class ProductionPlan(Entity):
    project_id: CanonicalId
    revision_id: CanonicalId
    shot_ids: list[CanonicalId] = Field(default_factory=list)
    mode: ProductionMode = ProductionMode.AUTO
    target_duration: float | None = Field(default=None, ge=0)
    budget_policy: dict[str, Any] = Field(default_factory=dict)
    execution_profile_id: CanonicalId | None = None
    legacy_ids: dict[str, str] = Field(default_factory=dict)


class ExecutionNode(DomainModel):
    node_key: str
    op_type: str
    capability: str
    requirements: dict[str, Any] = Field(default_factory=dict)
    dependencies: list[str] = Field(default_factory=list)
    state: Literal["pending", "queued", "running", "completed", "failed"] = "pending"


class ExecutionPlan(Entity):
    """Immutable compiler output; provider transport is intentionally absent."""

    project_id: CanonicalId | None = None
    production_id: CanonicalId | UUID | None = None  # RC6 compatibility alias
    revision_id: CanonicalId | UUID
    shot_id: CanonicalId | None = None
    shot_revision_id: CanonicalId | None = None
    reference_revision_id: CanonicalId | None = None
    provider: str = ""
    model: str = ""
    capability: str = ""
    prompt: str = ""
    negative_prompt: str = ""
    selected_references: list[ReferenceItem] = Field(default_factory=list)
    parameters: dict[str, Any] = Field(default_factory=dict)
    resolution: str = ""
    fps: int | None = Field(default=None, gt=0)
    duration: float | None = Field(default=None, gt=0)
    estimated_cost: float = Field(default=0.0, ge=0)
    estimated_latency_s: float | None = Field(default=None, ge=0)
    resource_profile: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str = ""
    plan_version: int = Field(default=1, ge=1)
    nodes: list[ExecutionNode] = Field(default_factory=list)
    immutable: bool = True
    created_at: datetime = Field(default_factory=_now)

    def validate_dag(self) -> None:
        known = {node.node_key for node in self.nodes}
        if len(known) != len(self.nodes):
            raise ValueError("execution plan contains duplicate node keys")
        if any(dep not in known for node in self.nodes for dep in node.dependencies):
            raise ValueError("execution plan references an unknown dependency")
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(key: str) -> None:
            if key in visiting:
                raise ValueError("execution plan contains a dependency cycle")
            if key in visited:
                return
            visiting.add(key)
            node = next(item for item in self.nodes if item.node_key == key)
            for dep in node.dependencies:
                visit(dep)
            visiting.remove(key)
            visited.add(key)

        for node in self.nodes:
            visit(node.node_key)


class ExecutionAttempt(Entity):
    project_id: CanonicalId
    revision_id: CanonicalId
    shot_id: CanonicalId | None = None
    execution_plan_id: CanonicalId
    attempt_no: int = Field(default=1, ge=1)
    status: str = "pending"
    idempotency_key: str
    provider_job_id: str | None = None
    checkpoint: dict[str, Any] = Field(default_factory=dict)
    artifact_ids: list[str] = Field(default_factory=list)
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class TaskEnvelope(Entity):
    """Durable execution request shared by canonical production tasks."""

    project_id: CanonicalId
    revision_id: CanonicalId
    shot_id: CanonicalId | None = None
    stage: str
    execution_plan_id: CanonicalId
    idempotency_key: str
    attempt: int = Field(default=1, ge=1)
    provider_job_id: str | None = None
    status: str = "pending"
    checkpoint: dict[str, Any] = Field(default_factory=dict)
    artifact_ids: list[str] = Field(default_factory=list)
    error: str | None = None
    retryable: bool = True
    cancelable: bool = True
    resumable: bool = True


class ProductionGraphSnapshot(DomainModel):
    project: ProductionProject
    revision: ProductionRevision
    sources: list[SourceDocument] = Field(default_factory=list)
    source_chunks: list[SourceChunk] = Field(default_factory=list)
    narrative: NarrativeGraph | None = None
    adaptation_plans: list[AdaptationPlan] = Field(default_factory=list)
    adaptation_decisions: list[AdaptationDecision] = Field(default_factory=list)
    characters: list[Character] = Field(default_factory=list)
    character_states: list[CharacterState] = Field(default_factory=list)
    look_variants: list[LookVariant] = Field(default_factory=list)
    worlds: list[World] = Field(default_factory=list)
    world_rules: list[WorldRule] = Field(default_factory=list)
    locations: list[Location] = Field(default_factory=list)
    location_states: list[LocationState] = Field(default_factory=list)
    props: list[Prop] = Field(default_factory=list)
    prop_states: list[PropState] = Field(default_factory=list)
    seasons: list[Season] = Field(default_factory=list)
    episodes: list[Episode] = Field(default_factory=list)
    scenes: list[Scene] = Field(default_factory=list)
    beats: list[Beat] = Field(default_factory=list)
    shots: list[CanonicalShot] = Field(default_factory=list)
    keyframes: list[Keyframe] = Field(default_factory=list)
    reference_bundles: list[ReferenceBundle] = Field(default_factory=list)
    continuity_constraints: list[ContinuityConstraint] = Field(default_factory=list)
    readiness_results: list[ShotReadinessResult] = Field(default_factory=list)
    director_sessions: list[DirectorSession] = Field(default_factory=list)
    director_decisions: list[DirectorDecision] = Field(default_factory=list)
    revision_patches: list[RevisionPatch] = Field(default_factory=list)
    production_plans: list[ProductionPlan] = Field(default_factory=list)
    execution_plans: list[ExecutionPlan] = Field(default_factory=list)
    execution_attempts: list[ExecutionAttempt] = Field(default_factory=list)

    def validate_referential_integrity(self) -> None:
        if self.revision.project_id != self.project.id:
            raise ValueError("revision does not belong to project")
        if self.project.current_revision_id not in (None, self.revision.id):
            raise ValueError("project current_revision_id does not match snapshot revision")
        ids = {
            "source": {item.id for item in self.sources},
            "chunk": {item.id for item in self.source_chunks},
            "character": {item.id for item in self.characters},
            "look": {item.id for item in self.look_variants},
            "world": {item.id for item in self.worlds},
            "location": {item.id for item in self.locations},
            "prop": {item.id for item in self.props},
            "season": {item.id for item in self.seasons},
            "episode": {item.id for item in self.episodes},
            "scene": {item.id for item in self.scenes},
            "beat": {item.id for item in self.beats},
            "shot": {item.id for item in self.shots},
            "keyframe": {item.id for item in self.keyframes},
            "bundle": {item.id for item in self.reference_bundles},
            "constraint": {item.id for item in self.continuity_constraints},
            "adaptation_plan": {item.id for item in self.adaptation_plans},
            "adaptation_decision": {item.id for item in self.adaptation_decisions},
        }
        if self.narrative is not None:
            self.narrative.validate_integrity()
            narrative_event_ids = {item.id for item in self.narrative.events}
        else:
            narrative_event_ids = set()
        for decision in self.adaptation_decisions:
            if set(decision.source_event_ids) - narrative_event_ids:
                raise ValueError(f"adaptation decision {decision.id} references unknown events")
            if decision.target_episode_id and decision.target_episode_id not in ids["episode"]:
                raise ValueError(f"adaptation decision {decision.id} references unknown episode")
        for plan in self.adaptation_plans:
            if set(plan.source_event_ids) - narrative_event_ids:
                raise ValueError(f"adaptation plan {plan.id} references unknown events")
            if set(plan.decision_ids) - ids["adaptation_decision"]:
                raise ValueError(f"adaptation plan {plan.id} references unknown decisions")
            if set(plan.target_episode_ids) - ids["episode"]:
                raise ValueError(f"adaptation plan {plan.id} references unknown episodes")
        for chunk in self.source_chunks:
            if chunk.document_id not in ids["source"]:
                raise ValueError(f"source chunk {chunk.id} references an unknown document")
        for look in self.look_variants:
            if look.character_id not in ids["character"]:
                raise ValueError(f"look {look.id} references an unknown character")
        for state in self.character_states:
            if state.character_id not in ids["character"]:
                raise ValueError(f"character state {state.id} references an unknown character")
            if state.look_variant_id and state.look_variant_id not in ids["look"]:
                raise ValueError(f"character state {state.id} references an unknown look")
        for episode in self.episodes:
            if episode.season_id and episode.season_id not in ids["season"]:
                raise ValueError(f"episode {episode.id} references an unknown season")
        for scene in self.scenes:
            if scene.episode_id not in ids["episode"]:
                raise ValueError(f"scene {scene.id} references an unknown episode")
            if scene.location_id and scene.location_id not in ids["location"]:
                raise ValueError(f"scene {scene.id} references an unknown location")
            missing = set(scene.character_ids) - ids["character"]
            if missing:
                raise ValueError(f"scene {scene.id} references unknown characters: {sorted(missing)}")
            missing_props = set(scene.prop_ids) - ids["prop"]
            if missing_props:
                raise ValueError(f"scene {scene.id} references unknown props: {sorted(missing_props)}")
        for beat in self.beats:
            if beat.scene_id not in ids["scene"]:
                raise ValueError(f"beat {beat.id} references an unknown scene")
        for shot in self.shots:
            if shot.scene_id not in ids["scene"]:
                raise ValueError(f"shot {shot.id} references an unknown scene")
            if set(shot.beat_ids) - ids["beat"]:
                raise ValueError(f"shot {shot.id} references an unknown beat")
            if set(shot.character_ids) - ids["character"]:
                raise ValueError(f"shot {shot.id} references unknown characters")
            if shot.location_id and shot.location_id not in ids["location"]:
                raise ValueError(f"shot {shot.id} references an unknown location")
            if set(shot.prop_ids) - ids["prop"]:
                raise ValueError(f"shot {shot.id} references unknown props")
            if shot.reference_bundle_id and shot.reference_bundle_id not in ids["bundle"]:
                raise ValueError(f"shot {shot.id} references an unknown reference bundle")
            if set(shot.keyframe_ids) - ids["keyframe"]:
                raise ValueError(f"shot {shot.id} references unknown keyframes")
            if set(shot.continuity_constraint_ids) - ids["constraint"]:
                raise ValueError(f"shot {shot.id} references unknown constraints")
        for keyframe in self.keyframes:
            if keyframe.shot_id not in ids["shot"]:
                raise ValueError(f"keyframe {keyframe.id} references an unknown shot")
        for bundle in self.reference_bundles:
            if bundle.shot_id not in ids["shot"]:
                raise ValueError(f"reference bundle {bundle.id} references an unknown shot")


__all__ = [
    "AdaptationDecision",
    "AdaptationPlan",
    "Beat",
    "CameraSpec",
    "CanonicalShot",
    "Character",
    "CharacterState",
    "ConstraintSeverity",
    "ConstraintType",
    "ContinuityConstraint",
    "DirectorDecision",
    "DirectorSession",
    "DirectorSessionStatus",
    "Entity",
    "Episode",
    "ExecutionAttempt",
    "ExecutionNode",
    "ExecutionPlan",
    "GenerationIntent",
    "Keyframe",
    "KeyframeRole",
    "Location",
    "LocationState",
    "LookVariant",
    "NarrativeEdge",
    "NarrativeEdgeType",
    "NarrativeEvent",
    "NarrativeGraph",
    "PlotThread",
    "ProductionGraphSnapshot",
    "ProductionMode",
    "ProductionPlan",
    "ProductionProject",
    "ProductionRevision",
    "ProjectStatus",
    "Prop",
    "PropState",
    "ReadinessState",
    "ReferenceBundle",
    "ReferenceItem",
    "ReferenceRole",
    "RevisionPatch",
    "RevisionPatchOperation",
    "Scene",
    "Season",
    "Shot",
    "ShotReadinessResult",
    "ShotSize",
    "SourceChunk",
    "SourceDocument",
    "SourceKind",
    "SourceReference",
    "TaskEnvelope",
    "World",
    "WorldRule",
]
