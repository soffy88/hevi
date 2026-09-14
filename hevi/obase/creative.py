"""HEVI-native creative runtime contracts.

This module is the additive Phase 1 contract surface for the 3O creative
runtime.  It deliberately contains data authority and identity only.  It
does not import or mirror an external creative runtime and it does not grant
any model, skill, or projection permission to mutate canonical state.

The existing ``hevi.narrative`` package remains the frozen Narrative v1
contract.  These records are the cross-capability envelope used by vNext
modules and can reference frozen Narrative v1 records through provenance.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

CREATIVE_CONTRACT_VERSION = 1


class CreativeAuthority(StrEnum):
    """The authority of a record in the creative runtime."""

    CANONICAL = "CANONICAL"
    PROJECTION = "PROJECTION"
    SNAPSHOT = "SNAPSHOT"
    PROPOSAL = "PROPOSAL"
    EVIDENCE = "EVIDENCE"
    EXECUTION_PLAN = "EXECUTION_PLAN"


class CreativeObject(BaseModel):
    """Common identity and provenance envelope for all creative objects."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True, str_strip_whitespace=True)

    schema_version: int = Field(default=CREATIVE_CONTRACT_VERSION, ge=1)
    object_id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    revision: int = Field(default=0, ge=0)
    authority: CreativeAuthority = CreativeAuthority.CANONICAL
    provenance: tuple[ProvenanceRef, ...] = ()
    content_hash: str | None = None

    @model_validator(mode="after")
    def validate_dates(self) -> CreativeObject:
        if self.updated_at < self.created_at:
            raise ValueError("updated_at must not precede created_at")
        return self

    def stable_dump(self) -> dict[str, Any]:
        """Return a deterministic JSON-compatible representation."""

        return self.model_dump(mode="json", exclude_none=True)

    def stable_json(self) -> str:
        return json.dumps(
            self.stable_dump(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )

    def calculated_hash(self) -> str:
        """Hash identity/content while excluding mutable bookkeeping fields."""

        payload = self.model_dump(
            mode="json",
            exclude_none=True,
            exclude={"content_hash", "created_at", "updated_at"},
        )
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class ProvenanceRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ref_id: str = Field(min_length=1)
    ref_type: str = Field(min_length=1)
    uri: str | None = None
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{64}$")
    locator: str | None = None


class AuthorIntent(CreativeObject):
    purpose: str
    audience: str | None = None
    tone: str | None = None
    constraints: tuple[str, ...] = ()
    success_criteria: tuple[str, ...] = ()


class StoryRule(CreativeObject):
    name: str
    rule: str
    severity: Literal["HARD", "SOFT"] = "HARD"


class CharacterState(CreativeObject):
    character_id: UUID
    knowledge: tuple[str, ...] = ()
    emotional: tuple[str, ...] = ()
    physical: tuple[str, ...] = ()
    location_id: UUID | None = None
    at_time: str | None = None


class CharacterVoice(CreativeObject):
    character_id: UUID
    voice_register: str = Field(alias="register")
    cadence: str | None = None
    vocabulary: tuple[str, ...] = ()
    forbidden_patterns: tuple[str, ...] = ()

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        str_strip_whitespace=True,
        populate_by_name=True,
    )


class Character(CreativeObject):
    name: str
    aliases: tuple[str, ...] = ()
    role: str | None = None
    motivation: str | None = None
    goals: tuple[str, ...] = ()
    fears: tuple[str, ...] = ()
    conflict: str | None = None
    traits: tuple[str, ...] = ()
    knowledge_state_id: UUID | None = None
    relationship_ids: tuple[UUID, ...] = ()
    arc_id: UUID | None = None
    voice_id: UUID | None = None


class WorldRule(CreativeObject):
    statement: str
    scope: str | None = None
    hard: bool = True


class WorldState(CreativeObject):
    rule_ids: tuple[UUID, ...] = ()
    fact_refs: tuple[ProvenanceRef, ...] = ()
    state: tuple[tuple[str, str], ...] = ()


class LocationState(CreativeObject):
    name: str
    description: str | None = None
    property_refs: tuple[UUID, ...] = ()


class RelationshipState(CreativeObject):
    from_character: UUID
    to_character: UUID
    relation_type: str
    strength: float = Field(default=0.0, ge=-1.0, le=1.0)
    trust: float = Field(default=0.0, ge=-1.0, le=1.0)
    conflict: float = Field(default=0.0, ge=0.0, le=1.0)
    valid_from: str | None = None
    valid_to: str | None = None


class ResourceState(CreativeObject):
    name: str
    owner_ref: UUID | None = None
    status: str
    quantity: str | None = None


class InformationState(CreativeObject):
    subject: str
    known_by: tuple[UUID, ...] = ()
    source_refs: tuple[ProvenanceRef, ...] = ()


class EmotionState(CreativeObject):
    character_id: UUID
    label: str
    intensity: float = Field(default=0.0, ge=0.0, le=1.0)


class PhysicalState(CreativeObject):
    character_id: UUID
    condition: str
    location_id: UUID | None = None


class TimelineState(CreativeObject):
    event_ids: tuple[UUID, ...] = ()
    current_marker: str | None = None


class StoryArc(CreativeObject):
    name: str
    goal: str
    obstacle: str | None = None
    status: Literal["PLANNED", "ACTIVE", "RESOLVED", "ABANDONED"] = "PLANNED"
    beat_ids: tuple[UUID, ...] = ()


class StoryBeat(CreativeObject):
    purpose: str
    change: str
    character_ids: tuple[UUID, ...] = ()
    source_refs: tuple[ProvenanceRef, ...] = ()


class ChapterIntent(CreativeObject):
    sequence: int = Field(ge=1)
    purpose: str
    objective: str | None = None
    beat_ids: tuple[UUID, ...] = ()


class SceneIntent(CreativeObject):
    sequence: int = Field(ge=1)
    purpose: str
    objective: str
    obstacle: str | None = None
    turn: str | None = None
    outcome: str | None = None
    character_ids: tuple[UUID, ...] = ()
    location_id: UUID | None = None


class PendingHook(CreativeObject):
    description: str
    priority: Literal["LOW", "MEDIUM", "HIGH"] = "MEDIUM"
    introduced_in: UUID | None = None
    payoff_refs: tuple[UUID, ...] = ()
    status: Literal["OPEN", "ADVANCED", "RESOLVED", "ABANDONED"] = "OPEN"


class Foreshadow(CreativeObject):
    setup: str
    payoff: str | None = None
    setup_refs: tuple[UUID, ...] = ()
    payoff_refs: tuple[UUID, ...] = ()


class Payoff(CreativeObject):
    description: str
    setup_refs: tuple[UUID, ...] = ()
    resolved_hook_ids: tuple[UUID, ...] = ()


class ChapterSummary(CreativeObject):
    chapter_id: UUID
    summary: str
    character_ids: tuple[UUID, ...] = ()
    source_refs: tuple[ProvenanceRef, ...] = ()


class ContinuityFact(CreativeObject):
    statement: str
    source_refs: tuple[ProvenanceRef, ...] = ()
    valid_from: str | None = None
    valid_to: str | None = None


class NarrativeCanon(CreativeObject):
    """Canonical narrative authority; projections cannot be committed here."""

    character_ids: tuple[UUID, ...] = ()
    character_state_ids: tuple[UUID, ...] = ()
    world_rule_ids: tuple[UUID, ...] = ()
    world_state_id: UUID | None = None
    location_ids: tuple[UUID, ...] = ()
    relationship_state_ids: tuple[UUID, ...] = ()
    resource_state_ids: tuple[UUID, ...] = ()
    information_state_ids: tuple[UUID, ...] = ()
    emotion_state_ids: tuple[UUID, ...] = ()
    physical_state_ids: tuple[UUID, ...] = ()
    timeline_state_id: UUID | None = None
    arc_ids: tuple[UUID, ...] = ()
    beat_ids: tuple[UUID, ...] = ()
    chapter_intent_ids: tuple[UUID, ...] = ()
    scene_intent_ids: tuple[UUID, ...] = ()
    hook_ids: tuple[UUID, ...] = ()
    foreshadow_ids: tuple[UUID, ...] = ()
    payoff_ids: tuple[UUID, ...] = ()
    continuity_fact_ids: tuple[UUID, ...] = ()


class StoryBible(CreativeObject):
    premise: str
    theme: str | None = None
    dramatic_question: str | None = None
    canon_id: UUID
    author_intent_id: UUID | None = None
    story_rule_ids: tuple[UUID, ...] = ()
    chapter_ids: tuple[UUID, ...] = ()
    scene_ids: tuple[UUID, ...] = ()


class NarrativeProject(CreativeObject):
    title: str
    language: str = "en"
    narrative_kind: Literal["NOVEL", "SHORT", "SCRIPT", "DOCUMENTARY", "SERIES"] = "NOVEL"
    author_intent_id: UUID | None = None
    story_bible_id: UUID | None = None
    canon_id: UUID | None = None


class CreativeProject(CreativeObject):
    name: str
    kind: str
    narrative_project_id: UUID | None = None
    active_run_id: UUID | None = None


class CreativeSource(CreativeObject):
    title: str
    source_type: Literal["USER", "UPLOADED", "PUBLIC", "RESEARCH", "GENERATED", "REFERENCE"]
    uri: str | None = None
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{64}$")
    license_ref: str | None = None


class CreativeEvidence(CreativeObject):
    source_id: UUID
    claim: str
    locator: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    accepted_to_canon: bool = False


class ResearchReport(CreativeObject):
    query: str
    source_ids: tuple[UUID, ...] = ()
    evidence_ids: tuple[UUID, ...] = ()
    unknowns: tuple[str, ...] = ()
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    canon_commit_required: bool = True


class Material(CreativeObject):
    name: str
    material_type: Literal["TEXT", "MARKDOWN", "IMAGE", "DOCUMENT", "EXTERNAL_REFERENCE"]
    source_id: UUID
    purpose: str | None = None
    archive: bool = False


class NarrativeBranch(CreativeObject):
    name: str
    base_canon_revision: int = Field(ge=0)
    beat_ids: tuple[UUID, ...] = ()
    projected_character_changes: tuple[str, ...] = ()
    projected_world_changes: tuple[str, ...] = ()
    risks: tuple[str, ...] = ()
    intent_alignment: float | None = Field(default=None, ge=0.0, le=1.0)
    selected: bool = False

    @model_validator(mode="after")
    def branch_is_non_canonical(self) -> NarrativeBranch:
        if self.authority is CreativeAuthority.CANONICAL:
            raise ValueError("narrative branches must remain non-canonical")
        return self


class ScriptScene(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scene_id: UUID
    location: str
    time: str | None = None
    action: str
    dialogue: tuple[str, ...] = ()
    production_notes: tuple[str, ...] = ()


class Script(CreativeObject):
    title: str
    scene_ids: tuple[UUID, ...] = ()
    format: Literal["SCREENPLAY", "AUDIO", "SHORT_FORM", "DOCUMENTARY"] = "SCREENPLAY"
    language: str = "en"


class StoryboardShot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shot_id: UUID
    visual_intent: str
    framing: str | None = None
    camera: str | None = None
    subject: str | None = None
    action: str | None = None
    environment: str | None = None
    duration_ms: int = Field(gt=0)
    transition: str | None = None
    audio_refs: tuple[UUID, ...] = ()


class StoryboardScene(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scene_id: UUID
    shot_ids: tuple[UUID, ...] = ()


class Storyboard(CreativeObject):
    title: str
    script_id: UUID
    scenes: tuple[StoryboardScene, ...] = ()
    shots: tuple[StoryboardShot, ...] = ()


class Condition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expression: str
    variable_refs: tuple[str, ...] = ()


class Choice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    choice_id: UUID = Field(default_factory=uuid4)
    label: str
    target_node_id: UUID
    condition: Condition | None = None


class StoryNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: UUID = Field(default_factory=uuid4)
    title: str
    choice_ids: tuple[UUID, ...] = ()
    ending: bool = False
    visual_asset_ids: tuple[UUID, ...] = ()


class InteractiveFilm(CreativeObject):
    title: str
    node_ids: tuple[UUID, ...] = ()
    choice_ids: tuple[UUID, ...] = ()
    variable_names: tuple[str, ...] = ()
    ending_node_ids: tuple[UUID, ...] = ()


class InventoryItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: str
    quantity: int = Field(default=1, ge=0)


class InteractiveWorld(CreativeObject):
    title: str
    world_contract: str
    clock: str
    player_state_ref: UUID | None = None
    inventory: tuple[InventoryItem, ...] = ()
    turn: int = Field(default=0, ge=0)


class GlossaryEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    term: str
    translation: str
    notes: str | None = None


class TranslationSegment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    segment_id: UUID = Field(default_factory=uuid4)
    source_text: str
    translated_text: str | None = None
    ordinal: int = Field(ge=0)
    source_ref: ProvenanceRef | None = None


class TranslationProject(CreativeObject):
    source_artifact_id: UUID
    source_language: str
    target_language: str
    segment_ids: tuple[UUID, ...] = ()
    glossary: tuple[GlossaryEntry, ...] = ()
    status: Literal["CREATED", "RUNNING", "REVIEW", "COMPLETED", "FAILED"] = "CREATED"


class StyleProfile(CreativeObject):
    name: str
    sentence_length: str | None = None
    lexical_characteristics: tuple[str, ...] = ()
    rhythm: str | None = None
    dialogue_ratio: float | None = Field(default=None, ge=0.0, le=1.0)
    paragraph_structure: str | None = None
    pov_tendencies: tuple[str, ...] = ()
    tone: tuple[str, ...] = ()
    descriptive_density: str | None = None


class GenreRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    requirement: str
    severity: Literal["HARD", "SOFT"] = "SOFT"


class GenreProfile(CreativeObject):
    name: str
    rules: tuple[GenreRule, ...] = ()
    forbidden_patterns: tuple[str, ...] = ()
    pacing_profile: str | None = None
    fatigue_lexicon: tuple[str, ...] = ()


class CreativeSkill(CreativeObject):
    name: str
    knowledge_refs: tuple[ProvenanceRef, ...] = ()
    policy_refs: tuple[ProvenanceRef, ...] = ()
    can_write_state: bool = False
    can_bypass_gate: bool = False


class CreativePolicy(CreativeObject):
    name: str
    scope: Literal["GLOBAL", "PROJECT", "CAPABILITY"]
    version: int = Field(default=1, ge=1)
    rules: tuple[str, ...] = ()
    enabled: bool = True


class StageResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage: str
    status: Literal["PENDING", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED"]
    artifact_ids: tuple[UUID, ...] = ()
    error_code: str | None = None


class FailureRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    retryable: bool = False
    stage: str


class ArtifactManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_ids: tuple[UUID, ...] = ()
    hashes: tuple[str, ...] = ()


class ProductionRun(CreativeObject):
    run_key: str
    capability: str
    status: Literal["PENDING", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED", "BLOCKED"] = "PENDING"
    stage_results: tuple[StageResult, ...] = ()
    artifact_manifest: ArtifactManifest = Field(default_factory=ArtifactManifest)
    failure: FailureRecord | None = None


class RunSnapshot(CreativeObject):
    run_id: UUID
    stage: str
    state_hash: str
    resume_token: str | None = None


class CreativeArtifact(CreativeObject):
    artifact_type: str
    uri: str
    media_type: str
    sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    source_ids: tuple[UUID, ...] = ()
    quality_gate_status: Literal["PENDING", "PASS", "WARN", "FAIL"] = "PENDING"


class AuditFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    severity: Literal["INFO", "WARN", "ERROR", "FATAL"]
    dimension: str
    evidence: tuple[ProvenanceRef, ...] = ()
    artifact_location: str | None = None
    canonical_refs: tuple[UUID, ...] = ()
    recommendation: str
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class NarrativeAudit(CreativeObject):
    artifact_id: UUID
    status: Literal["PASS", "WARN", "FAIL"]
    findings: tuple[AuditFinding, ...] = ()
    dimensions_checked: tuple[str, ...] = ()


class Revision(CreativeObject):
    asset_id: UUID
    base_revision: int = Field(ge=0)
    new_revision: int = Field(ge=0)
    change_type: Literal["POLISH", "SPOT_FIX", "REWRITE", "STRUCTURAL_REWORK", "QUALITY_DRIVEN"]
    reason: str
    proposal_only: bool = True

    @model_validator(mode="after")
    def revision_is_forward(self) -> Revision:
        if self.new_revision <= self.base_revision:
            raise ValueError("new_revision must be greater than base_revision")
        return self


class Approval(CreativeObject):
    target_id: UUID
    decision: Literal["APPROVE", "REJECT", "EDIT", "REVISION_REQUEST", "APPROVE_ALL"]
    actor_id: str
    note: str | None = None


class ExportArtifact(CreativeArtifact):
    export_format: Literal["TXT", "MARKDOWN", "EPUB", "PDF", "JSON", "PLAYABLE"]
    manifest_id: UUID | None = None


__all__ = [
    "CREATIVE_CONTRACT_VERSION",
    "Approval",
    "ArtifactManifest",
    "AuditFinding",
    "AuthorIntent",
    "ChapterIntent",
    "ChapterSummary",
    "Character",
    "CharacterState",
    "CharacterVoice",
    "Choice",
    "Condition",
    "ContinuityFact",
    "CreativeArtifact",
    "CreativeAuthority",
    "CreativeEvidence",
    "CreativeObject",
    "CreativePolicy",
    "CreativeProject",
    "CreativeSkill",
    "CreativeSource",
    "EmotionState",
    "ExportArtifact",
    "FailureRecord",
    "Foreshadow",
    "GenreProfile",
    "GenreRule",
    "GlossaryEntry",
    "InformationState",
    "InteractiveFilm",
    "InteractiveWorld",
    "InventoryItem",
    "LocationState",
    "Material",
    "NarrativeAudit",
    "NarrativeBranch",
    "NarrativeCanon",
    "NarrativeProject",
    "Payoff",
    "PendingHook",
    "PhysicalState",
    "ProductionRun",
    "ProvenanceRef",
    "RelationshipState",
    "ResearchReport",
    "ResourceState",
    "Revision",
    "RunSnapshot",
    "SceneIntent",
    "Script",
    "ScriptScene",
    "StoryArc",
    "StoryBeat",
    "StoryBible",
    "StoryRule",
    "Storyboard",
    "StoryboardScene",
    "StoryboardShot",
    "StyleProfile",
    "TimelineState",
    "TranslationProject",
    "TranslationSegment",
    "WorldRule",
    "WorldState",
]
