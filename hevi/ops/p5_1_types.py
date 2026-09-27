"""HEVI P5.1 — Visual Editorial Intelligence canonical types.

The editorial loop is an *extension* of the canonical chain, never a second one:

    ProductionMission
    -> Proof/Final Candidate
    -> Native Video Review
    -> Editorial Diagnosis
    -> Repair Plan
    -> Targeted Repair
    -> New Candidate
    -> Pairwise Comparison
    -> Promote / Reject / Stop
    -> Editable Delivery

Every object here is an editorial *observation* or *intent*. None of them owns
production. Production stays with P0 (correctness), P1 (VisualBeat / ShotPlan /
MotionPlan), P2 (profile creative direction), P3 (mission / RepairController /
lineage), P4 (scheduler / budget / delivery) and P5 (approval / content /
editable delivery).

P5.1 therefore adds exactly:

    video understanding, editorial diagnosis, evidence acquisition policy,
    shot presentation policy, pairwise comparison, revision convergence policy

Hard redlines enforced here (see ``docs/architecture/p5-1-visual-editorial.md``):

* No second pipeline / mission runtime / repair runtime / QA authority /
  provider registry / asset registry / delivery runtime / editable runtime /
  completion authority.
* A ``VideoReview`` is bound to a ``video_hash``; a stale review can never be
  reused after the video changes (``STALE_VIDEO_REVIEW_REUSE == 0``).
* Evidence truth is closed: a generated visualization may never be relabelled as
  a real interface, and a mock UI may never become official evidence.
* Promotion authority is the ``RevisionSession`` policy only. A reviewer never
  mutates the authoritative candidate.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import uuid4

# ── Helpers ──────────────────────────────────────────────────────────────


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _eid(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:12]}"


def video_file_hash(path: str | Path) -> str:
    """Content hash of a video file. This is the review binding key."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def canonical_hash(payload: Any) -> str:
    """Stable hash of any JSON-serialisable payload (key order independent)."""
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return f"sha256:{hashlib.sha256(blob.encode()).hexdigest()}"


# ── Review prompt / contract versioning (§49) ────────────────────────────

REVIEW_PROMPT_VERSION = "hevi.p5_1.editorial_review.v1"
PAIRWISE_PROMPT_VERSION = "hevi.p5_1.editorial_pairwise.v1"
PAIRWISE_CONTRACT_DIMENSIONS = (
    "hard_defects",
    "narrative_clarity",
    "visual_grounding",
    "information_density",
    "pacing",
    "speaker_evidence_balance",
    "motion_purpose",
    "caption_readability",
    "profile_consistency",
    "overall_watchability",
)


# ── Provider capability vocabulary (§8) ───────────────────────────────────

VIDEO_UNDERSTANDING = "VIDEO_UNDERSTANDING"
NATIVE_VIDEO_INPUT = "NATIVE_VIDEO_INPUT"


# ── Editorial issue taxonomy (§12) ───────────────────────────────────────


class EditorialIssueCategory(StrEnum):
    """Closed-but-extensible editorial issue taxonomy.

    Extensible: unknown categories observed from a reviewer are preserved as
    ``UNCLASSIFIED`` together with the raw provider label, never dropped.
    """

    PACING = "PACING"
    DEAD_AIR = "DEAD_AIR"
    VISUAL_STAGNATION = "VISUAL_STAGNATION"
    SHOT_TOO_SHORT = "SHOT_TOO_SHORT"
    SHOT_TOO_LONG = "SHOT_TOO_LONG"
    SUBJECT_JUMP = "SUBJECT_JUMP"
    LAYOUT_INSTABILITY = "LAYOUT_INSTABILITY"
    CAPTION_OCCLUSION = "CAPTION_OCCLUSION"
    CAPTION_OVERLOAD = "CAPTION_OVERLOAD"
    TEXT_DOMINANCE = "TEXT_DOMINANCE"
    WEAK_VISUAL_GROUNDING = "WEAK_VISUAL_GROUNDING"
    WRONG_EVIDENCE = "WRONG_EVIDENCE"
    FAKE_UI = "FAKE_UI"
    LOW_INFORMATION_DENSITY = "LOW_INFORMATION_DENSITY"
    EXCESSIVE_INFORMATION_DENSITY = "EXCESSIVE_INFORMATION_DENSITY"
    MOTION_DISTRACTION = "MOTION_DISTRACTION"
    MOTION_MEANINGLESS = "MOTION_MEANINGLESS"
    TRANSITION_MISMATCH = "TRANSITION_MISMATCH"
    SPEAKER_OVERUSE = "SPEAKER_OVERUSE"
    SPEAKER_UNDERUSE = "SPEAKER_UNDERUSE"
    EVIDENCE_UNDERUSE = "EVIDENCE_UNDERUSE"
    VISUAL_REPETITION = "VISUAL_REPETITION"
    STYLE_INCONSISTENCY = "STYLE_INCONSISTENCY"
    AUDIO_VISUAL_MISMATCH = "AUDIO_VISUAL_MISMATCH"
    EMOTIONAL_MISMATCH = "EMOTIONAL_MISMATCH"
    PROFILE_MISMATCH = "PROFILE_MISMATCH"
    UNCLASSIFIED = "UNCLASSIFIED"


#: Categories whose presence without a temporal range is still actionable
#: because the defect is a property of the whole cut rather than one shot.
GLOBAL_ISSUE_CATEGORIES = frozenset(
    {
        EditorialIssueCategory.STYLE_INCONSISTENCY,
        EditorialIssueCategory.PROFILE_MISMATCH,
        EditorialIssueCategory.TEXT_DOMINANCE,
        EditorialIssueCategory.AUDIO_VISUAL_MISMATCH,
    }
)


class IssueSeverity(StrEnum):
    BLOCKER = "BLOCKER"
    MAJOR = "MAJOR"
    MINOR = "MINOR"
    COSMETIC = "COSMETIC"


#: Severities allowed to drive an autonomous repair round (§13).
AUTONOMOUS_REPAIR_SEVERITIES = frozenset({IssueSeverity.BLOCKER, IssueSeverity.MAJOR})

#: Most-severe-first ordering key.
_SEVERITY_ORDER: dict[IssueSeverity, int] = {
    IssueSeverity.BLOCKER: 0,
    IssueSeverity.MAJOR: 1,
    IssueSeverity.MINOR: 2,
    IssueSeverity.COSMETIC: 3,
}

#: Provider severity vocabularies are normalised onto the canonical scale.
_SEVERITY_ALIASES: dict[str, IssueSeverity] = {
    "BLOCKER": IssueSeverity.BLOCKER,
    "CRITICAL": IssueSeverity.BLOCKER,
    "FATAL": IssueSeverity.BLOCKER,
    "MAJOR": IssueSeverity.MAJOR,
    "HIGH": IssueSeverity.MAJOR,
    "SEVERE": IssueSeverity.MAJOR,
    "MINOR": IssueSeverity.MINOR,
    "MEDIUM": IssueSeverity.MINOR,
    "LOW": IssueSeverity.MINOR,
    "COSMETIC": IssueSeverity.COSMETIC,
    "TRIVIAL": IssueSeverity.COSMETIC,
    "NIT": IssueSeverity.COSMETIC,
}


def normalize_severity(raw: str | None) -> IssueSeverity:
    """Map a provider severity label onto the canonical four-level scale."""
    if not raw:
        return IssueSeverity.MINOR
    return _SEVERITY_ALIASES.get(str(raw).strip().upper(), IssueSeverity.MINOR)


def normalize_category(raw: str | None) -> tuple[EditorialIssueCategory, str]:
    """Map a provider category label onto the taxonomy, keeping the raw label.

    Returns ``(category, raw_label)``. Unknown labels become ``UNCLASSIFIED``
    with the raw label preserved so a taxonomy extension can be audited rather
    than silently losing observations.
    """
    label = str(raw or "").strip().upper().replace(" ", "_").replace("-", "_")
    for member in EditorialIssueCategory:
        if member.value == label:
            return member, label
    return EditorialIssueCategory.UNCLASSIFIED, label or "UNSPECIFIED"


# ── Hard defect vs editorial preference (§14) ────────────────────────────


#: Flat list of every taxonomy label, used to seed reviewer prompts and audits.
EDITORIAL_ISSUE_TAXONOMY: tuple[str, ...] = tuple(
    c.value for c in EditorialIssueCategory
)


class DefectClass(StrEnum):
    HARD_DEFECT = "HARD_DEFECT"
    EDITORIAL_PREFERENCE = "EDITORIAL_PREFERENCE"


#: Hard defects are repaired directly. Each entry is
#: ``category -> (defect class, canonical artifact to map onto)``.
HARD_DEFECT_CATEGORIES: dict[EditorialIssueCategory, DefectClass] = {
    EditorialIssueCategory.CAPTION_OCCLUSION: DefectClass.HARD_DEFECT,
    EditorialIssueCategory.WRONG_EVIDENCE: DefectClass.HARD_DEFECT,
    EditorialIssueCategory.FAKE_UI: DefectClass.HARD_DEFECT,
    EditorialIssueCategory.AUDIO_VISUAL_MISMATCH: DefectClass.HARD_DEFECT,
    EditorialIssueCategory.SUBJECT_JUMP: DefectClass.HARD_DEFECT,
    EditorialIssueCategory.DEAD_AIR: DefectClass.HARD_DEFECT,
    EditorialIssueCategory.LAYOUT_INSTABILITY: DefectClass.HARD_DEFECT,
    # A claim the picture does not support is wrong evidence, not a taste
    # question: the viewer is shown something other than what is being said.
    EditorialIssueCategory.EVIDENCE_UNDERUSE: DefectClass.HARD_DEFECT,
    EditorialIssueCategory.WEAK_VISUAL_GROUNDING: DefectClass.HARD_DEFECT,
    EditorialIssueCategory.CAPTION_OCCLUSION: DefectClass.HARD_DEFECT,
}

#: Everything else defaults to an editorial preference, which routes through the
#: pairwise / convergence policy instead of a direct repair.
DEFAULT_DEFECT_CLASS = DefectClass.EDITORIAL_PREFERENCE


def classify_defect(category: EditorialIssueCategory) -> DefectClass:
    return HARD_DEFECT_CATEGORIES.get(category, DEFAULT_DEFECT_CLASS)


# ── Root cause → canonical artifact mapping (§30) ─────────────────────────


class CanonicalArtifact(StrEnum):
    """Canonical P0-P5 artifacts an editorial issue is allowed to repair.

    A diagnosis may only ever target one of these. ``TEXT_DOMINANCE`` maps onto
    the P5 caption style profile; ``WRONG_EVIDENCE`` onto a P5.1
    ``EvidenceAsset``; shot length onto the P1 ``VisualBeat``/P0 ``ShotPlan``
    timeline. It never maps onto "regenerate the whole video".
    """

    CAPTION_STYLE = "CAPTION_STYLE"
    EVIDENCE_ASSET = "EVIDENCE_ASSET"
    SHOT_PLAN = "SHOT_PLAN"
    VISUAL_BEAT = "VISUAL_BEAT"
    MOTION_PLAN = "MOTION_PLAN"
    ASSET_SELECTION = "ASSET_SELECTION"
    AUDIO_MIX = "AUDIO_MIX"
    PROFILE_DIRECTION = "PROFILE_DIRECTION"
    NONE = "NONE"


#: category -> canonical artifact to repair. A category absent from this map is
#: a preference with no canonical repair target.
ROOT_CAUSE_MAP: dict[EditorialIssueCategory, CanonicalArtifact] = {
    EditorialIssueCategory.CAPTION_OCCLUSION: CanonicalArtifact.CAPTION_STYLE,
    EditorialIssueCategory.CAPTION_OVERLOAD: CanonicalArtifact.CAPTION_STYLE,
    EditorialIssueCategory.TEXT_DOMINANCE: CanonicalArtifact.CAPTION_STYLE,
    EditorialIssueCategory.WRONG_EVIDENCE: CanonicalArtifact.EVIDENCE_ASSET,
    EditorialIssueCategory.FAKE_UI: CanonicalArtifact.EVIDENCE_ASSET,
    EditorialIssueCategory.WEAK_VISUAL_GROUNDING: CanonicalArtifact.EVIDENCE_ASSET,
    EditorialIssueCategory.EVIDENCE_UNDERUSE: CanonicalArtifact.EVIDENCE_ASSET,
    EditorialIssueCategory.SHOT_TOO_SHORT: CanonicalArtifact.SHOT_PLAN,
    EditorialIssueCategory.SHOT_TOO_LONG: CanonicalArtifact.SHOT_PLAN,
    EditorialIssueCategory.PACING: CanonicalArtifact.SHOT_PLAN,
    EditorialIssueCategory.SUBJECT_JUMP: CanonicalArtifact.SHOT_PLAN,
    EditorialIssueCategory.TRANSITION_MISMATCH: CanonicalArtifact.SHOT_PLAN,
    EditorialIssueCategory.DEAD_AIR: CanonicalArtifact.SHOT_PLAN,
    EditorialIssueCategory.LAYOUT_INSTABILITY: CanonicalArtifact.SHOT_PLAN,
    EditorialIssueCategory.VISUAL_REPETITION: CanonicalArtifact.VISUAL_BEAT,
    EditorialIssueCategory.VISUAL_STAGNATION: CanonicalArtifact.VISUAL_BEAT,
    EditorialIssueCategory.LOW_INFORMATION_DENSITY: CanonicalArtifact.VISUAL_BEAT,
    EditorialIssueCategory.EXCESSIVE_INFORMATION_DENSITY: CanonicalArtifact.VISUAL_BEAT,
    EditorialIssueCategory.MOTION_DISTRACTION: CanonicalArtifact.MOTION_PLAN,
    EditorialIssueCategory.MOTION_MEANINGLESS: CanonicalArtifact.MOTION_PLAN,
    EditorialIssueCategory.EMOTIONAL_MISMATCH: CanonicalArtifact.ASSET_SELECTION,
    EditorialIssueCategory.STYLE_INCONSISTENCY: CanonicalArtifact.PROFILE_DIRECTION,
    EditorialIssueCategory.PROFILE_MISMATCH: CanonicalArtifact.PROFILE_DIRECTION,
    EditorialIssueCategory.SPEAKER_OVERUSE: CanonicalArtifact.VISUAL_BEAT,
    EditorialIssueCategory.SPEAKER_UNDERUSE: CanonicalArtifact.VISUAL_BEAT,
    EditorialIssueCategory.AUDIO_VISUAL_MISMATCH: CanonicalArtifact.AUDIO_MIX,
}


# ── Repair scope (§33) ───────────────────────────────────────────────────


class RepairScope(StrEnum):
    ASSET_ONLY = "ASSET_ONLY"
    SHOT_ONLY = "SHOT_ONLY"
    TIMELINE_RANGE = "TIMELINE_RANGE"
    CAPTION_RANGE = "CAPTION_RANGE"
    MOTION_RANGE = "MOTION_RANGE"
    AUDIO_MIX_RANGE = "AUDIO_MIX_RANGE"
    MULTI_SHOT = "MULTI_SHOT"
    GLOBAL = "GLOBAL"


#: Scopes that must not re-run source generation (§34).
NON_REGENERATING_SCOPES = frozenset(
    {
        RepairScope.ASSET_ONLY,
        RepairScope.SHOT_ONLY,
        RepairScope.TIMELINE_RANGE,
        RepairScope.CAPTION_RANGE,
        RepairScope.MOTION_RANGE,
        RepairScope.AUDIO_MIX_RANGE,
    }
)


# ── Shot presentation roles (§21) ────────────────────────────────────────


class ShotPresentationRole(StrEnum):
    DIRECT_ADDRESS = "DIRECT_ADDRESS"
    EVIDENCE_DOMINANT = "EVIDENCE_DOMINANT"
    DEMONSTRATION = "DEMONSTRATION"
    EMOTIONAL_PRESENCE = "EMOTIONAL_PRESENCE"
    CONTEXTUAL_BROLL = "CONTEXTUAL_BROLL"
    TRANSITION = "TRANSITION"
    FULL_SCREEN_INFORMATION = "FULL_SCREEN_INFORMATION"


class SpeakerVisibility(StrEnum):
    DOMINANT = "DOMINANT"
    VISIBLE = "VISIBLE"
    SMALL_PIP = "SMALL_PIP"
    HIDDEN = "HIDDEN"


class EvidenceVisibility(StrEnum):
    DOMINANT = "DOMINANT"
    VISIBLE = "VISIBLE"
    PARTIAL = "PARTIAL"
    HIDDEN = "HIDDEN"


class ScaleLevel(StrEnum):
    FULL_FRAME = "FULL_FRAME"
    LARGE = "LARGE"
    MEDIUM = "MEDIUM"
    SMALL = "SMALL"
    NONE = "NONE"


# ── Information density (§26) ─────────────────────────────────────────────


class InformationDensity(StrEnum):
    TOO_EMPTY = "TOO_EMPTY"
    BALANCED = "BALANCED"
    TOO_DENSE = "TOO_DENSE"


# ── Evidence (§15-§19) ───────────────────────────────────────────────────


class EvidenceSourceType(StrEnum):
    OFFICIAL_SCREENSHOT = "OFFICIAL_SCREENSHOT"
    REAL_INTERFACE = "REAL_INTERFACE"
    OFFICIAL_IMAGE = "OFFICIAL_IMAGE"
    DOCUMENT_EXCERPT = "DOCUMENT_EXCERPT"
    DATA_VISUALIZATION = "DATA_VISUALIZATION"
    REAL_PHOTO = "REAL_PHOTO"
    GENERATED_VISUALIZATION = "GENERATED_VISUALIZATION"
    SYMBOLIC = "SYMBOLIC"


#: The evidence-first ladder (§15), best evidence first.
EVIDENCE_PRIORITY: tuple[EvidenceSourceType, ...] = (
    EvidenceSourceType.OFFICIAL_SCREENSHOT,
    EvidenceSourceType.REAL_INTERFACE,
    EvidenceSourceType.DOCUMENT_EXCERPT,
    EvidenceSourceType.OFFICIAL_IMAGE,
    EvidenceSourceType.DATA_VISUALIZATION,
    EvidenceSourceType.REAL_PHOTO,
    EvidenceSourceType.GENERATED_VISUALIZATION,
    EvidenceSourceType.SYMBOLIC,
)

#: Types that assert the depicted interface/artifact is the real thing. These
#: may never be satisfied by generated or symbolic material.
REALITY_ASSERTING_TYPES = frozenset(
    {
        EvidenceSourceType.OFFICIAL_SCREENSHOT,
        EvidenceSourceType.REAL_INTERFACE,
        EvidenceSourceType.OFFICIAL_IMAGE,
        EvidenceSourceType.DOCUMENT_EXCERPT,
    }
)

#: Types that can never be promoted into a reality-asserting type.
NON_REALITY_TYPES = frozenset(
    {EvidenceSourceType.GENERATED_VISUALIZATION, EvidenceSourceType.SYMBOLIC}
)


class EvidenceFreshness(StrEnum):
    FRESH = "FRESH"
    STALE_EVIDENCE = "STALE_EVIDENCE"
    UNDATED = "UNDATED"


# ── Provider failure semantics (§84) ─────────────────────────────────────


class ReviewOutcome(StrEnum):
    PASS = "PASS"
    BLOCKED_BY_PROVIDER = "BLOCKED_BY_PROVIDER"
    BLOCKED_BY_NATIVE_INPUT = "BLOCKED_BY_NATIVE_INPUT"
    BLOCKED_BY_STALE_REVIEW = "BLOCKED_BY_STALE_REVIEW"
    BLOCKED_BY_EVIDENCE_TRUTH = "BLOCKED_BY_EVIDENCE_TRUTH"
    FAILED = "FAILED"


class PairwiseVerdict(StrEnum):
    A = "A"
    B = "B"
    TIE = "TIE"
    INCOMPARABLE = "INCOMPARABLE"


class PromotionDecisionKind(StrEnum):
    PROMOTE_NEW = "PROMOTE_NEW"
    KEEP_OLD = "KEEP_OLD"
    HUMAN_REVIEW = "HUMAN_REVIEW"


class SessionStopReason(StrEnum):
    NO_BLOCKER_OR_MAJOR_ISSUES = "NO_BLOCKER_OR_MAJOR_ISSUES"
    NEW_NOT_PROMOTED = "NEW_NOT_PROMOTED"
    ONLY_MINOR_COSMETIC_REMAINS = "ONLY_MINOR_COSMETIC_REMAINS"
    MAX_REVISION_ROUNDS_REACHED = "MAX_REVISION_ROUNDS_REACHED"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    HUMAN_REVIEW_REQUIRED = "HUMAN_REVIEW_REQUIRED"
    NO_PROGRESS_DETECTED = "NO_PROGRESS_DETECTED"
    MEANINGFUL_REVISION_REFUSED = "MEANINGFUL_REVISION_REFUSED"


class HumanDecision(StrEnum):
    KEEP_V0 = "KEEP_V0"
    KEEP_V1 = "KEEP_V1"
    REJECT_ALL = "REJECT_ALL"
    REQUEST_CHANGE = "REQUEST_CHANGE"


# ── Editable layer semantics (§63, §64) ──────────────────────────────────


class EditableLayer(StrEnum):
    BACKGROUND = "BACKGROUND"
    SPEAKER = "SPEAKER"
    EVIDENCE = "EVIDENCE"
    OVERLAY = "OVERLAY"
    CAPTIONS = "CAPTIONS"
    VOICE = "VOICE"
    BGM = "BGM"
    SFX = "SFX"


#: Canonical bottom-to-top z order for the delivered project.
LAYER_Z_ORDER: dict[EditableLayer, int] = {
    EditableLayer.BACKGROUND: 0,
    EditableLayer.VOICE: 10,
    EditableLayer.BGM: 20,
    EditableLayer.SFX: 21,
    EditableLayer.EVIDENCE: 30,
    EditableLayer.SPEAKER: 40,
    EditableLayer.OVERLAY: 50,
    EditableLayer.CAPTIONS: 60,
}


# ── Editorial observation objects (§5, §11) ──────────────────────────────


@dataclass
class EditorialIssue:
    """One time-bounded editorial observation about a candidate video.

    ``start_ms``/``end_ms`` are mandatory for anything that will drive a
    shot-level repair: a visual issue with no temporal range cannot be located,
    so it can only drive a repair when the category is genuinely global.
    """

    issue_id: str = field(default_factory=lambda: _eid("issue"))
    category: EditorialIssueCategory = EditorialIssueCategory.UNCLASSIFIED
    raw_category: str = ""
    severity: IssueSeverity = IssueSeverity.MINOR
    defect_class: DefectClass = DefectClass.EDITORIAL_PREFERENCE
    start_ms: int = 0
    end_ms: int = 0
    description: str = ""
    evidence: str = ""
    confidence: float = 0.0
    repair_hint: str = ""
    shot_id: str = ""
    beat_id: str = ""
    global_scope: bool = False

    @property
    def has_temporal_range(self) -> bool:
        return self.end_ms > self.start_ms

    @property
    def duration_ms(self) -> int:
        return max(0, self.end_ms - self.start_ms)

    @property
    def severity_rank(self) -> int:
        """Sort key: most severe first."""
        return _SEVERITY_ORDER[self.severity]

    def is_locatable(self) -> bool:
        return self.has_temporal_range or self.global_scope

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TemporalObservation:
    """A provider's description of what happens in a time window."""

    start_ms: int = 0
    end_ms: int = 0
    observation: str = ""
    source: str = "PROVIDER"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class VideoReview:
    """Formal native-video review artifact, bound to an exact video hash.

    The binding is what makes stale reuse detectable: if the candidate video
    changes, ``video_hash`` stops matching and the review must be re-run.
    """

    review_id: str = field(default_factory=lambda: _eid("vrev"))
    content_id: str = ""
    candidate_id: str = ""
    video_hash: str = ""
    video_path: str = ""
    video_duration_s: float = 0.0
    provider: str = ""
    model: str = ""
    review_prompt_version: str = REVIEW_PROMPT_VERSION
    reviewed_at: str = field(default_factory=_now)
    temporal_observations: list[TemporalObservation] = field(default_factory=list)
    issues: list[EditorialIssue] = field(default_factory=list)
    summary: str = ""
    confidence: float = 0.0
    native_video_input: bool = False
    latency_s: float = 0.0
    cost_usd: float | None = None
    outcome: ReviewOutcome = ReviewOutcome.PASS
    blocked_reason: str = ""
    raw_provider_payload: dict[str, Any] = field(default_factory=dict)

    # ── Staleness (§5, adversarial A2) ──
    def is_stale_for(self, video_hash: str) -> bool:
        """A review is stale as soon as the reviewed bytes are no longer current."""
        return not video_hash or self.video_hash != video_hash

    def temporal_issue_count(self) -> int:
        return sum(1 for i in self.issues if i.has_temporal_range)

    def blocker_count(self) -> int:
        return sum(1 for i in self.issues if i.severity is IssueSeverity.BLOCKER)

    def major_count(self) -> int:
        return sum(1 for i in self.issues if i.severity is IssueSeverity.MAJOR)

    def categories(self) -> set[EditorialIssueCategory]:
        return {i.category for i in self.issues}

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["outcome"] = self.outcome.value
        return d


# ── Evidence objects (§16, §17) ──────────────────────────────────────────


@dataclass
class EvidenceRequest:
    """A request for real, verifiable evidence backing a claim."""

    request_id: str = field(default_factory=lambda: _eid("ereq"))
    claim: str = ""
    entity: str = ""
    desired_evidence_type: EvidenceSourceType = EvidenceSourceType.REAL_INTERFACE
    source_preference: str = ""
    time_context: str = ""
    required_confidence: float = 0.7
    beat_id: str = ""
    created_at: str = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EvidenceAsset:
    """Real evidence asset with provenance, freshness and privacy state."""

    asset_id: str = field(default_factory=lambda: _eid("easset"))
    request_id: str = ""
    source_type: EvidenceSourceType = EvidenceSourceType.GENERATED_VISUALIZATION
    source_uri: str = ""
    path: str = ""
    captured_at: str = ""
    content_hash: str = ""
    provenance: dict[str, Any] = field(default_factory=dict)
    claim_supported: str = ""
    entity: str = ""
    confidence: float = 0.0
    freshness: EvidenceFreshness = EvidenceFreshness.UNDATED
    redactions: list[str] = field(default_factory=list)
    privacy_scan: dict[str, Any] = field(default_factory=dict)
    beat_id: str = ""
    shot_id: str = ""
    created_at: str = field(default_factory=_now)

    @property
    def is_reality_asserting(self) -> bool:
        return self.source_type in REALITY_ASSERTING_TYPES

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── Shot presentation (§21, §22) ─────────────────────────────────────────


@dataclass
class ShotPresentationDecision:
    """How one VisualBeat should be presented, decided from beat semantics.

    ``speaker_visibility`` is never a fixed cadence (no "face every N seconds",
    no fixed 30% ratio, no random PIP). It follows from the beat's job.
    """

    decision_id: str = field(default_factory=lambda: _eid("spd"))
    beat_id: str = ""
    role: ShotPresentationRole = ShotPresentationRole.CONTEXTUAL_BROLL
    speaker_visibility: SpeakerVisibility = SpeakerVisibility.HIDDEN
    speaker_scale: ScaleLevel = ScaleLevel.NONE
    evidence_visibility: EvidenceVisibility = EvidenceVisibility.HIDDEN
    evidence_scale: ScaleLevel = ScaleLevel.NONE
    caption_priority: int = 50
    motion_priority: int = 50
    reason: str = ""
    semantic_basis: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DensityWindow:
    """Information-density verdict for one time window."""

    start_ms: int = 0
    end_ms: int = 0
    density: InformationDensity = InformationDensity.BALANCED
    competing_channels: list[str] = field(default_factory=list)
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class StagnationSpan:
    """A span with no semantically meaningful visual change."""

    start_ms: int = 0
    end_ms: int = 0
    duration_s: float = 0.0
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── Diagnosis and repair (§29, §30, §31) ─────────────────────────────────


@dataclass
class DiagnosisFinding:
    """One deduplicated editorial finding with its mapped root cause."""

    finding_id: str = field(default_factory=lambda: _eid("find"))
    categories: list[EditorialIssueCategory] = field(default_factory=list)
    representative_issue_id: str = ""
    defect_class: DefectClass = DefectClass.EDITORIAL_PREFERENCE
    severity: IssueSeverity = IssueSeverity.MINOR
    start_ms: int = 0
    end_ms: int = 0
    root_cause: str = ""
    canonical_artifact: CanonicalArtifact = CanonicalArtifact.NONE
    repairable: bool = False
    repair_scope: RepairScope = RepairScope.GLOBAL
    confidence: float = 0.0
    rationale: str = ""
    duplicate_issue_ids: list[str] = field(default_factory=list)
    shot_ids: list[str] = field(default_factory=list)
    beat_ids: list[str] = field(default_factory=list)

    @property
    def severity_rank(self) -> int:
        return _SEVERITY_ORDER[self.severity]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EditorialDiagnosis:
    """Deduplicated, root-caused editorial diagnosis of one candidate."""

    diagnosis_id: str = field(default_factory=lambda: _eid("diag"))
    review_id: str = ""
    candidate_id: str = ""
    content_id: str = ""
    video_hash: str = ""
    findings: list[DiagnosisFinding] = field(default_factory=list)
    summary: str = ""
    confidence: float = 0.0
    created_at: str = field(default_factory=_now)

    def blocker_findings(self) -> list[DiagnosisFinding]:
        return [f for f in self.findings if f.severity is IssueSeverity.BLOCKER]

    def major_findings(self) -> list[DiagnosisFinding]:
        return [f for f in self.findings if f.severity is IssueSeverity.MAJOR]

    def autonomous_findings(self) -> list[DiagnosisFinding]:
        """Findings allowed to drive an autonomous repair round."""
        return [
            f
            for f in self.findings
            if f.repairable
            and f.severity in AUTONOMOUS_REPAIR_SEVERITIES
            and f.canonical_artifact is not CanonicalArtifact.NONE
        ]

    def has_autonomous_work(self) -> bool:
        return bool(self.autonomous_findings())

    def only_minor_or_cosmetic(self) -> bool:
        return not any(
            f.severity in (IssueSeverity.BLOCKER, IssueSeverity.MAJOR) for f in self.findings
        )

    def categories_present(self) -> set[EditorialIssueCategory]:
        return {c for f in self.findings for c in f.categories}

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RepairIntent:
    """A declared, bounded, verifiable intent to change something.

    No ``RepairIntent`` means no autonomous revision.
    """

    intent_id: str = field(default_factory=lambda: _eid("rint"))
    diagnosis_id: str = ""
    finding_id: str = ""
    target_artifacts: list[CanonicalArtifact] = field(default_factory=list)
    expected_change: str = ""
    expected_visual_effect: str = ""
    scope: RepairScope = RepairScope.GLOBAL
    start_ms: int = 0
    end_ms: int = 0
    beat_ids: list[str] = field(default_factory=list)
    shot_ids: list[str] = field(default_factory=list)
    cost_estimate_usd: float = 0.0
    risk: str = "LOW"
    verification: str = ""
    global_reason: str = ""
    meaningful: bool = False
    created_at: str = field(default_factory=_now)

    @property
    def regenerates_sources(self) -> bool:
        return self.scope not in NON_REGENERATING_SCOPES

    def is_valid(self) -> tuple[bool, list[str]]:
        errors: list[str] = []
        if not self.diagnosis_id:
            errors.append("diagnosis_id required")
        if not self.target_artifacts:
            errors.append("target_artifacts required")
        if not self.expected_change:
            errors.append("expected_change required")
        if not self.expected_visual_effect:
            errors.append("expected_visual_effect required")
        if not self.verification:
            errors.append("verification required")
        if self.scope is RepairScope.GLOBAL and not self.global_reason:
            errors.append("GLOBAL scope requires an explicit reason")
        if self.scope in (RepairScope.SHOT_ONLY, RepairScope.TIMELINE_RANGE) and (
            self.end_ms <= self.start_ms
        ):
            errors.append("targeted scope requires a temporal range")
        return (not errors), errors

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── Candidates and comparison (§35, §38) ─────────────────────────────────


@dataclass
class RevisionCandidate:
    """One renderable revision in the V0 -> V1 -> V2 -> V3 chain."""

    candidate_id: str = field(default_factory=lambda: _eid("cand"))
    content_id: str = ""
    parent_candidate_id: str = ""
    revision_number: int = 0
    repair_intents: list[RepairIntent] = field(default_factory=list)
    video_path: str = ""
    video_hash: str = ""
    video_duration_s: float = 0.0
    changed_artifacts: list[str] = field(default_factory=list)
    unchanged_artifacts: list[str] = field(default_factory=list)
    changed_ranges: list[tuple[int, int]] = field(default_factory=list)
    cost: float = 0.0
    render_duration_s: float = 0.0
    review_id: str = ""
    created_at: str = field(default_factory=_now)
    human_note: str = ""

    def source_rerun_ranges_ms(self) -> list[tuple[int, int]]:
        return [r for r in self.changed_ranges if r[1] > r[0]]

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["changed_ranges"] = [list(r) for r in self.changed_ranges]
        return d


@dataclass
class PairwiseComparison:
    """A single blind pairwise judgement between two candidates.

    The reviewer is never told which candidate is newer, cheaper, or which the
    producing model preferred.
    """

    comparison_id: str = field(default_factory=lambda: _eid("cmp"))
    content_id: str = ""
    candidate_a: str = ""
    candidate_b: str = ""
    position_of_old: str = "A"  # which slot held the old candidate
    verdict: PairwiseVerdict = PairwiseVerdict.INCOMPARABLE
    rationale: str = ""
    dimension_notes: dict[str, str] = field(default_factory=dict)
    winner_candidate_id: str = ""
    provider: str = ""
    model: str = ""
    pairwise_prompt_version: str = PAIRWISE_PROMPT_VERSION
    latency_s: float = 0.0
    cost_usd: float | None = None
    compared_at: str = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["verdict"] = self.verdict.value
        return d


@dataclass
class PromotionDecision:
    """Outcome of the single promotion authority: the RevisionSession policy."""

    decision_id: str = field(default_factory=lambda: _eid("promo"))
    content_id: str = ""
    session_id: str = ""
    decision: PromotionDecisionKind = PromotionDecisionKind.KEEP_OLD
    old_candidate_id: str = ""
    new_candidate_id: str = ""
    new_blockers: int = 0
    hard_gates_pass: bool = False
    pairwise_forward: str = ""
    pairwise_reversed: str = ""
    expected_repair_verified: bool = False
    position_bias_or_uncertain: bool = False
    regression_detected: bool = False
    human_override: HumanDecision | None = None
    rationale: str = ""
    created_at: str = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["decision"] = self.decision.value
        d["human_override"] = self.human_override.value if self.human_override else None
        return d


@dataclass
class SessionCost:
    """Incremental cost of the revision loop (P4 budget aware)."""

    review_cost_usd: float = 0.0
    pairwise_cost_usd: float = 0.0
    asset_acquisition_cost_usd: float = 0.0
    repair_cost_usd: float = 0.0
    render_cost_usd: float = 0.0
    unknown_cost_items: int = 0

    @property
    def known_total_usd(self) -> float:
        return (
            self.review_cost_usd
            + self.pairwise_cost_usd
            + self.asset_acquisition_cost_usd
            + self.repair_cost_usd
            + self.render_cost_usd
        )

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["known_total_usd"] = self.known_total_usd
        return d


# ── Revision session (§46, §47, §48) ────────────────────────────────────

MAX_REVISION_ROUNDS = 3


@dataclass
class RevisionSession:
    """The single promotion authority for a candidate chain.

    Combines hard gates, blind bidirectional pairwise results, repair
    verification, budget and human override. A reviewer can never promote on
    its own.
    """

    session_id: str = field(default_factory=lambda: _eid("rsess"))
    content_id: str = ""
    profile_id: str = ""
    max_revision_rounds: int = MAX_REVISION_ROUNDS
    candidates: list[RevisionCandidate] = field(default_factory=list)
    reviews: dict[str, VideoReview] = field(default_factory=dict)  # candidate_id -> review
    diagnoses: dict[str, EditorialDiagnosis] = field(default_factory=dict)
    pairwise: list[PairwiseComparison] = field(default_factory=list)
    promotions: list[PromotionDecision] = field(default_factory=list)
    authoritative_candidate_id: str = ""
    revision_count: int = 0
    stop_reason: SessionStopReason | None = None
    cost: SessionCost = field(default_factory=SessionCost)
    budget_usd: float = 0.0
    history: list[RevisionCandidate] = field(default_factory=list)
    no_progress_streak: int = 0
    provider_available: bool = True
    human_decision: HumanDecision | None = None
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    # ── Candidate access ──
    @property
    def current(self) -> RevisionCandidate | None:
        return self.candidates[-1] if self.candidates else None

    def candidate(self, candidate_id: str) -> RevisionCandidate | None:
        return next((c for c in self.candidates if c.candidate_id == candidate_id), None)

    def authoritative(self) -> RevisionCandidate | None:
        return self.candidate(self.authoritative_candidate_id) or self.current

    def review_for(self, candidate_id: str) -> VideoReview | None:
        return self.reviews.get(candidate_id)

    def add_candidate(self, candidate: RevisionCandidate) -> None:
        self.candidates.append(candidate)
        self.revision_count = max(self.revision_count, candidate.revision_number)
        self.updated_at = _now()

    def record_promotion(self, decision: PromotionDecision) -> None:
        """Apply a promotion decision to the authoritative-candidate pointer.

        ``KEEP_OLD`` actively pins the old candidate: keeping the old version is a
        decision about which candidate is current, not the absence of one.
        ``HUMAN_REVIEW`` deliberately leaves the pointer alone, because the
        question is still open.
        """
        self.promotions.append(decision)
        if decision.decision is PromotionDecisionKind.PROMOTE_NEW:
            self.authoritative_candidate_id = decision.new_candidate_id
        elif decision.decision is PromotionDecisionKind.KEEP_OLD:
            self.authoritative_candidate_id = decision.old_candidate_id or (
                self.authoritative_candidate_id
            )
        self.updated_at = _now()

    def stop(self, reason: SessionStopReason) -> None:
        if self.stop_reason is None:
            self.stop_reason = reason
        self.updated_at = _now()

    def is_stopped(self) -> bool:
        return self.stop_reason is not None

    def rounds_remaining(self) -> int:
        return max(0, self.max_revision_rounds - self.revision_count)

    def budget_remaining_usd(self) -> float:
        return max(0.0, self.budget_usd - self.cost.known_total_usd)

    def promoted_count(self) -> int:
        return sum(
            1 for p in self.promotions if p.decision is PromotionDecisionKind.PROMOTE_NEW
        )

    def rejected_count(self) -> int:
        return sum(1 for p in self.promotions if p.decision is PromotionDecisionKind.KEEP_OLD)

    def uncertain_count(self) -> int:
        return sum(
            1 for p in self.promotions if p.decision is PromotionDecisionKind.HUMAN_REVIEW
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "content_id": self.content_id,
            "profile_id": self.profile_id,
            "max_revision_rounds": self.max_revision_rounds,
            "revision_count": self.revision_count,
            "authoritative_candidate_id": self.authoritative_candidate_id,
            "stop_reason": self.stop_reason.value if self.stop_reason else None,
            "cost": self.cost.to_dict(),
            "candidates": [c.to_dict() for c in self.candidates],
            "reviews": {k: v.to_dict() for k, v in self.reviews.items()},
            "diagnoses": {k: v.to_dict() for k, v in self.diagnoses.items()},
            "pairwise": [p.to_dict() for p in self.pairwise],
            "promotions": [p.to_dict() for p in self.promotions],
            "human_decision": self.human_decision.value if self.human_decision else None,
        }


# ── Fine-cut contract (§56) and reference style (§55) ────────────────────


@dataclass
class FineCutContract:
    """Production constraints layered onto P1/P2. Not a second edit pipeline."""

    target_duration_s: float = 0.0
    shot_density_per_minute: float = 0.0
    min_shot_s: float = 0.0
    max_shot_s: float = 0.0
    speaker_policy: str = "SEMANTIC"
    evidence_policy: str = "EVIDENCE_FIRST"
    caption_policy: str = "RESTRAINED"
    motion_policy: str = "SEMANTIC_ONLY"
    transition_policy: str = "MATCHED"
    information_density_policy: str = "BALANCED"
    revision_policy: str = "MAX_3_ROUNDS"
    contract_version: str = "hevi.p5_1.finecut.v1"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ReferenceStyleProfile:
    """Abstracted inspiration from a reference video.

    Only rhythm / ratio / family / density / caption / motion abstractions are
    retained. No shot sequence, no source footage, no protected graphic asset.
    """

    shot_rhythm: str = ""
    speaker_evidence_ratio: str = ""
    transition_family: str = ""
    information_density: str = ""
    caption_behavior: str = ""
    motion_language: str = ""
    source_ref: str = ""
    inspiration_only: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


__all__ = [
    "AUTONOMOUS_REPAIR_SEVERITIES",
    "EVIDENCE_PRIORITY",
    "GLOBAL_ISSUE_CATEGORIES",
    "HARD_DEFECT_CATEGORIES",
    "LAYER_Z_ORDER",
    "MAX_REVISION_ROUNDS",
    "NATIVE_VIDEO_INPUT",
    "NON_REALITY_TYPES",
    "NON_REGENERATING_SCOPES",
    "PAIRWISE_CONTRACT_DIMENSIONS",
    "PAIRWISE_PROMPT_VERSION",
    "REALITY_ASSERTING_TYPES",
    "REVIEW_PROMPT_VERSION",
    "ROOT_CAUSE_MAP",
    "VIDEO_UNDERSTANDING",
    "CanonicalArtifact",
    "DefectClass",
    "DensityWindow",
    "DiagnosisFinding",
    "EditableLayer",
    "EditorialDiagnosis",
    "EditorialIssue",
    "EditorialIssueCategory",
    "EvidenceAsset",
    "EvidenceFreshness",
    "EvidenceRequest",
    "EvidenceSourceType",
    "EvidenceVisibility",
    "FineCutContract",
    "HumanDecision",
    "InformationDensity",
    "IssueSeverity",
    "PairwiseComparison",
    "PairwiseVerdict",
    "PromotionDecision",
    "PromotionDecisionKind",
    "ReferenceStyleProfile",
    "RepairIntent",
    "RepairScope",
    "ReviewOutcome",
    "RevisionCandidate",
    "RevisionSession",
    "ScaleLevel",
    "SessionCost",
    "SessionStopReason",
    "ShotPresentationDecision",
    "ShotPresentationRole",
    "SpeakerVisibility",
    "StagnationSpan",
    "TemporalObservation",
    "VideoReview",
    "canonical_hash",
    "classify_defect",
    "normalize_category",
    "normalize_severity",
    "video_file_hash",
]
