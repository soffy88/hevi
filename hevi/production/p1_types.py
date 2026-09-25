"""HEVI P1 Content Production Quality — extended canonical types.

This module implements the P1 visual narrative chain extensions:
VisualIntent → VisualBeatPlan → AssetFitness → ShotRole → MotionPurpose
→ EditPlan → ContinuityPlan → InformationGain → NarrativeArc

All types are extensions of existing P0 infrastructure, not replacements.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ──────────────────────────────────────────────────────────────────────
# SEMANTIC ACTION MODEL
# ──────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SemanticAction:
    """Parsed semantic action from narration segment."""
    action_type: str  # ENTITY, ACTION, STATE_CHANGE, RELATIONSHIP, PROCESS, SCALE, LOCATION, CAUSE_EFFECT, COMPARISON
    subject: str
    verb: str
    object: str | None = None
    state_from: str | None = None
    state_to: str | None = None
    relationship: str | None = None
    magnitude: str | None = None
    location: str | None = None
    confidence: float = 1.0
    raw_text: str = ""

    def requires_motion(self) -> bool:
        """Whether this action requires purposeful visual motion."""
        return self.action_type in {"ACTION", "PROCESS", "STATE_CHANGE", "CAUSE_EFFECT", "SCALE", "LOCATION"}

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ──────────────────────────────────────────────────────────────────────
# VISUAL BEAT
# ──────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class VisualBeat:
    """A single visual beat: what the viewer should see RIGHT NOW."""
    beat_id: str
    timeline_start_s: float
    timeline_end_s: float
    narration_span: str  # exact narration substring
    intent_id: str  # links to VisualIntent

    # Semantic requirements
    semantic_action: SemanticAction | None = None
    semantic_subject: str = ""
    semantic_state_change: str = ""
    required_visual: str = ""
    preferred_visual: str = ""
    forbidden_visual: tuple[str, ...] = field(default_factory=tuple)

    # Shot & motion
    shot_role: str = "EXPLAIN"  # ESTABLISH, REVEAL, EXPLAIN, FOLLOW, DETAIL, COMPARE, TRANSITION, PAYOFF
    motion_purpose: str = "REVEAL_STRUCTURE"  # REVEAL_STRUCTURE, FOLLOW_SUBJECT, SHOW_ORBIT, etc.

    # Asset requirements
    asset_requirements: list[dict[str, Any]] = field(default_factory=list)
    continuity_from: str | None = None  # previous beat_id
    continuity_to: str | None = None    # next beat_id

    # Narrative
    information_gain: str = ""  # NEW_ENTITY, NEW_ACTION, NEW_STATE, NEW_RELATIONSHIP, NEW_SCALE, NEW_LOCATION, NEW_DETAIL
    importance: float = 1.0     # 0.0-1.0
    narrative_phase: str = "DEVELOPMENT"  # HOOK, ORIENTATION, DEVELOPMENT, ESCALATION, PAYOFF

    # Lineage
    revision: int = 1
    created_at: str = field(default_factory=_now)

    def duration_s(self) -> float:
        return max(0.0, self.timeline_end_s - self.timeline_start_s)

    def requires_semantic_motion(self) -> bool:
        return self.semantic_action is not None and self.semantic_action.requires_motion()

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if self.semantic_action:
            d["semantic_action"] = self.semantic_action.to_dict()
        return d


@dataclass
class VisualBeatPlan:
    """Complete visual beat plan for a production."""
    production_id: str
    beats: list[VisualBeat] = field(default_factory=list)
    total_duration_s: float = 0.0
    revision: int = 1
    created_at: str = field(default_factory=_now)

    def add_beat(self, beat: VisualBeat) -> None:
        self.beats.append(beat)
        self.total_duration_s = max(self.total_duration_s, beat.timeline_end_s)

    def to_dict(self) -> dict[str, Any]:
        return {
            "production_id": self.production_id,
            "beats": [b.to_dict() for b in self.beats],
            "total_duration_s": self.total_duration_s,
            "revision": self.revision,
            "created_at": self.created_at,
        }


# ──────────────────────────────────────────────────────────────────────
# ASSET FITNESS
# ──────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class AssetFitness:
    """Multi-dimensional asset fitness for a specific VisualBeat."""
    asset_id: str
    beat_id: str

    entity_score: float      # 0-1: does asset show the right entity?
    action_score: float      # 0-1: does asset show the right action/process?
    state_score: float       # 0-1: does asset show the right state?
    temporal_score: float    # 0-1: is asset temporally appropriate?
    shot_role_score: float   # 0-1: does asset fit the shot role?
    motion_score: float      # 0-1: does asset support required motion?
    provenance_score: float  # 0-1: is provenance verified?

    overall: float = 0.0

    def __post_init__(self):
        object.__setattr__(self, "overall", round(
            (self.entity_score * 0.25 +
             self.action_score * 0.25 +
             self.state_score * 0.15 +
             self.temporal_score * 0.10 +
             self.shot_role_score * 0.10 +
             self.motion_score * 0.10 +
             self.provenance_score * 0.05), 3))

    def is_semantic_match(self, threshold: float = 0.7) -> bool:
        """Whether asset is a genuine semantic match for this beat."""
        return self.overall >= threshold

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ──────────────────────────────────────────────────────────────────────
# SHOT ROLE
# ──────────────────────────────────────────────────────────────────────

SHOT_ROLES: tuple[str, ...] = (
    "ESTABLISH",      # establish space/environment
    "REVEAL",         # reveal subject/detail
    "EXPLAIN",        # explain concept/process
    "FOLLOW",         # follow action/motion
    "DETAIL",         # show critical detail
    "COMPARE",        # compare/contrast
    "TRANSITION",     # transition context
    "PAYOFF",         # visual payoff/climax
)

ROLE_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "ESTABLISH": ("REVEAL", "EXPLAIN", "FOLLOW"),
    "REVEAL": ("EXPLAIN", "DETAIL", "FOLLOW", "COMPARE"),
    "EXPLAIN": ("FOLLOW", "DETAIL", "COMPARE", "TRANSITION"),
    "FOLLOW": ("DETAIL", "COMPARE", "PAYOFF", "TRANSITION"),
    "DETAIL": ("COMPARE", "PAYOFF", "TRANSITION"),
    "COMPARE": ("PAYOFF", "TRANSITION", "EXPLAIN"),
    "TRANSITION": ("ESTABLISH", "REVEAL", "EXPLAIN"),
    "PAYOFF": ("TRANSITION", "ESTABLISH"),
}


@dataclass(frozen=True)
class ShotRoleSpec:
    """Shot role with constraints."""
    role: str
    framing_preference: tuple[str, ...] = ("medium", "wide")
    duration_range_s: tuple[float, float] = (2.0, 6.0)
    requires_motion: bool = True
    preferred_motion: tuple[str, ...] = ()
    forbidden_motion: tuple[str, ...] = ()

    def validate_transition(self, from_role: str | None) -> bool:
        if from_role is None:
            return self.role == "ESTABLISH" or self.role == "HOOK"
        return self.role in ROLE_TRANSITIONS.get(from_role, ())


# ──────────────────────────────────────────────────────────────────────
# MOTION PURPOSE
# ──────────────────────────────────────────────────────────────────────

MOTION_PURPOSES: tuple[str, ...] = (
    "REVEAL_STRUCTURE",    # reveal spatial/structural layout
    "FOLLOW_SUBJECT",      # follow moving subject
    "SHOW_ORBIT",          # show orbital motion
    "SHOW_COLLAPSE",       # show collapse/formation
    "SHOW_SCALE",          # show relative scale
    "FOCUS_DETAIL",        # focus on critical detail
    "CONNECT_RELATIONSHIP", # connect two entities
    "COMPARE_STATE",       # compare before/after
    "TRANSITION_CONTEXT",  # transition between contexts
)

MOTION_PURPOSE_TO_BEAT: dict[str, tuple[str, ...]] = {
    "REVEAL_STRUCTURE": ("ESTABLISH", "REVEAL"),
    "FOLLOW_SUBJECT": ("FOLLOW",),
    "SHOW_ORBIT": ("EXPLAIN", "FOLLOW"),
    "SHOW_COLLAPSE": ("EXPLAIN", "PAYOFF"),
    "SHOW_SCALE": ("DETAIL", "COMPARE"),
    "FOCUS_DETAIL": ("DETAIL",),
    "CONNECT_RELATIONSHIP": ("COMPARE", "EXPLAIN"),
    "COMPARE_STATE": ("COMPARE",),
    "TRANSITION_CONTEXT": ("TRANSITION",),
}


# ──────────────────────────────────────────────────────────────────────
# EDIT PLAN
# ──────────────────────────────────────────────────────────────────────

CUT_REASONS: tuple[str, ...] = (
    "NEW_INFORMATION",
    "SUBJECT_CHANGE",
    "ACTION_CHANGE",
    "SCALE_CHANGE",
    "CAUSE_EFFECT",
    "COMPARE",
    "PAYOFF",
    "TEMPORAL_CHANGE",
)

TRANSITION_TYPES: tuple[str, ...] = (
    "CUT",
    "FADE",
    "CROSSFADE",
    "MATCH",
    "MOTION",
)


@dataclass(frozen=True)
class EditDecision:
    """Single edit decision between two beats/shots."""
    from_beat_id: str
    to_beat_id: str
    cut_reason: str  # must be in CUT_REASONS
    transition: str = "CUT"  # must be in TRANSITION_TYPES
    continuity_links: list[str] = field(default_factory=list)


@dataclass
class EditPlan:
    """Complete edit plan for a production."""
    production_id: str
    ordered_beats: list[str] = field(default_factory=list)  # beat_ids in order
    edit_decisions: list[EditDecision] = field(default_factory=list)
    revision: int = 1
    created_at: str = field(default_factory=_now)

    def add_transition(self, decision: EditDecision) -> None:
        self.edit_decisions.append(decision)

    def to_dict(self) -> dict[str, Any]:
        return {
            "production_id": self.production_id,
            "ordered_beats": self.ordered_beats,
            "edit_decisions": [asdict(d) for d in self.edit_decisions],
            "revision": self.revision,
            "created_at": self.created_at,
        }


# ──────────────────────────────────────────────────────────────────────
# CONTINUITY
# ──────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ContinuityCheck:
    """Continuity check between two adjacent shots/beats."""
    from_beat_id: str
    to_beat_id: str

    subject_continuous: bool
    spatial_continuous: bool
    temporal_continuous: bool
    motion_continuous: bool
    scale_continuous: bool
    style_continuous: bool

    change_type: str | None = None  # CONTINUATION, DETAIL, ANGLE_CHANGE, STATE_CHANGE, NONE

    def is_coherent(self) -> bool:
        return (
            self.subject_continuous or self.change_type in {"DETAIL", "ANGLE_CHANGE", "SUBJECT_CHANGE", "STATE_CHANGE"}
        ) and (
            self.spatial_continuous or self.change_type != "NONE"
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ContinuityPlan:
    """Continuity plan for a production."""
    production_id: str
    checks: list[ContinuityCheck] = field(default_factory=list)
    coherent_variety_score: float = 1.0
    revision: int = 1
    created_at: str = field(default_factory=_now)

    def add_check(self, check: ContinuityCheck) -> None:
        self.checks.append(check)

    def to_dict(self) -> dict[str, Any]:
        return {
            "production_id": self.production_id,
            "checks": [c.to_dict() for c in self.checks],
            "coherent_variety_score": self.coherent_variety_score,
            "revision": self.revision,
            "created_at": self.created_at,
        }


# ──────────────────────────────────────────────────────────────────────
# INFORMATION GAIN
# ──────────────────────────────────────────────────────────────────────

INFORMATION_GAIN_TYPES: tuple[str, ...] = (
    "NEW_ENTITY",
    "NEW_ACTION",
    "NEW_STATE",
    "NEW_RELATIONSHIP",
    "NEW_SCALE",
    "NEW_LOCATION",
    "NEW_DETAIL",
)


@dataclass(frozen=True)
class InformationGain:
    """Information gain for a visual beat."""
    beat_id: str
    gains: tuple[str, ...]  # from INFORMATION_GAIN_TYPES
    is_key_beat: bool = False

    def has_gain(self) -> bool:
        return len(self.gains) > 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class InformationGainPlan:
    """Information gain plan across all beats."""
    production_id: str
    gains: list[InformationGain] = field(default_factory=list)
    low_info_sequences: list[tuple[int, int]] = field(default_factory=list)  # (start_idx, end_idx)

    def add_gain(self, gain: InformationGain) -> None:
        self.gains.append(gain)

    def compute_low_info_sequences(self, max_consecutive_zero: int = 2) -> None:
        """Detect consecutive beats with zero information gain."""
        zero_count = 0
        start = None
        for i, g in enumerate(self.gains):
            if not g.has_gain():
                if zero_count == 0:
                    start = i
                zero_count += 1
            else:
                if zero_count >= max_consecutive_zero and start is not None:
                    self.low_info_sequences.append((start, i - 1))
                zero_count = 0
                start = None
        if zero_count >= max_consecutive_zero and start is not None:
            self.low_info_sequences.append((start, len(self.gains) - 1))

    def to_dict(self) -> dict[str, Any]:
        return {
            "production_id": self.production_id,
            "gains": [g.to_dict() for g in self.gains],
            "low_info_sequences": self.low_info_sequences,
        }


# ──────────────────────────────────────────────────────────────────────
# NARRATIVE ARC
# ──────────────────────────────────────────────────────────────────────

NARRATIVE_PHASES: tuple[str, ...] = (
    "HOOK",
    "ORIENTATION",
    "DEVELOPMENT",
    "ESCALATION",
    "PAYOFF",
)

PHASE_MIN_BEATS: dict[str, int] = {
    "HOOK": 1,
    "ORIENTATION": 1,
    "DEVELOPMENT": 2,
    "ESCALATION": 1,
    "PAYOFF": 1,
}


@dataclass(frozen=True)
class NarrativePhase:
    phase: str
    beat_indices: tuple[int, ...]  # inclusive start, end
    key_beat_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class NarrativeArc:
    """Narrative arc for a production."""
    production_id: str
    phases: list[NarrativePhase] = field(default_factory=list)
    revision: int = 1
    created_at: str = field(default_factory=_now)

    def assign_phases(self, beats: list[VisualBeat]) -> None:
        """Auto-assign narrative phases based on beat importance/position."""
        if not beats:
            return
        n = len(beats)
        
        # For 5+ beats: each phase gets its own beat range
        if n >= 5:
            self.phases.append(NarrativePhase(
                phase="HOOK",
                beat_indices=(0, 0),
                key_beat_id=beats[0].beat_id if beats else None,
            ))
            self.phases.append(NarrativePhase(
                phase="ORIENTATION",
                beat_indices=(1, 1),
                key_beat_id=beats[1].beat_id if len(beats) > 1 else None,
            ))
            self.phases.append(NarrativePhase(
                phase="DEVELOPMENT",
                beat_indices=(2, n - 3),
                key_beat_id=beats[2].beat_id if len(beats) > 2 else None,
            ))
            self.phases.append(NarrativePhase(
                phase="ESCALATION",
                beat_indices=(n - 2, n - 2),
                key_beat_id=beats[n - 2].beat_id if len(beats) > n - 2 else None,
            ))
            self.phases.append(NarrativePhase(
                phase="PAYOFF",
                beat_indices=(n - 1, n - 1),
                key_beat_id=beats[n - 1].beat_id if len(beats) > n - 1 else None,
            ))
            return
        
        # For 4 beats: explicitly add all 5 phases
        if n == 4:
            self.phases.append(NarrativePhase(
                phase="HOOK",
                beat_indices=(0, 0),
                key_beat_id=beats[0].beat_id if beats else None,
            ))
            self.phases.append(NarrativePhase(
                phase="ORIENTATION",
                beat_indices=(1, 1),
                key_beat_id=beats[1].beat_id if len(beats) > 1 else None,
            ))
            self.phases.append(NarrativePhase(
                phase="DEVELOPMENT",
                beat_indices=(2, 2),
                key_beat_id=beats[2].beat_id if len(beats) > 2 else None,
            ))
            self.phases.append(NarrativePhase(
                phase="ESCALATION",
                beat_indices=(2, 2),
                key_beat_id=beats[2].beat_id if len(beats) > 2 else None,
            ))
            self.phases.append(NarrativePhase(
                phase="PAYOFF",
                beat_indices=(3, 3),
                key_beat_id=beats[3].beat_id if len(beats) > 3 else None,
            ))
            return
        
        # For 3 beats: HOOK, DEVELOPMENT+ESCALATION combined, PAYOFF
        if n >= 3:
            self.phases.append(NarrativePhase(
                phase="HOOK",
                beat_indices=(0, 0),
                key_beat_id=beats[0].beat_id if beats else None,
            ))
            self.phases.append(NarrativePhase(
                phase="DEVELOPMENT",
                beat_indices=(1, 1),
                key_beat_id=beats[1].beat_id if len(beats) > 1 else None,
            ))
            self.phases.append(NarrativePhase(
                phase="ESCALATION",
                beat_indices=(1, 1),
                key_beat_id=beats[1].beat_id if len(beats) > 1 else None,
            ))
            self.phases.append(NarrativePhase(
                phase="PAYOFF",
                beat_indices=(2, 2),
                key_beat_id=beats[2].beat_id if len(beats) > 2 else None,
            ))
            return
        
        # 1-2 beats: just HOOK and PAYOFF
        self.phases.append(NarrativePhase(
            phase="HOOK",
            beat_indices=(0, 0),
            key_beat_id=beats[0].beat_id if beats else None,
        ))
        if n >= 2:
            self.phases.append(NarrativePhase(
                phase="PAYOFF",
                beat_indices=(n - 1, n - 1),
                key_beat_id=beats[n - 1].beat_id if len(beats) > n - 1 else None,
            ))

    def validate(self) -> list[str]:
        """Validate narrative arc completeness."""
        issues = []
        present = {p.phase for p in self.phases}
        issues.extend([f"missing phase: {req}" for req in NARRATIVE_PHASES if req not in present])
        return issues

    def to_dict(self) -> dict[str, Any]:
        return {
            "phases": [p.to_dict() for p in self.phases],
            "revision": 1,
        }


# ──────────────────────────────────────────────────────────────────────
# ASSET COVERAGE
# ──────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class AssetCoverage:
    """Asset coverage metrics for a production."""
    total_beats: int
    supported_beats: int
    unsupported_beats: int
    unique_primary_assets: int
    reused_primary_assets: int
    max_consecutive_reuse: int
    semantic_coverage_ratio: float

    # Beat-level
    beat_support: dict[str, bool] = field(default_factory=dict)
    beat_asset_ids: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ──────────────────────────────────────────────────────────────────────
# P1 PRODUCTION STATE
# ──────────────────────────────────────────────────────────────────────

@dataclass
class P1ProductionState:
    """Extended production state with P1 visual narrative."""
    # P0 base (injected from P0 pipeline)
    production_id: str
    narration: str
    topic: str
    language: str = "en-US"
    voice: str = "en-US-AriaNeural"

    # P0 artifacts
    audio_lock: Any = None
    timeline_lock: Any = None
    visual_intents: list[Any] = field(default_factory=list)
    resolved_assets: list[Any] = field(default_factory=list)
    shot_plans: list[Any] = field(default_factory=list)
    motion_plans: list[Any] = field(default_factory=list)

    # P1 artifacts
    visual_beat_plan: Any = None
    asset_fitnesses: list[Any] = field(default_factory=list)
    edit_plan: Any = None
    continuity_plan: Any = None
    information_gain_plan: Any = None
    narrative_arc: Any = None
    asset_coverage: Any = None

    # Gate report (extended)
    report: Any = None  # ProductionGateReport with P1 gates

    # Proof/final artifacts
    proof_mp4: str = ""
    final_mp4: str = ""

    def __post_init__(self):
        from hevi.production.p0_pipeline import ProductionGateReport
        if self.report is None:
            self.report = ProductionGateReport(production_id=self.production_id)


__all__ = [
    "CUT_REASONS",
    "INFORMATION_GAIN_TYPES",
    "MOTION_PURPOSES",
    "MOTION_PURPOSE_TO_BEAT",
    "NARRATIVE_PHASES",
    "PHASE_MIN_BEATS",
    "ROLE_TRANSITIONS",
    "SHOT_ROLES",
    "TRANSITION_TYPES",
    "AssetCoverage",
    "AssetFitness",
    "ContinuityCheck",
    "ContinuityPlan",
    "EditDecision",
    "EditPlan",
    "InformationGain",
    "InformationGainPlan",
    "NarrativeArc",
    "NarrativePhase",
    "P1ProductionState",
    "SemanticAction",
    "ShotRoleSpec",
    "VisualBeat",
    "VisualBeatPlan",
]
