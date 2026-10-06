"""HEVI P6 — Commercial Product Grammar: core schema (P6.0 architecture).

A ``ProductProfile`` states *production intent and constraints* for one class of
commercial video. It executes nothing. It names which grammars apply, what the
narrative/performance/visual intent is, and which policies bound production.

The canonical chain is:

    ProductProfile
    -> Product Grammar (declarative, composable)
    -> Narrative / Performance / Visual Constraints
    -> Unified Production Runtime  (existing P0-P5)
    -> Render / Delivery

What this module deliberately does NOT contain, because P6 is not allowed to
re-own any of it:

* no pipeline, and no production runner. The runtime entry points belong to
  ``hevi.production.p2_pipeline`` (canonical P0->P1->P2 chain) and
  ``hevi.tasks.task_service`` (API path). P6 declares a boundary, in
  :mod:`hevi.production.p6.runtime`.
* no renderer. ``hevi.renderers.base.RendererBackend`` is the single renderer
  authority. P6 may *constrain* a product (``RendererConstraint``) but never
  names or selects a backend.
* no timeline, shot, or motion model. ``VisualBeat`` (``hevi.production.p1_types``),
  ``ShotPlan`` and ``MotionPlan`` (``hevi.production.p0_pipeline``) remain
  canonical and are referenced by id only.
* no asset or evidence authority. ``AssetCandidate`` /
  ``assert_ready_for_generation`` (``hevi.production.shot_readiness``) and
  ``EvidenceAsset`` (``hevi.ops.p5_1_types``) are imported by downstream layers,
  never redefined here.
* no QA, verdict, or promotion authority. ``hevi.verdict`` and ``hevi.quality``
  own those.
* no creative profile. ``ProductionProfile`` /
  ``ProductionProfileRegistry`` (``hevi.production.p2_types``) own creative
  direction; a ``ProductProfile`` *references* ``profile_refs`` and never
  defines one.

P6.0 is architecture only: schemas, grammar contracts, and validated
enumerations. Grammar behaviour arrives in P6.1+; the compiler contract is
declared in :mod:`hevi.production.p6.compiler` but not implemented.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

# ── Enumerations ────────────────────────────────────────────────────────


class ProductType(StrEnum):
    """The ten canonical commercial product types.

    This vocabulary is closed. A new commercial product is a new
    ``ProductProfile`` that composes existing grammars, not a new member here
    and not a branch in the runtime.
    """

    AVATAR_EXPLAINER = "P01_AVATAR_EXPLAINER"
    NARRATED_KNOWLEDGE = "P02_NARRATED_KNOWLEDGE"
    HISTORICAL_REENACTMENT = "P03_HISTORICAL_REENACTMENT"
    CHARACTER_DOCUMENTARY = "P04_CHARACTER_DOCUMENTARY"
    DOCUMENTARY = "P05_DOCUMENTARY"
    NARRATIVE_FILM = "P06_NARRATIVE_FILM"
    CINEMATIC_KNOWLEDGE = "P07_CINEMATIC_KNOWLEDGE"
    COMMERCIAL = "P08_COMMERCIAL"
    TUTORIAL = "P09_TUTORIAL"
    SHORT_FORM = "P10_SHORT_FORM"


class GrammarKind(StrEnum):
    """The ten composable grammar kinds (spec G01-G10).

    ``CINEMATIC`` is declaration-only: P5.3 already owns camera movement,
    temporal separation, viewpoint separation, stabilization, dolly/zoom
    resolution and recipe selection. P6 may state cinematic *intent* through
    this grammar and must not reimplement any of it.
    """

    NARRATIVE = "G01_NarrativeGrammar"
    PRESENTER = "G02_PresenterGrammar"
    CHARACTER = "G03_CharacterGrammar"
    WORLD = "G04_WorldGrammar"
    EVIDENCE = "G05_EvidenceGrammar"
    DOCUMENTARY = "G06_DocumentaryGrammar"
    COMMERCIAL = "G07_CommercialGrammar"
    INSTRUCTION = "G08_InstructionGrammar"
    SHORT_FORM = "G09_ShortFormGrammar"
    CINEMATIC = "G10_CinematicGrammar"


class NarrativeNode(StrEnum):
    """Canonical narrative nodes. Profiles select and order a subset."""

    HOOK = "HOOK"
    CONTEXT = "CONTEXT"
    SETUP = "SETUP"
    DEVELOPMENT = "DEVELOPMENT"
    TURNING_POINT = "TURNING_POINT"
    EXPLANATION = "EXPLANATION"
    EVIDENCE = "EVIDENCE"
    CONFLICT = "CONFLICT"
    RESOLUTION = "RESOLUTION"
    CONCLUSION = "CONCLUSION"
    CTA = "CTA"


class NarrativeMode(StrEnum):
    """Supported narrative shapes. One engine, selected by declaration."""

    LINEAR = "linear"
    CHRONOLOGICAL = "chronological"
    NONLINEAR = "nonlinear"
    DOCUMENTARY = "documentary"
    EXPLANATORY = "explanatory"
    INSTRUCTIONAL = "instructional"
    COMMERCIAL = "commercial"
    CHARACTER_DRIVEN = "character-driven"
    SHORT_FORM = "short-form"


class PresenterKind(StrEnum):
    """A presenter is a semantic entity, never a renderer."""

    AVATAR = "avatar_presenter"
    HUMAN = "human_presenter"
    VOICE_ONLY = "voice_only_presenter"
    NARRATOR = "narrator"
    CHARACTER = "character_presenter"


class SpeakerVisibility(StrEnum):
    """Semantic speaker framing. Resolved to a shot by existing P1/P5.1 policy."""

    DOMINANT = "DOMINANT"
    FULL = "FULL"
    MEDIUM = "MEDIUM"
    PIP = "PIP"
    HIDDEN = "HIDDEN"


class CharacterKind(StrEnum):
    """Supported character configurations."""

    SINGLE = "single_character"
    MULTIPLE = "multiple_characters"
    DIALOGUE = "dialogue"
    NARRATION_WITH_CHARACTER = "narration_with_character"
    HISTORICAL = "historical_character"
    FICTIONAL = "fictional_character"


class WorldKind(StrEnum):
    """Supported world configurations. A world is not an asset authority."""

    HISTORICAL = "historical_world"
    REAL_LOCATION = "real_location"
    DOCUMENTARY_LOCATION = "documentary_location"
    FICTIONAL = "fictional_world"
    COMMERCIAL_ENVIRONMENT = "commercial_environment"


class EvidenceType(StrEnum):
    """Evidence kinds, ordered most-real-first in declaration intent only."""

    PRIMARY_SOURCE = "PRIMARY_SOURCE"
    OFFICIAL_RECORD = "OFFICIAL_RECORD"
    TESTIMONY = "TESTIMONY"
    ARCHIVAL = "ARCHIVAL"
    DOCUMENT_EXCERPT = "DOCUMENT_EXCERPT"
    DATA_VISUALIZATION = "DATA_VISUALIZATION"
    DERIVED = "DERIVED"
    RECONSTRUCTION = "RECONSTRUCTION"
    SYMBOLIC = "SYMBOLIC"


class EpistemicStatus(StrEnum):
    """The fact/interpretation/reconstruction/fiction distinction.

    This is the boundary P6 must never blur: a generated model output is not an
    evidence authority. ``FICTION`` and ``RECONSTRUCTION`` may not be presented
    as ``FACT``, and ``disclosure_required`` follows from this.
    """

    FACT = "FACT"
    INTERPRETATION = "INTERPRETATION"
    RECONSTRUCTION = "RECONSTRUCTION"
    FICTION = "FICTION"


class ShortFormPlatform(StrEnum):
    """Short-form targets. Each only changes production constraints."""

    TIKTOK = "TikTok"
    REELS = "Reels"
    SHORTS = "Shorts"
    GENERIC_VERTICAL = "generic_vertical"


class AspectPolicy(StrEnum):
    """Declared aspect intent. The existing render/delivery layer resolves it."""

    LANDSCAPE_16_9 = "16:9"
    LANDSCAPE_4_3 = "4:3"
    VERTICAL_9_16 = "9:16"
    SQUARE_1_1 = "1:1"
    CINEMATIC_2_39 = "2.39:1"


# ── Small shared value types ────────────────────────────────────────────


@dataclass(frozen=True)
class DurationPolicy:
    """Declared duration intent. Bounds, not a timeline."""

    target_s: float
    min_s: float
    max_s: float

    def __post_init__(self) -> None:
        if self.min_s <= 0 or self.max_s < self.min_s:
            raise ValueError(f"INVALID_DURATION_POLICY:{self.min_s}-{self.max_s}")
        if not (self.min_s <= self.target_s <= self.max_s):
            raise ValueError(
                f"DURATION_OUT_OF_RANGE:target={self.target_s} not in "
                f"[{self.min_s}, {self.max_s}]"
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ContinuityConstraint:
    """One declarative continuity requirement.

    Continuity is *declared* here and *enforced* by the existing continuity
    authority. This is a requirement, not a checker.
    """

    dimension: str
    requirement: str
    enforced_by: str

    def __post_init__(self) -> None:
        if not self.dimension or not self.requirement:
            raise ValueError("INVALID_CONTINUITY_CONSTRAINT:dimension and requirement required")
        if not self.enforced_by:
            raise ValueError(
                "CONTINUITY_WITHOUT_AUTHORITY:continuity must name the existing "
                "authority that enforces it"
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ProductConstraint:
    """A single product-level constraint. Declarative and inspectable."""

    key: str
    value: str
    rationale: str = ""

    def __post_init__(self) -> None:
        if not self.key:
            raise ValueError("INVALID_PRODUCT_CONSTRAINT:key required")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RendererConstraint:
    """Renderer *requirements*, never a renderer identity.

    ``required_capabilities`` and ``forbidden_renderers`` are consumed by the
    existing selection authority (``hevi.renderers.base.select_renderer``). P6
    must never name a concrete backend as the product's renderer: a product
    declares what it needs, and the existing authority decides who can execute
    it.
    """

    required_capabilities: tuple[str, ...] = ()
    forbidden_renderers: tuple[str, ...] = ()
    rationale: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "required_capabilities": list(self.required_capabilities),
            "forbidden_renderers": list(self.forbidden_renderers),
            "rationale": self.rationale,
        }


@dataclass(frozen=True)
class GrammarRef:
    """A grammar attached to a product profile, with its composition weight.

    Composition is declarative: a profile lists grammars and says which
    grammars are mandatory versus optional. Nothing here branches on
    ``ProductType``.
    """

    kind: GrammarKind
    required: bool = True
    weight_hint: str = ""
    notes: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.kind, GrammarKind):
            raise ValueError(f"UNKNOWN_GRAMMAR_KIND:{self.kind!r}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "required": self.required,
            "weight_hint": self.weight_hint,
            "notes": self.notes,
        }


# ── G01 NarrativeGrammar ────────────────────────────────────────────────


@dataclass(frozen=True)
class NarrativeGrammar:
    """G01 — narrative shape, declared not executed.

    Reuses the existing narrative vocabulary rather than introducing a second
    story engine: ``hevi.narrative.models.StoryBeat`` and
    ``hevi.production.p1_types.NarrativePhase`` remain canonical. This grammar
    states which nodes a product uses, in what mode, and what continuity the
    arc requires.
    """

    mode: NarrativeMode
    nodes: tuple[NarrativeNode, ...]
    arc_constraints: tuple[ProductConstraint, ...] = ()
    required_phase_refs: tuple[str, ...] = ()
    max_parallel_threads: int = 1

    def __post_init__(self) -> None:
        if not self.nodes:
            raise ValueError("EMPTY_NARRATIVE_GRAMMAR:at least one node required")
        if len(set(self.nodes)) != len(self.nodes):
            raise ValueError("DUPLICATE_NARRATIVE_NODE:nodes must be unique")
        if self.max_parallel_threads < 1:
            raise ValueError(f"INVALID_THREAD_COUNT:{self.max_parallel_threads}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode.value,
            "nodes": [n.value for n in self.nodes],
            "arc_constraints": [c.to_dict() for c in self.arc_constraints],
            "required_phase_refs": list(self.required_phase_refs),
            "max_parallel_threads": self.max_parallel_threads,
        }


# ── G02 PresenterGrammar ────────────────────────────────────────────────


@dataclass(frozen=True)
class PresenterGrammar:
    """G02 — presenter as a semantic entity.

    ``presenter_id`` references an identity owned elsewhere; P6 declares how
    that presenter must read on screen, never how it is drawn or rendered.
    """

    presenter_id: str
    kind: PresenterKind
    identity_ref: str = ""
    voice_ref: str = ""
    visual_identity_ref: str = ""
    delivery_style: str = ""
    camera_behavior: str = ""
    gesture_policy: str = ""
    expression_policy: str = ""
    default_visibility: SpeakerVisibility = SpeakerVisibility.DOMINANT
    continuity: tuple[ContinuityConstraint, ...] = ()

    def __post_init__(self) -> None:
        if not self.presenter_id:
            raise ValueError("PRESENTER_WITHOUT_ID:presenter_id required")
        if not self.kind:
            raise ValueError("PRESENTER_WITHOUT_KIND:kind required")

    def to_dict(self) -> dict[str, Any]:
        return {
            "presenter_id": self.presenter_id,
            "kind": self.kind.value,
            "identity_ref": self.identity_ref,
            "voice_ref": self.voice_ref,
            "visual_identity_ref": self.visual_identity_ref,
            "delivery_style": self.delivery_style,
            "camera_behavior": self.camera_behavior,
            "gesture_policy": self.gesture_policy,
            "expression_policy": self.expression_policy,
            "default_visibility": self.default_visibility.value,
            "continuity": [c.to_dict() for c in self.continuity],
        }


# ── G03 CharacterGrammar ────────────────────────────────────────────────


@dataclass(frozen=True)
class CharacterGrammar:
    """G03 — character declaration plus its continuity requirements.

    Identity/appearance/voice/role/scene continuity are declared here and
    enforced by the existing entity and continuity authorities
    (``hevi.production.entities``, ``hevi.narrative.continuity``).
    """

    character_id: str
    kind: CharacterKind
    identity_ref: str = ""
    role: str = ""
    appearance_ref: str = ""
    voice_ref: str = ""
    personality: str = ""
    motivation: str = ""
    relationship_refs: tuple[str, ...] = ()
    dialogue_policy: str = ""
    performance_policy: str = ""
    continuity: tuple[ContinuityConstraint, ...] = ()

    def __post_init__(self) -> None:
        if not self.character_id:
            raise ValueError("CHARACTER_WITHOUT_ID:character_id required")
        if not self.kind:
            raise ValueError("CHARACTER_WITHOUT_KIND:kind required")
        # A character must declare what keeps it the same character, or it is
        # not a character contract at all.
        if not self.continuity:
            raise ValueError(
                f"CHARACTER_WITHOUT_CONTINUITY:{self.character_id} must declare "
                "at least one continuity constraint"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "character_id": self.character_id,
            "kind": self.kind.value,
            "identity_ref": self.identity_ref,
            "role": self.role,
            "appearance_ref": self.appearance_ref,
            "voice_ref": self.voice_ref,
            "personality": self.personality,
            "motivation": self.motivation,
            "relationship_refs": list(self.relationship_refs),
            "dialogue_policy": self.dialogue_policy,
            "performance_policy": self.performance_policy,
            "continuity": [c.to_dict() for c in self.continuity],
        }


# ── G04 WorldGrammar ────────────────────────────────────────────────────


@dataclass(frozen=True)
class WorldGrammar:
    """G04 — world declaration. Explicitly not an asset authority.

    A world describes era, place, culture and visual constraints. It never
    holds, resolves, or vouches for a media asset; that is
    ``hevi.production.shot_readiness`` and ``hevi.artifact_store``.
    """

    world_id: str
    kind: WorldKind
    era: str = ""
    location_ref: str = ""
    environment: str = ""
    architecture: str = ""
    culture: str = ""
    technology: str = ""
    time_period: str = ""
    weather: str = ""
    lighting: str = ""
    visual_constraints: tuple[ProductConstraint, ...] = ()
    continuity: tuple[ContinuityConstraint, ...] = ()

    def __post_init__(self) -> None:
        if not self.world_id:
            raise ValueError("WORLD_WITHOUT_ID:world_id required")
        if not self.kind:
            raise ValueError("WORLD_WITHOUT_KIND:kind required")

    def to_dict(self) -> dict[str, Any]:
        return {
            "world_id": self.world_id,
            "kind": self.kind.value,
            "era": self.era,
            "location_ref": self.location_ref,
            "environment": self.environment,
            "architecture": self.architecture,
            "culture": self.culture,
            "technology": self.technology,
            "time_period": self.time_period,
            "weather": self.weather,
            "lighting": self.lighting,
            "visual_constraints": [c.to_dict() for c in self.visual_constraints],
            "continuity": [c.to_dict() for c in self.continuity],
        }


# ── G05 EvidenceGrammar ─────────────────────────────────────────────────


@dataclass(frozen=True)
class EvidenceClaim:
    """One claim and the epistemic status of the support behind it.

    ``epistemic_status`` is the honesty boundary. A claim backed only by
    ``RECONSTRUCTION`` or ``FICTION`` cannot be presented as ``FACT``, and
    ``disclosure_required`` is what forces that onto the screen.
    """

    claim_id: str
    statement: str
    epistemic_status: EpistemicStatus
    confidence: float
    source_refs: tuple[str, ...] = ()
    evidence_types: tuple[EvidenceType, ...] = ()

    def __post_init__(self) -> None:
        if not self.claim_id or not self.statement:
            raise ValueError("INVALID_EVIDENCE_CLAIM:claim_id and statement required")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"INVALID_CONFIDENCE:{self.confidence}")
        if self.epistemic_status is EpistemicStatus.FACT and not self.source_refs:
            raise ValueError(
                f"FACT_WITHOUT_SOURCE:{self.claim_id} is declared FACT with no source"
            )

    @property
    def disclosure_required(self) -> bool:
        """Fiction and reconstruction must be disclosed, never passed off as fact."""
        return self.epistemic_status in (
            EpistemicStatus.FICTION,
            EpistemicStatus.RECONSTRUCTION,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "statement": self.statement,
            "epistemic_status": self.epistemic_status.value,
            "confidence": self.confidence,
            "source_refs": list(self.source_refs),
            "evidence_types": [e.value for e in self.evidence_types],
            "disclosure_required": self.disclosure_required,
        }


@dataclass(frozen=True)
class EvidenceGrammar:
    """G05 — the Source -> Evidence -> Claim -> Scene -> Shot chain.

    Declares the chain's shape. It does not acquire evidence, and a model
    output is never itself an evidence authority: generated material may only
    enter as ``DERIVED``, ``RECONSTRUCTION`` or ``SYMBOLIC``.
    """

    claims: tuple[EvidenceClaim, ...] = ()
    allowed_evidence_types: tuple[EvidenceType, ...] = ()
    require_disclosure_for_speculative: bool = True
    forbid_generated_as_fact: bool = True
    traceability: tuple[ProductConstraint, ...] = ()

    def __post_init__(self) -> None:
        ids = [c.claim_id for c in self.claims]
        if len(set(ids)) != len(ids):
            raise ValueError("DUPLICATE_CLAIM_ID:claim ids must be unique")

    def claim(self, claim_id: str) -> EvidenceClaim | None:
        return next((c for c in self.claims if c.claim_id == claim_id), None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "claims": [c.to_dict() for c in self.claims],
            "allowed_evidence_types": [e.value for e in self.allowed_evidence_types],
            "require_disclosure_for_speculative": self.require_disclosure_for_speculative,
            "forbid_generated_as_fact": self.forbid_generated_as_fact,
            "traceability": [t.to_dict() for t in self.traceability],
        }


# ── G06 DocumentaryGrammar ──────────────────────────────────────────────


@dataclass(frozen=True)
class DocumentaryGrammar:
    """G06 — documentary composition over the evidence chain.

    Must be able to answer, for any shot: why does it exist, which claim does
    it serve, what is that claim's source, and is it fact or reconstruction.
    Those four questions are declared as requirements here and answered by the
    existing lineage/evidence authorities at runtime.
    """

    evidence_ref: str = ""
    narrator_ref: str = ""
    interview_refs: tuple[str, ...] = ()
    archive_refs: tuple[str, ...] = ()
    broll_policy: str = ""
    reconstruction_policy: str = ""
    context_policy: str = ""
    timeline_mode: str = ""
    required_answers: tuple[str, ...] = (
        "why_does_this_shot_exist",
        "which_claim_does_it_serve",
        "what_is_the_claim_source",
        "fact_or_reconstruction",
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_ref": self.evidence_ref,
            "narrator_ref": self.narrator_ref,
            "interview_refs": list(self.interview_refs),
            "archive_refs": list(self.archive_refs),
            "broll_policy": self.broll_policy,
            "reconstruction_policy": self.reconstruction_policy,
            "context_policy": self.context_policy,
            "timeline_mode": self.timeline_mode,
            "required_answers": list(self.required_answers),
        }


# ── G07 CommercialGrammar ───────────────────────────────────────────────


@dataclass(frozen=True)
class ProductIdentity:
    """Locked commercial product identity.

    The model may not freely alter the core identity of a product being sold.
    Every locked attribute is explicit so a later stage can verify it rather
    than infer it.
    """

    product_id: str
    official_name: str = ""
    shape: str = ""
    appearance: str = ""
    logo_ref: str = ""
    label_ref: str = ""
    color_material_constraints: tuple[str, ...] = ()
    key_attributes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.product_id:
            raise ValueError("PRODUCT_IDENTITY_WITHOUT_ID:product_id required")

    def to_dict(self) -> dict[str, Any]:
        return {
            "product_id": self.product_id,
            "official_name": self.official_name,
            "shape": self.shape,
            "appearance": self.appearance,
            "logo_ref": self.logo_ref,
            "label_ref": self.label_ref,
            "color_material_constraints": list(self.color_material_constraints),
            "key_attributes": list(self.key_attributes),
        }


@dataclass(frozen=True)
class CommercialGrammar:
    """G07 — brand, product, message, proof and legal boundary.

    ``forbidden_claims`` is enforced as a constraint, not advice; it is
    declared so the existing claim-grounding authority
    (``hevi.production.product_video``) can refuse an unsupported claim.
    """

    brand_id: str
    product_identity: ProductIdentity | None = None
    campaign_id: str = ""
    brand_voice: str = ""
    visual_identity_ref: str = ""
    key_message: str = ""
    benefits: tuple[str, ...] = ()
    proof_points: tuple[str, ...] = ()
    cta: str = ""
    legal_constraints: tuple[ProductConstraint, ...] = ()
    forbidden_claims: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.brand_id:
            raise ValueError("COMMERCIAL_WITHOUT_BRAND:brand_id required")
        if not self.forbidden_claims:
            raise ValueError(
                f"COMMERCIAL_WITHOUT_FORBIDDEN_CLAIMS:{self.brand_id} must declare "
                "at least one forbidden claim class"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "brand_id": self.brand_id,
            "product_identity": (
                self.product_identity.to_dict() if self.product_identity else None
            ),
            "campaign_id": self.campaign_id,
            "brand_voice": self.brand_voice,
            "visual_identity_ref": self.visual_identity_ref,
            "key_message": self.key_message,
            "benefits": list(self.benefits),
            "proof_points": list(self.proof_points),
            "cta": self.cta,
            "legal_constraints": [c.to_dict() for c in self.legal_constraints],
            "forbidden_claims": list(self.forbidden_claims),
        }


# ── G08 InstructionGrammar ──────────────────────────────────────────────


@dataclass(frozen=True)
class InstructionStep:
    """One step: Action -> ExpectedState -> Verification.

    A tutorial is not narration over B-roll. Every step states what should
    happen and how that is checked.
    """

    step_id: str
    action: str
    expected_state: str
    verification: str
    failure_recovery: str = ""

    def __post_init__(self) -> None:
        if not self.step_id:
            raise ValueError("INSTRUCTION_STEP_WITHOUT_ID:step_id required")
        for name, value in (
            ("action", self.action),
            ("expected_state", self.expected_state),
            ("verification", self.verification),
        ):
            if not value:
                raise ValueError(
                    f"INCOMPLETE_INSTRUCTION_STEP:{self.step_id} missing {name}"
                )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class InstructionGrammar:
    """G08 — objective and ordered, verifiable steps."""

    objective: str
    steps: tuple[InstructionStep, ...]
    audience_assumption: str = ""
    verification_policy: str = ""

    def __post_init__(self) -> None:
        if not self.objective:
            raise ValueError("INSTRUCTION_WITHOUT_OBJECTIVE:objective required")
        if not self.steps:
            raise ValueError("INSTRUCTION_WITHOUT_STEPS:at least one step required")
        ids = [s.step_id for s in self.steps]
        if len(set(ids)) != len(ids):
            raise ValueError("DUPLICATE_STEP_ID:step ids must be unique")

    def to_dict(self) -> dict[str, Any]:
        return {
            "objective": self.objective,
            "steps": [s.to_dict() for s in self.steps],
            "audience_assumption": self.audience_assumption,
            "verification_policy": self.verification_policy,
        }


# ── G09 ShortFormGrammar ────────────────────────────────────────────────


@dataclass(frozen=True)
class ShortFormGrammar:
    """G09 — short-form production constraints.

    Changes production constraints only. It cannot create a second timeline
    authority: beat structure and cut policy are declared, and the existing
    edit/shot authority executes them.
    """

    platform: ShortFormPlatform
    duration: DurationPolicy
    aspect_ratio: AspectPolicy = AspectPolicy.VERTICAL_9_16
    hook: str = ""
    beat_structure: tuple[str, ...] = ()
    caption_policy: str = ""
    cut_policy: str = ""
    retention_policy: str = ""
    cta: str = ""

    def __post_init__(self) -> None:
        if not self.hook:
            raise ValueError("SHORT_FORM_WITHOUT_HOOK:hook required")

    def to_dict(self) -> dict[str, Any]:
        return {
            "platform": self.platform.value,
            "duration": self.duration.to_dict(),
            "aspect_ratio": self.aspect_ratio.value,
            "hook": self.hook,
            "beat_structure": list(self.beat_structure),
            "caption_policy": self.caption_policy,
            "cut_policy": self.cut_policy,
            "retention_policy": self.retention_policy,
            "cta": self.cta,
        }


# ── G10 CinematicGrammar ────────────────────────────────────────────────


@dataclass(frozen=True)
class CinematicIntent:
    """Declared cinematic intent, expressed in P5.3 vocabulary.

    P6 does not resolve camera movement, dolly/zoom coupling, stabilization or
    recipe selection. It names the intent in terms P5.3 already understands
    and lets P5.3's retrieval and compiler decide.
    """

    intent_refs: tuple[str, ...] = ()
    viewpoint_preference: str = ""
    stabilization_preference: str = ""
    pacing_intent: str = ""
    motion_intent: str = ""
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent_refs": list(self.intent_refs),
            "viewpoint_preference": self.viewpoint_preference,
            "stabilization_preference": self.stabilization_preference,
            "pacing_intent": self.pacing_intent,
            "motion_intent": self.motion_intent,
            "notes": self.notes,
        }


# ── ProductProfile ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class ProductProfile:
    """Canonical commercial product intent. Declares, never executes.

    A ``ProductProfile`` is not a creative profile. ``profile_refs`` names
    existing ``ProductionProfile`` ids owned by
    ``hevi.production.p2_types.ProductionProfileRegistry``; P6 never defines or
    registers one, which is what keeps ``DUPLICATE_PROFILE_REGISTRY == 0``.

    ``content_hash()`` is stable across runs so a product's intent is
    diffable and cacheable. It is derived from the full serialised profile with
    sorted keys, so identical intent always hashes identically.
    """

    id: str
    product_type: ProductType
    purpose: str
    audience: str
    grammars: tuple[GrammarRef, ...]

    version: str = "1.0.0"
    profile_refs: tuple[str, ...] = ()

    #: P6.1 — id of a registered narrative grammar, e.g. ``"documentary"`` or
    #: ``"explanatory@1.0.0"``. Resolved through
    #: :data:`hevi.production.p6.narrative.registry.NARRATIVE_GRAMMAR_REGISTRY`
    #: by the :class:`~hevi.production.p6.narrative.compiler.NarrativeCompiler`.
    #: Deliberately a *reference*, not an embedded grammar: one shape is defined
    #: once and shared, so a product never carries a private narrative engine.
    narrative_grammar_id: str = ""

    #: P6.2 — id of a registered presenter grammar, e.g. ``"avatar_explainer"``.
    #: Resolved through
    #: :data:`hevi.production.p6.presenter_registry.PRESENTER_GRAMMAR_REGISTRY`
    #: by the :class:`~hevi.production.p6.presenter_compiler.PresenterCompiler`.
    #: As with the narrative grammar, a product *selects* a presenter shape; it
    #: never defines node order, presenter logic, camera logic, render logic or
    #: audio logic of its own.
    presenter_grammar_id: str = ""

    #: P6.3 — id of a registered visual style grammar, e.g. ``"documentary_realism"``.
    #: Resolved through
    #: :data:`hevi.production.p6.visual_style.registry.VISUAL_STYLE_REGISTRY`
    #: by the
    #: :class:`~hevi.production.p6.visual_style.compiler.VisualStyleCompiler`.
    #: As with every P6 grammar, this is a *reference*: a product selects a
    #: shared style, and never defines its own mood, palette, composition,
    #: texture, motion or lighting of its own.
    visual_style_id: str = ""

    #: P6.4 — id of a registered visual grammar, e.g. ``"documentary_realism"``.
    #: Resolved through
    #: :data:`hevi.production.p6.visual_grammar.VISUAL_GRAMMAR_REGISTRY`
    #: by the
    #: :class:`~hevi.production.p6.visual_compiler.VisualCompiler`, then bound to
    #: P5.3's cinematic engine via ``retrieve_with_evidence()``.
    #:
    #: Distinct from ``visual_style_id`` on purpose. The style reference answers
    #: *how it looks* (mood, palette, texture); the grammar reference answers *how
    #: it is shot and cut* (camera, editing). They overlap on composition, motion
    #: and lighting, so :class:`VisualCompiler` refuses a pair whose shared
    #: languages disagree rather than silently preferring one layer.
    visual_grammar_id: str = ""

    duration_policy: DurationPolicy | None = None
    aspect_policy: AspectPolicy = AspectPolicy.LANDSCAPE_16_9

    narrative_grammar: NarrativeGrammar | None = None
    presenter_grammar: PresenterGrammar | None = None
    character_grammar: CharacterGrammar | None = None
    world_grammar: WorldGrammar | None = None
    evidence_grammar: EvidenceGrammar | None = None
    documentary_grammar: DocumentaryGrammar | None = None
    commercial_grammar: CommercialGrammar | None = None
    instruction_grammar: InstructionGrammar | None = None
    short_form_grammar: ShortFormGrammar | None = None
    cinematic_intent: CinematicIntent | None = None

    evidence_policy: tuple[ProductConstraint, ...] = ()
    brand_policy: tuple[ProductConstraint, ...] = ()
    instruction_policy: tuple[ProductConstraint, ...] = ()
    short_form_policy: tuple[ProductConstraint, ...] = ()
    delivery_policy: tuple[ProductConstraint, ...] = ()
    renderer_constraint: RendererConstraint = field(default_factory=RendererConstraint)
    constraints: tuple[ProductConstraint, ...] = ()
    qualification_profile: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("PRODUCT_PROFILE_WITHOUT_ID:id required")
        if not self.purpose:
            raise ValueError(f"PRODUCT_PROFILE_WITHOUT_PURPOSE:{self.id}")
        if not self.audience:
            raise ValueError(f"PRODUCT_PROFILE_WITHOUT_AUDIENCE:{self.id}")
        if not self.grammars:
            raise ValueError(
                f"PRODUCT_PROFILE_WITHOUT_GRAMMARS:{self.id} must compose at least one grammar"
            )
        kinds = [g.kind for g in self.grammars]
        if len(set(kinds)) != len(kinds):
            raise ValueError(f"DUPLICATE_GRAMMAR_REF:{self.id} lists a grammar twice")

    # ── Composition helpers (declarative, no branching on product_type) ──

    def grammar(self, kind: GrammarKind) -> GrammarRef | None:
        return next((g for g in self.grammars if g.kind is kind), None)

    def has_grammar(self, kind: GrammarKind) -> bool:
        return self.grammar(kind) is not None

    def required_grammar_kinds(self) -> tuple[GrammarKind, ...]:
        return tuple(g.kind for g in self.grammars if g.required)

    def validate_composition(self) -> tuple[bool, list[str]]:
        """Check declared grammar refs against the grammars actually present.

        Fail-closed: a profile that references a grammar it does not carry, or
        carries a grammar it never declared, is invalid. This is a structural
        check only; it does not compile anything.
        """
        errors: list[str] = []

        payload_by_kind = {
            GrammarKind.NARRATIVE: self.narrative_grammar,
            GrammarKind.PRESENTER: self.presenter_grammar,
            GrammarKind.CHARACTER: self.character_grammar,
            GrammarKind.WORLD: self.world_grammar,
            GrammarKind.EVIDENCE: self.evidence_grammar,
            GrammarKind.DOCUMENTARY: self.documentary_grammar,
            GrammarKind.COMMERCIAL: self.commercial_grammar,
            GrammarKind.INSTRUCTION: self.instruction_grammar,
            GrammarKind.SHORT_FORM: self.short_form_grammar,
        }

        for ref in self.grammars:
            if ref.kind is GrammarKind.CINEMATIC:
                if self.cinematic_intent is None:
                    errors.append(f"DECLARED_BUT_ABSENT:{ref.kind.value}")
                continue
            if payload_by_kind.get(ref.kind) is None:
                errors.append(f"DECLARED_BUT_ABSENT:{ref.kind.value}")

        declared = {g.kind for g in self.grammars}
        if GrammarKind.CINEMATIC not in declared and self.cinematic_intent is not None:
            errors.append(f"PRESENT_BUT_UNDECLARED:{GrammarKind.CINEMATIC.value}")
        for kind, payload in payload_by_kind.items():
            if payload is not None and kind not in declared:
                errors.append(f"PRESENT_BUT_UNDECLARED:{kind.value}")

        if self.short_form_grammar is not None and self.aspect_policy is not (
            AspectPolicy.VERTICAL_9_16
        ):
            errors.append(
                f"SHORT_FORM_ASPECT_MISMATCH:{self.aspect_policy.value} declared with "
                "a vertical-only grammar"
            )

        return (not errors), errors

    # ── Serialisation ───────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "version": self.version,
            "product_type": self.product_type.value,
            "purpose": self.purpose,
            "audience": self.audience,
            "profile_refs": list(self.profile_refs),
            "grammars": [g.to_dict() for g in self.grammars],
            "duration_policy": (
                self.duration_policy.to_dict() if self.duration_policy else None
            ),
            "aspect_policy": self.aspect_policy.value,
            # P6.3 note: the three grammar *reference* ids are part of the
            # profile's identity. They were serialised only from P6.3 onward;
            # before this, two profiles differing solely in which grammar they
            # selected hashed identically, which made ``content_hash()``
            # unusable as a cache key for exactly the thing P6.1–P6.3 add.
            "narrative_grammar_id": self.narrative_grammar_id,
            "presenter_grammar_id": self.presenter_grammar_id,
            "visual_style_id": self.visual_style_id,
            "visual_grammar_id": self.visual_grammar_id,
            "narrative_grammar": (
                self.narrative_grammar.to_dict() if self.narrative_grammar else None
            ),
            "presenter_grammar": (
                self.presenter_grammar.to_dict() if self.presenter_grammar else None
            ),
            "character_grammar": (
                self.character_grammar.to_dict() if self.character_grammar else None
            ),
            "world_grammar": self.world_grammar.to_dict() if self.world_grammar else None,
            "evidence_grammar": (
                self.evidence_grammar.to_dict() if self.evidence_grammar else None
            ),
            "documentary_grammar": (
                self.documentary_grammar.to_dict() if self.documentary_grammar else None
            ),
            "commercial_grammar": (
                self.commercial_grammar.to_dict() if self.commercial_grammar else None
            ),
            "instruction_grammar": (
                self.instruction_grammar.to_dict() if self.instruction_grammar else None
            ),
            "short_form_grammar": (
                self.short_form_grammar.to_dict() if self.short_form_grammar else None
            ),
            "cinematic_intent": (
                self.cinematic_intent.to_dict() if self.cinematic_intent else None
            ),
            "evidence_policy": [c.to_dict() for c in self.evidence_policy],
            "brand_policy": [c.to_dict() for c in self.brand_policy],
            "instruction_policy": [c.to_dict() for c in self.instruction_policy],
            "short_form_policy": [c.to_dict() for c in self.short_form_policy],
            "delivery_policy": [c.to_dict() for c in self.delivery_policy],
            "renderer_constraint": self.renderer_constraint.to_dict(),
            "constraints": [c.to_dict() for c in self.constraints],
            "qualification_profile": self.qualification_profile,
        }

    def content_hash(self) -> str:
        """Stable hash of the full profile. Deterministic across processes."""
        encoded = json.dumps(
            self.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


__all__ = [
    "AspectPolicy",
    "CharacterGrammar",
    "CharacterKind",
    "CinematicIntent",
    "CommercialGrammar",
    "ContinuityConstraint",
    "DocumentaryGrammar",
    "DurationPolicy",
    "EpistemicStatus",
    "EvidenceClaim",
    "EvidenceGrammar",
    "EvidenceType",
    "GrammarKind",
    "GrammarRef",
    "InstructionGrammar",
    "InstructionStep",
    "NarrativeGrammar",
    "NarrativeMode",
    "NarrativeNode",
    "PresenterGrammar",
    "PresenterKind",
    "ProductConstraint",
    "ProductIdentity",
    "ProductProfile",
    "ProductType",
    "RendererConstraint",
    "ShortFormGrammar",
    "ShortFormPlatform",
    "SpeakerVisibility",
    "WorldGrammar",
    "WorldKind",
]
