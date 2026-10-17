"""P2 production-intelligence control plane.

This module is deliberately a control-plane projection over the frozen P0
production graph and the P1 Workbench.  It stores typed proposals, policy,
review, learning and evidence records through ``ProductionGraphRepository``;
it never becomes an alternate production graph, provider transport, or task
queue.  All records carry project/revision identity so stale work cannot be
silently applied.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field

from .ids import new_id
from .repository import ProductionGraphRepository


def _now() -> datetime:
    return datetime.now(UTC)


class P2Model(BaseModel):
    id: str = Field(default_factory=new_id)
    project_id: str
    revision_id: str
    created_at: datetime = Field(default_factory=_now)


class CrewRole(StrEnum):
    DIRECTOR = "director"
    STORY = "story"
    CONTINUITY = "continuity"
    EDITOR = "editor"
    QA = "qa"


class AdaptiveCrew(P2Model):
    """A persisted crew decision envelope, not an autonomous executor."""

    objective: str
    roles: list[CrewRole] = Field(default_factory=list)
    proposal_ids: list[str] = Field(default_factory=list)
    selected_director_id: str | None = None
    resolved: bool = False


class ProposalState(StrEnum):
    PROPOSED = "PROPOSED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class CrewProposal(P2Model):
    role: CrewRole
    action_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    rationale: str = ""
    state: ProposalState = ProposalState.PROPOSED
    evidence_ids: list[str] = Field(default_factory=list)
    actor_id: str = ""


class ConflictResolution(P2Model):
    proposal_ids: list[str] = Field(min_length=2)
    winner_id: str
    reason: str = Field(min_length=1)
    authority: Literal["user", "locked_state", "policy", "memory", "learned"] = "policy"
    anti_theater_check: bool = True


class AntiTheaterEvidence(P2Model):
    proposal_id: str
    required_fields: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    canonical_effect: str = ""
    passed: bool = False


class PreferenceAuthority(StrEnum):
    EXPLICIT_USER = "explicit_user"
    LOCKED_CANONICAL = "locked_canonical"
    PROJECT_POLICY = "project_policy"
    LEARNED_PREFERENCE = "learned_preference"


class CreativePreference(P2Model):
    scope: Literal["PROJECT", "SEASON", "EPISODE", "CHARACTER", "DIRECTOR_SESSION"]
    scope_id: str | None = None
    key: str
    value: Any
    source: str
    confidence: float = Field(default=0.5, ge=0, le=1)
    authority: PreferenceAuthority = PreferenceAuthority.LEARNED_PREFERENCE
    active: bool = True


class CreativePreferenceProfile(P2Model):
    """Structured preference projection; it is never an authority over locks."""

    scope: Literal["PROJECT", "SEASON", "EPISODE", "CHARACTER", "DIRECTOR_SESSION"]
    scope_id: str | None = None
    preferences: list[CreativePreference] = Field(default_factory=list)
    authority_order: list[PreferenceAuthority] = Field(
        default_factory=lambda: [
            PreferenceAuthority.EXPLICIT_USER,
            PreferenceAuthority.LOCKED_CANONICAL,
            PreferenceAuthority.PROJECT_POLICY,
            PreferenceAuthority.LEARNED_PREFERENCE,
        ]
    )


class ProductionOutcome(P2Model):
    execution_attempt_id: str | None = None
    artifact_id: str | None = None
    metrics: dict[str, float] = Field(default_factory=dict)
    accepted: bool = False
    failure_codes: list[str] = Field(default_factory=list)
    provenance_refs: list[str] = Field(default_factory=list)


class ReviewState(StrEnum):
    OPEN = "OPEN"
    APPROVED = "APPROVED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    RESOLVED = "RESOLVED"


class ReviewThread(P2Model):
    object_type: str
    object_id: str
    reviewer_id: str
    comment: str
    state: ReviewState = ReviewState.OPEN
    base_revision_id: str
    resolved_revision_id: str | None = None


class SpatialConstraint(P2Model):
    shot_id: str
    subject_id: str
    coordinate_system: str = "screen-normalized"
    position: dict[str, float] = Field(default_factory=dict)
    facing_degrees: float | None = None
    tolerance: float = Field(default=0.1, ge=0)
    status: Literal["VALID", "STALE", "VIOLATION"] = "VALID"


class NLEOperation(P2Model):
    sequence_id: str
    operation: Literal["trim", "replace", "subtitle", "audio_level", "bgm", "reorder"]
    target_id: str
    params: dict[str, Any] = Field(default_factory=dict)
    semantic: bool = True


class LocalizationTrack(P2Model):
    locale: str
    source_track_id: str
    segments: list[dict[str, Any]] = Field(default_factory=list)
    qa_status: Literal["PENDING", "PASS", "FAIL"] = "PENDING"


class PluginPermission(StrEnum):
    READ_GRAPH = "read_graph"
    PROPOSE_PATCH = "propose_patch"
    READ_ARTIFACT = "read_artifact"


class PluginManifest(P2Model):
    plugin_name: str
    plugin_version: str
    permissions: list[PluginPermission] = Field(default_factory=list)
    signature: str = Field(min_length=1)
    enabled: bool = False


class PluginProposal(P2Model):
    plugin_id: str
    action_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    validated: bool = False
    applied_revision_id: str | None = None


class DispatchLease(P2Model):
    task_id: str
    worker_id: str
    lease_token: str
    expires_at: datetime
    checkpoint: dict[str, Any] = Field(default_factory=dict)
    state: Literal["LEASED", "RECOVERED", "COMPLETED", "EXPIRED"] = "LEASED"


class EvaluationCase(P2Model):
    name: str
    input_refs: list[str] = Field(default_factory=list)
    expected: dict[str, Any] = Field(default_factory=dict)
    metric_names: list[str] = Field(default_factory=list)


class EvaluationResult(P2Model):
    case_id: str
    metrics: dict[str, float] = Field(default_factory=dict)
    passed: bool = False
    evidence_refs: list[str] = Field(default_factory=list)


class RightsLedgerEntry(P2Model):
    asset_id: str
    right_type: Literal["source", "music", "voice", "image", "model", "distribution"]
    licensor: str
    license_id: str
    territories: list[str] = Field(default_factory=list)
    expires_at: datetime | None = None
    allowed: bool = True
    evidence_refs: list[str] = Field(default_factory=list)


RECORD_TYPES = {
    "adaptive_crew": AdaptiveCrew,
    "crew_proposal": CrewProposal,
    "crew_conflict": ConflictResolution,
    "anti_theater": AntiTheaterEvidence,
    "preference": CreativePreference,
    "preference_profile": CreativePreferenceProfile,
    "outcome": ProductionOutcome,
    "review": ReviewThread,
    "spatial": SpatialConstraint,
    "nle_operation": NLEOperation,
    "localization": LocalizationTrack,
    "plugin_manifest": PluginManifest,
    "plugin_proposal": PluginProposal,
    "dispatch_lease": DispatchLease,
    "evaluation_case": EvaluationCase,
    "evaluation_result": EvaluationResult,
    "rights": RightsLedgerEntry,
}


def _record_type(model: BaseModel) -> str:
    for name, cls in RECORD_TYPES.items():
        if isinstance(model, cls):
            return f"p2_{name}"
    raise TypeError(f"unsupported P2 record: {type(model).__name__}")


class ProductionIntelligenceService:
    """Persist and validate P2 records using the existing graph repository."""

    def __init__(self, repository: ProductionGraphRepository) -> None:
        self.repository = repository

    async def save(self, record: P2Model) -> dict[str, Any]:
        if record.__class__ is ConflictResolution and not record.anti_theater_check:
            raise ValueError("conflict resolution requires anti-theater evidence")
        if isinstance(record, PluginManifest) and not set(record.permissions) <= set(
            PluginPermission
        ):
            raise ValueError("plugin requested an unsupported permission")
        if isinstance(record, PluginProposal):
            manifests = await self.list(record.project_id, "plugin_manifest")
            manifest = next((item for item in manifests if item["id"] == record.plugin_id), None)
            if not manifest or not manifest.get("enabled"):
                raise ValueError("plugin is not enabled")
            if PluginPermission.PROPOSE_PATCH.value not in manifest.get("permissions", []):
                raise ValueError("plugin lacks propose_patch permission")
        return await self.repository.save_workbench_record(
            record.project_id, _record_type(record), record.model_dump(mode="json")
        )

    async def list(self, project_id: str, kind: str) -> list[dict[str, Any]]:
        if kind not in RECORD_TYPES:
            raise ValueError(f"unknown P2 record type: {kind}")
        return await self.repository.list_workbench_records(project_id, f"p2_{kind}")

    async def learn_from_outcome(
        self, outcome: ProductionOutcome, *, preference_key: str, preference_value: Any
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        saved = await self.save(outcome)
        preference = CreativePreference(
            project_id=outcome.project_id,
            revision_id=outcome.revision_id,
            scope="PROJECT",
            key=preference_key,
            value=preference_value,
            source=f"outcome:{outcome.id}",
            confidence=min(1.0, 0.5 + (0.2 if outcome.accepted else -0.1)),
        )
        return saved, await self.save(preference)

    @staticmethod
    def resolve_preference(
        explicit: Any = None,
        locked: Any = None,
        policy: Any = None,
        learned: Any = None,
    ) -> Any:
        """Apply the P2 authority law without allowing learned data to win."""

        for value in (explicit, locked, policy, learned):
            if value is not None:
                return value
        return None

    @staticmethod
    def recover_lease(lease: DispatchLease, *, worker_id: str) -> DispatchLease:
        return lease.model_copy(
            update={"worker_id": worker_id, "state": "RECOVERED", "created_at": _now()}
        )


__all__ = [
    "RECORD_TYPES",
    "AdaptiveCrew",
    "AntiTheaterEvidence",
    "ConflictResolution",
    "CreativePreference",
    "CreativePreferenceProfile",
    "CrewProposal",
    "CrewRole",
    "DispatchLease",
    "EvaluationCase",
    "EvaluationResult",
    "LocalizationTrack",
    "NLEOperation",
    "PluginManifest",
    "PluginPermission",
    "PluginProposal",
    "ProductionIntelligenceService",
    "ProductionOutcome",
    "ReviewThread",
    "RightsLedgerEntry",
    "SpatialConstraint",
]
