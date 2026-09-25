"""HEVI P3 — Autonomous Production Runtime canonical types.

Mission → Chapters → Segments → Beats → Shots hierarchy with durable
state, plan graph, research/script artifacts, budget, provider policy,
artifact lifecycle, and delivery manifest. Orchestration only; all media
production delegates to the canonical P0/P1/P2 chain.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class MissionStatus(StrEnum):
    CREATED = "CREATED"
    PLANNING = "PLANNING"
    RESEARCHING = "RESEARCHING"
    SCRIPTING = "SCRIPTING"
    PLANNED = "PLANNED"
    PRODUCING = "PRODUCING"
    QA = "QA"
    REPAIRING = "REPAIRING"
    FINALIZING = "FINALIZING"
    COMPLETED = "COMPLETED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


_MISSION_TRANSITIONS: dict[str, frozenset[str]] = {
    "CREATED": frozenset({"PLANNING", "CANCELLED"}),
    "PLANNING": frozenset({"RESEARCHING", "BLOCKED", "FAILED", "CANCELLED"}),
    "RESEARCHING": frozenset({"SCRIPTING", "BLOCKED", "FAILED", "CANCELLED"}),
    "SCRIPTING": frozenset({"PLANNED", "BLOCKED", "FAILED", "CANCELLED"}),
    "PLANNED": frozenset({"PRODUCING", "BLOCKED", "FAILED", "CANCELLED"}),
    "PRODUCING": frozenset({"QA", "REPAIRING", "BLOCKED", "FAILED", "CANCELLED"}),
    "QA": frozenset({"FINALIZING", "REPAIRING", "BLOCKED", "FAILED", "CANCELLED"}),
    "REPAIRING": frozenset({"QA", "PRODUCING", "BLOCKED", "FAILED", "CANCELLED"}),
    "FINALIZING": frozenset({"REPAIRING", "COMPLETED", "BLOCKED", "FAILED", "CANCELLED"}),
    "COMPLETED": frozenset({"REPAIRING", "COMPLETED"}),
    "BLOCKED": frozenset({"PLANNING", "RESEARCHING", "SCRIPTING", "PLANNED", "PRODUCING", "QA", "REPAIRING", "FINALIZING", "FAILED", "CANCELLED"}),
    "FAILED": frozenset({"FAILED"}),
    "CANCELLED": frozenset({"CANCELLED"}),
}


def validate_mission_transition(previous: str, current: str) -> None:
    if previous == current:
        return
    allowed = _MISSION_TRANSITIONS.get(previous)
    if allowed is None or current not in allowed:
        raise ValueError(f"invalid mission transition: {previous!r} -> {current!r}")


class NodeKind(StrEnum):
    RESEARCH = "RESEARCH"
    SCRIPT = "SCRIPT"
    AUDIO = "AUDIO"
    ALIGNMENT = "ALIGNMENT"
    VISUAL_PLAN = "VISUAL_PLAN"
    ASSET = "ASSET"
    SHOT = "SHOT"
    MOTION = "MOTION"
    EDIT = "EDIT"
    RENDER = "RENDER"
    QA = "QA"
    REPAIR = "REPAIR"
    DELIVERY = "DELIVERY"


class NodeStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    CANCELLED = "CANCELLED"
    SKIPPED = "SKIPPED"


class ArtifactStatus(StrEnum):
    VALID = "VALID"
    STALE = "STALE"
    FAILED = "FAILED"
    SUPERSEDED = "SUPERSEDED"


@dataclass
class ArtifactRecord:
    artifact_id: str
    type: str
    revision: int = 1
    producer: str = ""
    parents: tuple[str, ...] = ()
    hash: str = ""
    status: str = "VALID"
    created_at: str = field(default_factory=_now)
    provenance: dict[str, Any] = field(default_factory=dict)
    path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SourceRecord:
    source_id: str
    title: str
    uri: str = ""
    source_type: str = "REFERENCE"
    verified: bool = False
    verification_method: str = ""


@dataclass
class ClaimRecord:
    claim_id: str
    statement: str
    source_ids: tuple[str, ...] = ()
    verified: bool = False
    kind: str = "fact"  # fact | paraphrase | original_expression


@dataclass
class ResearchBundle:
    bundle_id: str
    sources: list[SourceRecord] = field(default_factory=list)
    claims: list[ClaimRecord] = field(default_factory=list)
    asset_leads: list[str] = field(default_factory=list)
    revision: int = 1

    def unverified_fact_claims(self) -> list[ClaimRecord]:
        return [c for c in self.claims if c.kind == "fact" and not c.verified]

    def to_dict(self) -> dict[str, Any]:
        return {"bundle_id": self.bundle_id, "revision": self.revision,
                "sources": [asdict(s) for s in self.sources],
                "claims": [asdict(c) for c in self.claims],
                "asset_leads": list(self.asset_leads)}


@dataclass
class NarrationBlock:
    block_id: str
    text: str
    kind: str = "narration"  # narration | quotation | paraphrase
    source_ids: tuple[str, ...] = ()
    verified: bool = True


@dataclass
class ScriptSection:
    section_id: str
    title: str
    blocks: list[NarrationBlock] = field(default_factory=list)
    profile_phase: str = "DEVELOPMENT"


@dataclass
class ScriptDocument:
    script_id: str
    sections: list[ScriptSection] = field(default_factory=list)
    revision: int = 1
    research_bundle_id: str = ""
    profile_id: str = ""

    def narration_text(self) -> str:
        return " ".join(b.text for s in self.sections for b in s.blocks)

    def unverified_quotes(self) -> list[NarrationBlock]:
        return [b for s in self.sections for b in s.blocks if b.kind == "quotation" and not b.verified]

    def to_dict(self) -> dict[str, Any]:
        return {"script_id": self.script_id, "revision": self.revision,
                "research_bundle_id": self.research_bundle_id, "profile_id": self.profile_id,
                "sections": [{"section_id": s.section_id, "title": s.title,
                              "profile_phase": s.profile_phase,
                              "blocks": [asdict(b) for b in s.blocks]} for s in self.sections]}


@dataclass
class PlanNode:
    node_id: str
    kind: str
    label: str = ""
    dependencies: tuple[str, ...] = ()
    status: str = "PENDING"
    attempts: int = 0
    max_attempts: int = 3
    artifact_ids: tuple[str, ...] = ()
    error: str = ""
    estimated_cost_usd: float = 0.0
    actual_cost_usd: float = 0.0
    idempotency_key: str = ""
    segment_index: int = -1
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProductionPlan:
    plan_id: str
    nodes: list[PlanNode] = field(default_factory=list)
    revision: int = 1

    def node(self, node_id: str) -> PlanNode | None:
        return next((n for n in self.nodes if n.node_id == node_id), None)

    def ready_nodes(self) -> list[PlanNode]:
        done = {n.node_id for n in self.nodes if n.status == "COMPLETED"}
        return [n for n in self.nodes
                if n.status == "PENDING"
                and all(d in done for d in n.dependencies)]

    def required_incomplete(self) -> list[PlanNode]:
        return [n for n in self.nodes if n.status not in ("COMPLETED", "SKIPPED", "CANCELLED")]

    def to_dict(self) -> dict[str, Any]:
        return {"plan_id": self.plan_id, "revision": self.revision,
                "nodes": [n.to_dict() for n in self.nodes]}


@dataclass
class ProductionSegment:
    segment_index: int
    chapter_index: int
    narration: str
    status: str = "PENDING"
    segment_run_dir: str = ""
    final_mp4: str = ""
    report: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProductionChapter:
    chapter_index: int
    title: str
    segments: list[ProductionSegment] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"chapter_index": self.chapter_index, "title": self.title,
                "segments": [s.to_dict() for s in self.segments]}


@dataclass
class ProviderPolicy:
    preferred_provider: str = ""
    fallback_providers: tuple[str, ...] = ()
    cost_ceiling_usd: float = 0.0
    quality_floor: str = ""
    retry_max: int = 2
    timeout_s: int = 300

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProviderDecision:
    requested_provider: str = ""
    resolved_provider: str = ""
    fallback_reason: str = ""
    cost_usd: float = 0.0
    latency_s: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProductionBudget:
    max_total_cost_usd: float = 0.0
    estimated_cost_usd: float = 0.0
    actual_cost_usd: float = 0.0

    @property
    def remaining_usd(self) -> float:
        return self.max_total_cost_usd - self.actual_cost_usd

    def check(self, additional: float = 0.0) -> tuple[bool, str]:
        if self.actual_cost_usd + additional > self.max_total_cost_usd:
            return False, "BUDGET_BLOCKED"
        return True, ""

    def to_dict(self) -> dict[str, Any]:
        return {"max_total_cost_usd": self.max_total_cost_usd,
                "estimated_cost_usd": self.estimated_cost_usd,
                "actual_cost_usd": self.actual_cost_usd,
                "remaining_usd": self.remaining_usd}


@dataclass
class DeliveryManifest:
    mission_id: str
    final_mp4: str = ""
    proof_mp4: str = ""
    captions: str = ""
    thumbnail: str = ""
    production_report: str = ""
    source_manifest: str = ""
    artifact_manifest: str = ""
    editable_project: str = ""
    hashes: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProductionMission:
    mission_id: str
    request: str = ""
    profile_id: str = ""
    production_goal: str = ""
    target_duration_s: float = 0.0
    status: str = "CREATED"
    revision: int = 1
    artifact_root: str = ""
    quality_policy: dict[str, Any] = field(default_factory=dict)
    provider_policy: ProviderPolicy = field(default_factory=ProviderPolicy)
    budget: ProductionBudget = field(default_factory=ProductionBudget)
    research_bundle: ResearchBundle | None = None
    script: ScriptDocument | None = None
    plan: ProductionPlan | None = None
    chapters: list[ProductionChapter] = field(default_factory=list)
    artifacts: dict[str, ArtifactRecord] = field(default_factory=dict)
    delivery: DeliveryManifest | None = None
    repair_count: int = 0
    no_progress_streak: int = 0
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    def set_status(self, status: str) -> None:
        validate_mission_transition(self.status, status)
        self.status = status
        self.updated_at = _now()

    def to_dict(self) -> dict[str, Any]:
        return {
            "mission_id": self.mission_id, "request": self.request,
            "profile_id": self.profile_id, "production_goal": self.production_goal,
            "target_duration_s": self.target_duration_s, "status": self.status,
            "revision": self.revision, "artifact_root": self.artifact_root,
            "quality_policy": self.quality_policy,
            "provider_policy": self.provider_policy.to_dict(),
            "budget": self.budget.to_dict(),
            "research_bundle": self.research_bundle.to_dict() if self.research_bundle else None,
            "script": self.script.to_dict() if self.script else None,
            "plan": self.plan.to_dict() if self.plan else None,
            "chapters": [c.to_dict() for c in self.chapters],
            "artifacts": {k: v.to_dict() for k, v in self.artifacts.items()},
            "delivery": self.delivery.to_dict() if self.delivery else None,
            "repair_count": self.repair_count, "no_progress_streak": self.no_progress_streak,
            "created_at": self.created_at, "updated_at": self.updated_at,
        }


P3_GATES = (
    "MISSION_STATE_MACHINE",
    "AUTONOMOUS_PLANNING",
    "PRODUCTION_GRAPH",
    "FAN_OUT",
    "FAN_IN",
    "LONG_FORM_SEGMENTATION",
    "RESEARCH_GROUNDING",
    "SCRIPT_LINEAGE",
    "TARGETED_REPAIR",
    "NO_PROGRESS_DETECTION",
    "PROVIDER_POLICY",
    "BUDGET_CONTROL",
    "ARTIFACT_LIFECYCLE",
    "MISSION_RESUME",
    "CANCELLATION",
    "IDEMPOTENCY",
    "GLOBAL_CONTINUITY",
    "DELIVERY_MANIFEST",
    "OBSERVABILITY",
    "LONG_TASK",
)

ADVERSARIAL_P3_GATES = (
    "CASE_P3_1_WORKER_CRASH_RESUME",
    "CASE_P3_2_PROVIDER_FAILURE",
    "CASE_P3_3_SEGMENT_ONLY_REPAIR",
    "CASE_P3_4_STALE_INVALIDATION",
    "CASE_P3_5_MISSION_RESTART",
    "CASE_P3_6_CLEAN_CANCEL",
    "CASE_P3_7_BUDGET_BLOCKED",
    "CASE_P3_8_COMPLETION_BLOCKED",
    "CASE_P3_9_GLOBAL_CONTINUITY_BLOCKS",
    "CASE_P3_10_SILENT_FALLBACK",
    "CASE_P3_11_DEDUPLICATED",
    "CASE_P3_12_NO_PROGRESS_BLOCKED",
)

__all__ = [
    "ADVERSARIAL_P3_GATES",
    "P3_GATES",
    "ArtifactRecord",
    "ArtifactStatus",
    "ClaimRecord",
    "DeliveryManifest",
    "MissionStatus",
    "NarrationBlock",
    "NodeKind",
    "NodeStatus",
    "PlanNode",
    "ProductionBudget",
    "ProductionChapter",
    "ProductionMission",
    "ProductionPlan",
    "ProductionSegment",
    "ProviderDecision",
    "ProviderPolicy",
    "ResearchBundle",
    "ScriptDocument",
    "ScriptSection",
    "SourceRecord",
    "validate_mission_transition",
]
