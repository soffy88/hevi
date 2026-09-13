"""Canonical narrative domain objects.

These contracts intentionally contain no renderer/provider-specific fields.
They are dataclasses so their JSON representation is stable and dependency-light.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import UTC, datetime
from typing import Any, Literal, cast

SCHEMA_VERSION = "1.0"
Timestamp = str


def now() -> Timestamp:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


@dataclass(frozen=True)
class StoryPremise:
    text: str


@dataclass(frozen=True)
class Theme:
    name: str
    statement: str = ""


@dataclass(frozen=True)
class DramaticQuestion:
    text: str


@dataclass(frozen=True)
class CharacterGoal:
    text: str
    stakes: str = ""


@dataclass(frozen=True)
class CharacterObstacle:
    text: str


@dataclass(frozen=True)
class CharacterArc:
    start_state: str
    end_state: str
    turning_points: tuple[str, ...] = ()


@dataclass(frozen=True)
class Character:
    id: str
    name: str
    aliases: tuple[str, ...] = ()
    role: str = ""
    motivation: str = ""
    goal: CharacterGoal | None = None
    fear: str = ""
    conflict: str = ""
    traits: tuple[str, ...] = ()
    knowledge_state: tuple[str, ...] = ()
    relationship_ids: tuple[str, ...] = ()
    arc: CharacterArc | None = None
    visual_identity_ref: str | None = None
    voice_identity_ref: str | None = None


@dataclass(frozen=True)
class CharacterState:
    character_id: str
    scene_id: str
    location: str | None = None
    emotional_state: str = ""
    physical_state: str = ""
    knowledge: tuple[str, ...] = ()
    timestamp: str = ""


@dataclass(frozen=True)
class CharacterRelationship:
    id: str
    from_character: str
    to_character: str
    relation_type: str
    strength: float = 0.5
    trust: float = 0.5
    conflict: float = 0.0
    public_state: str = ""
    private_state: str = ""
    valid_from: str | None = None
    valid_to: str | None = None


@dataclass(frozen=True)
class WorldRule:
    id: str
    statement: str
    source_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class Location:
    id: str
    name: str
    description: str = ""


@dataclass(frozen=True)
class TimelineEvent:
    id: str
    label: str
    order: int
    timestamp: str | None = None
    source_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class NarrativeAssertion:
    id: str
    text: str
    type: Literal["SOURCE_FACT", "DERIVED_CLAIM", "INTERPRETATION", "DRAMATIZATION", "FICTIONAL_BRIDGE"]
    evidence_refs: tuple[str, ...] = ()
    historically_verified: bool = False


@dataclass(frozen=True)
class StoryBeat:
    id: str
    kind: str
    purpose: str
    setup: str = ""
    conflict: str = ""
    change: str = ""
    payoff: str = ""
    character_ids: tuple[str, ...] = ()
    source_claim_ids: tuple[str, ...] = ()
    continuity_effects: tuple[str, ...] = ()


@dataclass(frozen=True)
class SequenceBlueprint:
    id: str
    purpose: str
    beat_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class EpisodeBlueprint:
    episode_id: str
    episode_number: int
    premise: str
    episode_goal: str
    incoming_state: tuple[str, ...] = ()
    outgoing_state: tuple[str, ...] = ()
    beats: tuple[StoryBeat, ...] = ()
    sequences: tuple[SequenceBlueprint, ...] = ()
    scene_ids: tuple[str, ...] = ()
    open_threads: tuple[str, ...] = ()
    resolved_threads: tuple[str, ...] = ()


@dataclass(frozen=True)
class SceneObjective:
    text: str


@dataclass(frozen=True)
class SceneObstacle:
    text: str


@dataclass(frozen=True)
class SceneTurn:
    text: str


@dataclass(frozen=True)
class SceneOutcome:
    text: str


@dataclass(frozen=True)
class DialogueIntent:
    speaker: str
    goal: str
    subtext: str = ""
    information_to_reveal: tuple[str, ...] = ()
    information_to_hide: tuple[str, ...] = ()
    emotional_shift: str = ""
    relationship_effect: str = ""


@dataclass(frozen=True)
class ContinuityConstraint:
    id: str
    kind: str
    description: str
    entity_refs: tuple[str, ...] = ()
    severity: Literal["FAIL", "WARN"] = "FAIL"


@dataclass(frozen=True)
class ContinuityViolation:
    code: str
    severity: Literal["FAIL", "WARN"]
    entity_refs: tuple[str, ...]
    scene_refs: tuple[str, ...]
    description: str
    suggested_resolution: str = ""


@dataclass(frozen=True)
class SceneBlueprint:
    scene_id: str
    sequence_id: str
    purpose: str
    objective: SceneObjective
    obstacle: SceneObstacle
    conflict: str
    turn: SceneTurn
    outcome: SceneOutcome
    characters: tuple[str, ...]
    location: str
    time: str
    incoming_state: tuple[str, ...] = ()
    outgoing_state: tuple[str, ...] = ()
    required_facts: tuple[str, ...] = ()
    forbidden_claims: tuple[str, ...] = ()
    dialogue_intent: tuple[DialogueIntent, ...] = ()
    visual_intent: str = ""
    emotional_tone: str = ""
    pace: str = "medium"
    source_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    continuity_constraints: tuple[ContinuityConstraint, ...] = ()


@dataclass(frozen=True)
class NarrativeStyleProfile:
    tone: str = ""
    register: str = ""
    dialogue_density: str = "medium"
    narration_density: str = "medium"
    pace: str = "medium"
    humor: str = ""
    formality: str = ""
    audience: str = ""
    genre: str = ""


@dataclass(frozen=True)
class NarrativeThread:
    id: str
    kind: str
    introduced_at: str
    status: Literal["OPEN", "ADVANCED", "RESOLVED", "ABANDONED"] = "OPEN"
    payoff_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class NarrativeRevision:
    asset_id: str
    base_revision: str | None
    new_revision: str
    change_type: str
    reason: str
    author: str
    created_at: Timestamp


@dataclass(frozen=True)
class RevisionReceipt:
    asset_id: str
    previous_revision: str | None
    new_revision: str
    committed: bool
    validation: str


@dataclass(frozen=True)
class NarrativeProvenance:
    project_revision: str
    story_bible_revision: str
    episode_revision: str | None
    scene_revision: str | None
    llm_provider: str | None = None
    llm_model: str | None = None
    source_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    continuity_report_id: str | None = None
    review_report_id: str | None = None
    shot_plan_id: str | None = None


@dataclass(frozen=True)
class GenerationCompletionStatus:
    status: Literal["COMPLETE", "TRUNCATED", "CANCELLED", "FAILED"]
    continuation_count: int = 0
    overlap_deduplicated: bool = False


@dataclass(frozen=True)
class StoryBible:
    project_id: str
    schema_version: str = SCHEMA_VERSION
    premise: StoryPremise | None = None
    theme: Theme | None = None
    dramatic_question: DramaticQuestion | None = None
    characters: tuple[Character, ...] = ()
    relationships: tuple[CharacterRelationship, ...] = ()
    world_rules: tuple[WorldRule, ...] = ()
    locations: tuple[Location, ...] = ()
    timeline: tuple[TimelineEvent, ...] = ()
    established_facts: tuple[NarrativeAssertion, ...] = ()
    continuity_constraints: tuple[ContinuityConstraint, ...] = ()
    episodes: tuple[EpisodeBlueprint, ...] = ()
    sequences: tuple[SequenceBlueprint, ...] = ()
    style_profile: NarrativeStyleProfile = field(default_factory=NarrativeStyleProfile)
    narrative_voice: str = ""
    unresolved_threads: tuple[NarrativeThread, ...] = ()
    resolved_threads: tuple[NarrativeThread, ...] = ()
    source_refs: tuple[str, ...] = ()
    revision: str = "0"
    updated_at: Timestamp = field(default_factory=now)


@dataclass(frozen=True)
class SeriesBible:
    series_id: str
    global_story_bible: StoryBible
    episode_order: tuple[str, ...] = ()
    series_arc: tuple[str, ...] = ()
    persistent_characters: tuple[str, ...] = ()
    persistent_locations: tuple[str, ...] = ()
    persistent_threads: tuple[str, ...] = ()


@dataclass(frozen=True)
class NarrativeProject:
    project_id: str
    title: str
    story_bible: StoryBible
    revision: str = "0"
    created_at: Timestamp = field(default_factory=now)


def to_dict(value: Any) -> Any:
    """Stable JSON-ready serialization for every canonical object."""
    if is_dataclass(value):
        raw = asdict(cast(Any, value))
        return {key: to_dict(item) for key, item in raw.items()}
    if isinstance(value, tuple):
        return [to_dict(item) for item in value]
    if isinstance(value, list):
        return [to_dict(item) for item in value]
    if isinstance(value, dict):
        return {str(key): to_dict(item) for key, item in sorted(value.items())}
    return value
