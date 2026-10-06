"""Renderer-independent HEVI director contract.

This module internalizes the durable parts of stickman-video-director:
proposal/approval separation, timed beats, source fidelity, and structured
continuity. It deliberately contains no renderer-specific prompt format.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any, Literal

from hevi.creative.direction_plan.errors import PlanValidationError

AspectRatio = Literal["16:9", "9:16", "1:1"]
NarrativeStrategy = Literal[
    "MOTIVATIONAL",
    "EDUCATIONAL",
    "SCIENTIFIC",
    "HISTORICAL",
    "PRODUCT",
    "CUSTOM",
]

GLOBAL_CHANGE_FIELDS = frozenset(
    {
        "aspect_ratio",
        "duration_sec",
        "visual_style",
        "narrative_strategy",
        "narrator",
        "tone",
        "palette",
        "composition_policy",
    }
)


def _json_default(value: object) -> object:
    # is_dataclass() is also true for dataclass *classes*; asdict() on a class
    # raises TypeError, so the class case is excluded explicitly.
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    if isinstance(value, tuple):
        return list(value)
    raise TypeError(f"unsupported hash value: {type(value).__name__}")

def _stable_hash(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=_json_default)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ClaimRef:
    claim_id: str
    text: str
    source_refs: tuple[str, ...] = ()
    strength: str = "source"
    allowed_transformations: tuple[str, ...] = ()

    def validate(self) -> None:
        if not self.claim_id or not self.text:
            raise PlanValidationError("claim requires id and text", code="DIRECTOR_CLAIM_INVALID")
        if not self.source_refs:
            raise PlanValidationError(
                f"claim {self.claim_id}: source_refs required",
                code="DIRECTOR_CLAIM_UNGROUNDED",
            )
        if self.strength not in {"source", "neutral", "qualified"}:
            raise PlanValidationError(
                f"claim {self.claim_id}: invalid strength",
                code="DIRECTOR_CLAIM_STRENGTH",
            )


@dataclass(frozen=True)
class BeatSpec:
    beat_id: str
    start_sec: float
    end_sec: float
    narrative_function: str = ""
    emotional_function: str = ""
    visual_action: str = ""
    visual_devices: tuple[str, ...] = ()
    camera_intent: str = ""
    audio_intent: str = ""
    semantic_refs: tuple[str, ...] = ()

    def validate(self, *, duration_sec: float, known_claims: set[str]) -> None:
        if not self.beat_id:
            raise PlanValidationError("beat id required", code="DIRECTOR_BEAT_ID")
        if self.start_sec < 0 or self.end_sec <= self.start_sec:
            raise PlanValidationError(
                f"beat {self.beat_id}: invalid time range",
                code="DIRECTOR_BEAT_TIME",
            )
        if self.end_sec > duration_sec + 1e-6:
            raise PlanValidationError(
                f"beat {self.beat_id}: exceeds shot duration",
                code="DIRECTOR_BEAT_OVERFLOW",
            )
        if not self.visual_action:
            raise PlanValidationError(
                f"beat {self.beat_id}: visual_action required",
                code="DIRECTOR_BEAT_VISUAL_ACTION",
            )
        unknown = set(self.semantic_refs) - known_claims
        if unknown:
            raise PlanValidationError(
                f"beat {self.beat_id}: unknown semantic refs {sorted(unknown)}",
                code="DIRECTOR_BEAT_DANGLING_CLAIM",
            )


@dataclass(frozen=True)
class ContinuityAnchor:
    anchor_id: str
    kind: str
    state: str

    def validate(self) -> None:
        if not self.anchor_id or not self.kind or not self.state:
            raise PlanValidationError(
                "continuity anchor requires id, kind and state",
                code="DIRECTOR_CONTINUITY_ANCHOR",
            )


@dataclass(frozen=True)
class ContinuityContract:
    incoming: tuple[ContinuityAnchor, ...] = ()
    outgoing: tuple[ContinuityAnchor, ...] = ()

    def validate(self) -> None:
        for anchor in (*self.incoming, *self.outgoing):
            anchor.validate()


@dataclass(frozen=True)
class ShotSpec:
    shot_id: str
    duration_sec: float
    narrative_function: str
    beats: tuple[BeatSpec, ...]
    composition: str = ""
    camera_intent: str = ""
    audio_intent: str = ""
    semantic_refs: tuple[str, ...] = ()
    continuity: ContinuityContract = field(default_factory=ContinuityContract)
    renderer_constraints: tuple[str, ...] = ()

    def validate(self, known_claims: set[str]) -> None:
        if not self.shot_id:
            raise PlanValidationError("shot id required", code="DIRECTOR_SHOT_ID")
        if self.duration_sec <= 0:
            raise PlanValidationError(
                f"shot {self.shot_id}: duration must be positive",
                code="DIRECTOR_SHOT_DURATION",
            )
        if len(self.beats) < 3:
            raise PlanValidationError(
                f"shot {self.shot_id}: at least 3 beats required",
                code="DIRECTOR_BEAT_COUNT",
            )
        starts = [b.start_sec for b in self.beats]
        if abs(starts[0]) > 1e-6:
            raise PlanValidationError(
                f"shot {self.shot_id}: first beat must start at 0",
                code="DIRECTOR_BEAT_COVERAGE",
            )
        previous_end = 0.0
        for beat in self.beats:
            beat.validate(duration_sec=self.duration_sec, known_claims=known_claims)
            if abs(beat.start_sec - previous_end) > 1e-6:
                raise PlanValidationError(
                    f"shot {self.shot_id}: beat coverage gap",
                    code="DIRECTOR_BEAT_COVERAGE",
                )
            previous_end = beat.end_sec
        if abs(previous_end - self.duration_sec) > 1e-6:
            raise PlanValidationError(
                f"shot {self.shot_id}: beats do not cover duration",
                code="DIRECTOR_BEAT_COVERAGE",
            )
        unknown = set(self.semantic_refs) - known_claims
        if unknown:
            raise PlanValidationError(
                f"shot {self.shot_id}: unknown semantic refs {sorted(unknown)}",
                code="DIRECTOR_SHOT_DANGLING_CLAIM",
            )
        self.continuity.validate()


@dataclass(frozen=True)
class ContinuityEdge:
    from_shot: str
    to_shot: str
    shared_anchor_ids: tuple[str, ...]

    def validate(self, shots: dict[str, ShotSpec]) -> None:
        source = shots.get(self.from_shot)
        target = shots.get(self.to_shot)
        if source is None or target is None:
            raise PlanValidationError(
                f"continuity edge references unknown shot {self.from_shot}->{self.to_shot}",
                code="DIRECTOR_CONTINUITY_SHOT",
            )
        source_ids = {a.anchor_id for a in source.continuity.outgoing}
        target_ids = {a.anchor_id for a in target.continuity.incoming}
        if not self.shared_anchor_ids:
            raise PlanValidationError(
                f"continuity edge {self.from_shot}->{self.to_shot}: anchor required",
                code="DIRECTOR_CONTINUITY_EDGE",
            )
        if not set(self.shared_anchor_ids) <= source_ids or not set(self.shared_anchor_ids) <= target_ids:
            raise PlanValidationError(
                f"continuity edge {self.from_shot}->{self.to_shot}: anchor mismatch",
                code="DIRECTOR_CONTINUITY_MISMATCH",
            )


@dataclass(frozen=True)
class DirectorProposal:
    direction_id: str
    revision: int
    source_fingerprint: str
    aspect_ratio: AspectRatio
    duration_sec: float
    visual_style: str
    narrative_strategy: NarrativeStrategy
    narrator: str = ""
    tone: str = ""
    palette: tuple[str, ...] = ()
    composition_policy: str = ""
    claims: tuple[ClaimRef, ...] = ()
    shots: tuple[ShotSpec, ...] = ()
    continuity_edges: tuple[ContinuityEdge, ...] = ()
    proposal_hash: str = ""

    def _payload(self) -> dict[str, Any]:
        return {
            "direction_id": self.direction_id,
            "revision": self.revision,
            "source_fingerprint": self.source_fingerprint,
            "aspect_ratio": self.aspect_ratio,
            "duration_sec": self.duration_sec,
            "visual_style": self.visual_style,
            "narrative_strategy": self.narrative_strategy,
            "narrator": self.narrator,
            "tone": self.tone,
            "palette": self.palette,
            "composition_policy": self.composition_policy,
            "claims": self.claims,
            "shots": self.shots,
            "continuity_edges": self.continuity_edges,
        }

    def canonical_hash(self) -> str:
        return _stable_hash(self._payload())

    def validate(self) -> None:
        if not self.direction_id:
            raise PlanValidationError("direction_id required", code="DIRECTOR_DIRECTION_ID")
        if self.revision < 1:
            raise PlanValidationError("revision must be >= 1", code="DIRECTOR_REVISION")
        if not self.source_fingerprint:
            raise PlanValidationError(
                "source_fingerprint required",
                code="DIRECTOR_SOURCE_FINGERPRINT",
            )
        if self.duration_sec <= 0:
            raise PlanValidationError(
                "proposal duration must be positive",
                code="DIRECTOR_DURATION",
            )
        if not self.visual_style:
            raise PlanValidationError(
                "visual_style required",
                code="DIRECTOR_STYLE",
            )
        claims = {c.claim_id for c in self.claims}
        if len(claims) != len(self.claims):
            raise PlanValidationError(
                "duplicate claim id",
                code="DIRECTOR_CLAIM_DUPLICATE",
            )
        for claim in self.claims:
            claim.validate()
        if not self.shots:
            raise PlanValidationError(
                "proposal requires at least one shot",
                code="DIRECTOR_SHOT_EMPTY",
            )
        shots = {s.shot_id: s for s in self.shots}
        if len(shots) != len(self.shots):
            raise PlanValidationError(
                "duplicate shot id",
                code="DIRECTOR_SHOT_DUPLICATE",
            )
        for shot in self.shots:
            shot.validate(claims)
        total = sum(s.duration_sec for s in self.shots)
        if abs(total - self.duration_sec) > 1e-6:
            raise PlanValidationError(
                "shot durations do not match proposal duration",
                code="DIRECTOR_DURATION_MISMATCH",
            )
        for edge in self.continuity_edges:
            edge.validate(shots)
        expected = self.canonical_hash()
        if self.proposal_hash and self.proposal_hash != expected:
            raise PlanValidationError(
                "proposal_hash does not match canonical proposal",
                code="DIRECTOR_HASH_MISMATCH",
            )

    def with_hash(self) -> DirectorProposal:
        expected = self.canonical_hash()
        return DirectorProposal(
            **{
                **self._payload(),
                "proposal_hash": expected,
            }
        )


@dataclass(frozen=True)
class ApprovalBinding:
    proposal_hash: str
    revision: int
    approved_by: str

    def validate(self, proposal: DirectorProposal) -> None:
        if self.proposal_hash != proposal.canonical_hash():
            raise PlanValidationError(
                "approval binds a stale proposal",
                code="DIRECTOR_APPROVAL_STALE_HASH",
            )
        if self.revision != proposal.revision:
            raise PlanValidationError(
                "approval binds a stale revision",
                code="DIRECTOR_APPROVAL_STALE_REVISION",
            )
        if not self.approved_by:
            raise PlanValidationError(
                "approved_by required",
                code="DIRECTOR_APPROVER_MISSING",
            )


@dataclass(frozen=True)
class ProductionPlan:
    proposal_hash: str
    direction_id: str
    revision: int
    shots: tuple[ShotSpec, ...]
    continuity_edges: tuple[ContinuityEdge, ...]
    source_fingerprint: str

    def validate(self) -> None:
        if not self.proposal_hash or len(self.proposal_hash) != 64:
            raise PlanValidationError(
                "production plan requires sha256 proposal hash",
                code="DIRECTOR_PRODUCTION_HASH",
            )
        if self.revision < 1:
            raise PlanValidationError(
                "production plan revision must be >= 1",
                code="DIRECTOR_PRODUCTION_REVISION",
            )
        if not self.shots:
            raise PlanValidationError(
                "production plan requires shots",
                code="DIRECTOR_PRODUCTION_SHOTS",
            )


def compile_production_plan(
    proposal: DirectorProposal,
    approval: ApprovalBinding | None,
) -> ProductionPlan:
    proposal.validate()
    if approval is None:
        raise PlanValidationError(
            "compile requires explicit approval",
            code="DIRECTOR_APPROVAL_MISSING",
        )
    approval.validate(proposal)
    return ProductionPlan(
        proposal_hash=proposal.canonical_hash(),
        direction_id=proposal.direction_id,
        revision=proposal.revision,
        shots=proposal.shots,
        continuity_edges=proposal.continuity_edges,
        source_fingerprint=proposal.source_fingerprint,
    )


def changed_global_fields(
    previous: DirectorProposal,
    current: DirectorProposal,
) -> frozenset[str]:
    return frozenset(
        name for name in GLOBAL_CHANGE_FIELDS
        if getattr(previous, name) != getattr(current, name)
    )


__all__ = [
    "GLOBAL_CHANGE_FIELDS",
    "ApprovalBinding",
    "AspectRatio",
    "BeatSpec",
    "ClaimRef",
    "ContinuityAnchor",
    "ContinuityContract",
    "ContinuityEdge",
    "DirectorProposal",
    "NarrativeStrategy",
    "ProductionPlan",
    "ShotSpec",
    "changed_global_fields",
    "compile_production_plan",
]
