"""HEVI P5.3 — Cinematic Recipe Intelligence: core schema.

A recipe is a typed structured contract, not a prompt. It describes WHAT the
viewer should see, WHY it serves the story, WHEN it applies, and HOW it is
composed — in a form that can be validated, versioned, retrieved by semantics,
parameterized, and evaluated.

P5.3 is directing knowledge only. It recommends, ranks, parameterizes, records
evidence, and learns preference. It does not render, execute providers, deliver,
repair video, override ShotPlan, override MotionPlan, or declare final QA PASS.

The canonical chain is:

    Recipe + Parameters -> ShotPlan / MotionPlan (suggestions)
                        -> RendererBackend
                        -> Candidate Video
                        -> P5.1 Editorial Review
                        -> Recipe Performance Evidence
                        -> Creative Memory

P5.3 produces the suggestions on the left. The canonical outputs on the right
remain owned by P1 (ShotPlan, MotionPlan), P5.2 (RendererBackend), and P5.1
(editorial review).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

# ── Enumerations ────────────────────────────────────────────────────────


class RecipeFamily(StrEnum):
    """The eight canonical recipe families."""

    COMPOSITION = "COMPOSITION"
    CAMERA = "CAMERA"
    EVIDENCE = "EVIDENCE"
    EXPLAINER = "EXPLAINER"
    EMOTIONAL = "EMOTIONAL"
    PRESENTER = "PRESENTER"
    PRODUCT = "PRODUCT"
    DATA = "DATA"


class QualificationState(StrEnum):
    """Recipe qualification lifecycle.

    EXPERIMENTAL recipes must not auto-promote. Promotion requires real
    production usage and evidence. P5.1 provider unavailability defers
    editorial qualification but does not block core qualification.
    """

    EXPERIMENTAL = "EXPERIMENTAL"
    QUALIFIED = "QUALIFIED"
    DEPRECATED = "DEPRECATED"
    REJECTED = "REJECTED"


class AdoptionMode(StrEnum):
    """How an external reference may be used.

    REFERENCE_ONLY: read for ideas, no code import.
    CONTRACT_ADOPT: adopt the interface/contract pattern.
    RECIPE_SOURCE: the reference is a source of recipe structures.
    CODE_ADOPT_ALLOWED: code may be imported under its license.
    REJECT: do not use.
    """

    REFERENCE_ONLY = "REFERENCE_ONLY"
    CONTRACT_ADOPT = "CONTRACT_ADOPT"
    RECIPE_SOURCE = "RECIPE_SOURCE"
    CODE_ADOPT_ALLOWED = "CODE_ADOPT_ALLOWED"
    REJECT = "REJECT"


#: Validated viewpoint vocabulary. POV describes the viewer/character viewpoint
#: relationship; FPV describes high-speed first-view flight/traversal as a
#: camera platform and motion behavior. They are not synonyms.
VALID_VIEWPOINTS = frozenset({
    "POV", "FPV", "FIRST_PERSON", "THIRD_PERSON",
    "OVER_SHOULDER", "EYE_LEVEL", "LOW_ANGLE", "HIGH_ANGLE",
})

#: Validated stabilization vocabulary. A platform characteristic, decoupled from
#: the camera path. TRIPOD is a platform; STATIC is a camera state. A tripod
#: shot is typically static, but the platform and the state are different facts.
VALID_STABILIZATION = frozenset({
    "TRIPOD", "HANDHELD", "GIMBAL", "CRANE", "DRONE", "STATIC_MOUNT",
})

#: Validated camera-path vocabulary. The route the camera travels, decoupled
#: from the platform that carries it and from focal-length behavior.
VALID_PATHS = frozenset({
    "PAN", "TILT", "DOLLY", "TRUCK", "ELEVATE", "ORBIT", "FOLLOW", "STATIC_PATH",
})

#: Validated focal behavior. ZOOM changes focal length with a static camera;
#: DOLLY translates the camera with a static focal length. push_in is neither
#: until the recipe declares which, which is exactly the ambiguity this
#: vocabulary exists to remove.
VALID_FOCAL_BEHAVIOR = frozenset({
    "ZOOM", "STATIC_FOCAL", "RACK_FOCUS",
})

#: Validated temporal structure. A temporal/editorial property, not a camera
#: movement. LONG_TAKE asserts continuous capture; SLOW_MOTION asserts
#: playback rate. They are different axes.
VALID_TEMPORAL_STRUCTURE = frozenset({
    "SINGLE_TAKE", "LONG_TAKE", "MONTAGE", "SLOW_MOTION", "TIME_LAPSE",
})

#: Validated trigger vocabulary. A structured phase-transition signal, not a
#: free-text entry description.
VALID_TRIGGERS = frozenset({
    "BEAT_START", "NARRATION_CUE", "EVIDENCE_READY", "MANUAL", "NONE",
})

#: Validated camera-height vocabulary. Where the camera sits vertically.
VALID_CAMERA_HEIGHT = frozenset({
    "GROUND", "LOW", "EYE_LEVEL", "HIGH", "OVERHEAD",
})

#: Validated camera-angle vocabulary. The tilt of the optical axis, distinct
#: from camera height: a HIGH camera can still shoot at EYE_LEVEL angle.
VALID_CAMERA_ANGLE = frozenset({
    "EYE_LEVEL", "LOW_ANGLE", "HIGH_ANGLE", "DUTCH", "TOP_DOWN",
})

#: Validated focal-length detail. Optical categories, not millimeter claims
#: no renderer here could verify.
VALID_FOCAL_LENGTH = frozenset({
    "WIDE", "NORMAL", "TELEPHOTO",
})

#: Validated focus behavior. RACK means focus changes during the shot;
#: LOCKED means it does not. Distinct from depth of field, which describes
#: how much is in focus, not whether focus moves.
VALID_FOCUS = frozenset({
    "LOCKED_FOCUS", "RACK_FOCUS",
})

#: Validated depth of field. How much of the frame is in focus.
VALID_DEPTH_OF_FIELD = frozenset({
    "SHALLOW", "MEDIUM", "DEEP",
})

#: Validated start/end framing states. Closed vocabulary so a state change
#: (level → rotated) is a verifiable fact, not a turn of phrase. A ROLL is
#: start_state != end_state on rotation; a static dutch angle has identical
#: start and end states.
VALID_FRAME_STATES = frozenset({
    "LEVEL", "ROTATED_15", "ROTATED_30", "ROTATED_45",
    "WIDE_VIEW", "CLOSE_VIEW", "DETAIL_VIEW",
    "CENTERED_SUBJECT", "SUBJECT_LEFT", "SUBJECT_RIGHT",
})

#: Validated hold-constraint vocabulary. A hold requirement the plan must
#: satisfy, not an aspiration in a description string.
VALID_HOLD_CONSTRAINTS = frozenset({
    "NO_HOLD", "HOLD_1S", "HOLD_2S", "HOLD_UNTIL_CUE",
})


class DeprecationReason(StrEnum):
    """Why a recipe was deprecated."""

    QUALITY_REGRESSION = "QUALITY_REGRESSION"
    RENDERER_INCOMPATIBILITY = "RENDERER_INCOMPATIBILITY"
    OVERUSE = "OVERUSE"
    PROFILE_MISMATCH = "PROFILE_MISMATCH"
    ACCESSIBILITY_ISSUE = "ACCESSIBILITY_ISSUE"


# ── Provenance ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SourceProvenance:
    """Where a recipe came from."""

    origin: str  # "hand_crafted", "reference_derived", "profile_derived"
    source_repository: str = ""
    source_revision: str = ""
    source_file_or_doc: str = ""
    adoption_type: str = ""  # IDEA, CONTRACT, RECIPE_STRUCTURE, PARAMETER_VALUES, CODE, ASSET
    notes: str = ""


@dataclass(frozen=True)
class LicenseProvenance:
    """License information for a recipe or reference."""

    license: str = ""
    license_confidence: str = ""  # "verified", "inferred", "unknown"
    license_url: str = ""
    source_file_or_doc: str = ""
    commercial_use_allowed: bool = False
    attribution_required: bool = False


# ── Terminal state ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class TerminalState:
    """Where a shot or sequence ends, stated explicitly.

    A terminal state names the final camera state, the final composition, and
    the final hold requirement. Free-text exit_behavior cannot express "the
    camera must be static on the subject for at least 2 seconds" in a way any
    downstream stage can verify; this can.
    """

    final_camera_state: str = ""
    final_composition: str = ""
    final_hold_requirement: str = ""


# ── Dolly-zoom specification ──────────────────────────────────────────────


@dataclass(frozen=True)
class DollyZoomSpec:
    """The verifiable structure of a dolly-zoom (Hitchcock zoom).

    A dolly-zoom is not "push in plus zoom out". It is four coupled facts:
    the camera genuinely translates, the focal length genuinely changes, the
    two move in inverse coupling, and the subject's screen size is constrained
    throughout. Absent any one of these, the claim is not a dolly-zoom.
    """

    camera_translation: str = ""
    focal_length_change: str = ""
    inverse_coupling: bool = False
    subject_screen_size_constraint: str = ""


def validate_dolly_zoom(spec: DollyZoomSpec) -> tuple[bool, list[str]]:
    """Whether a spec is a genuine dolly-zoom. Returns (valid, violations)."""
    violations: list[str] = []
    if not spec.camera_translation:
        violations.append("MISSING_CAMERA_TRANSLATION")
    if not spec.focal_length_change:
        violations.append("MISSING_FOCAL_LENGTH_CHANGE")
    if not spec.inverse_coupling:
        violations.append("MISSING_INVERSE_COUPLING")
    if not spec.subject_screen_size_constraint:
        violations.append("MISSING_SUBJECT_SCREEN_SIZE_CONSTRAINT")
    return (not violations), violations


def is_dolly_zoom(spec: DollyZoomSpec) -> bool:
    """True only when all four coupling facts hold."""
    valid, _ = validate_dolly_zoom(spec)
    return valid


# ── Combined movement ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class MovementPhase:
    """One phase of a combined camera movement."""

    camera_action: str = ""
    path: str = ""
    velocity_profile: str = ""
    hold_constraints: str = ""


@dataclass(frozen=True)
class MovementSequence:
    """A structured multi-phase camera movement.

    Sequence -> Phase[] -> Trigger -> TerminalState. This replaces free-text
    entry/hold/exit descriptions for any movement complex enough to need more
    than one phase. A single-phase move does not need this; a combined move
    cannot be expressed without it.
    """

    phases: tuple[MovementPhase, ...] = ()
    trigger: str = ""
    terminal_state: TerminalState = field(default_factory=TerminalState)


# ── Recipe ──────────────────────────────────────────────────────────────


@dataclass
class CinematicRecipe:
    """A reusable directing pattern.

    This is the canonical recipe representation. It is a typed structured
    contract — not a prompt string. A prompt hint may be attached as
    ``prompt_hint`` but it is never the canonical form.

    The recipe describes WHAT the viewer should see, WHY it serves the story,
    WHEN it applies, and HOW it is composed. It is renderer-neutral: it declares
    requirements and preferences, never renderer-specific implementation.
    """

    recipe_id: str
    version: str
    recipe_family: RecipeFamily

    name: str
    description: str

    # Semantic targeting
    intent: str = ""
    semantic_roles: list[str] = field(default_factory=list)
    profile_compatibility: list[str] = field(default_factory=list)
    beat_roles: list[str] = field(default_factory=list)

    # Composition
    composition: str = ""
    subject_role: str = ""
    evidence_role: str = ""
    background_role: str = ""

    # Behavior
    entry_behavior: str = ""
    hold_behavior: str = ""
    exit_behavior: str = ""

    # Camera and motion
    camera_behavior: str = ""
    motion_behavior: str = ""
    transition_behavior: str = ""

    # Validated cinematic primitives. All optional: existing recipes predate
    # them and must keep working. When present, each value must belong to its
    # vocabulary — a primitive that accepts anything is a label, not a primitive.
    viewpoint: str = ""
    stabilization: str = ""
    path: str = ""
    focal_behavior: str = ""
    temporal_structure: str = ""
    trigger: str = ""
    terminal_state: TerminalState = field(default_factory=TerminalState)

    # Camera optics and framing. All optional with validated vocabularies.
    # Each participates: validation rejects out-of-vocabulary values at
    # construction, and parameterization emits present values into the plan.
    camera_height: str = ""
    camera_angle: str = ""
    focal_length_detail: str = ""
    focus: str = ""
    depth_of_field: str = ""

    # Phased-movement states. When a recipe traverses states (a ROLL goes
    # from LEVEL to ROTATED_45), the change is a verifiable fact here rather
    # than a turn of phrase in a description. Both participate in the plan.
    start_state: str = ""
    end_state: str = ""
    hold_constraints: str = ""

    # Actions this recipe must never produce. Enforced, not advisory:
    # parameterization rejects a plan whose resolved motion matches one.
    forbidden_actions: list[str] = field(default_factory=list)

    # Dolly-zoom coupling. Present only when the recipe genuinely couples
    # translation with focal change; validated as a unit. A plain dolly or
    # plain zoom carries no spec and must never be read as a dolly-zoom.
    dolly_zoom: DollyZoomSpec | None = None

    # Combined movement. Present only for multi-phase moves; validated for
    # structural completeness (phases, trigger, terminal state).
    movement_sequence: MovementSequence | None = None

    # Timing
    duration_range: tuple[float, float] = (2.0, 5.0)
    information_density_range: tuple[float, float] = (0.3, 0.7)

    # Assets and capabilities
    required_assets: list[str] = field(default_factory=list)
    optional_assets: list[str] = field(default_factory=list)
    required_capabilities: list[str] = field(default_factory=list)

    # Parameterization
    parameters: dict[str, Any] = field(default_factory=dict)
    constraints: dict[str, Any] = field(default_factory=dict)
    anti_patterns: list[str] = field(default_factory=list)

    # Renderer neutrality
    renderer_requirements: list[str] = field(default_factory=list)
    renderer_preferences: list[str] = field(default_factory=list)

    # Provenance
    source_provenance: SourceProvenance = field(
        default_factory=lambda: SourceProvenance(origin="hand_crafted")
    )
    license_provenance: LicenseProvenance = field(default_factory=LicenseProvenance)

    # Qualification
    qualification_state: QualificationState = QualificationState.EXPERIMENTAL
    quality_evidence: list[dict[str, Any]] = field(default_factory=list)

    # Usage
    usage_statistics: dict[str, Any] = field(default_factory=dict)

    # Optional prompt hint — never the canonical representation
    prompt_hint: str = ""

    # Metadata
    created_at: str = ""
    deprecated_at: str = ""
    deprecation_reason: str = ""

    def __post_init__(self) -> None:
        if not self.recipe_id:
            raise ValueError("RECIPE_ID_REQUIRED")
        self._validate_primitives()
        if not self.version:
            raise ValueError("RECIPE_VERSION_REQUIRED")
        if not self.name:
            raise ValueError("RECIPE_NAME_REQUIRED")
        if self.prompt_hint and len(self.prompt_hint) > 500:
            raise ValueError("PROMPT_HINT_TOO_LONG")

    def _validate_primitives(self) -> None:
        """Every non-empty primitive must belong to its vocabulary."""
        checks = (
            (self.viewpoint, VALID_VIEWPOINTS, "VIEWPOINT"),
            (self.stabilization, VALID_STABILIZATION, "STABILIZATION"),
            (self.path, VALID_PATHS, "PATH"),
            (self.focal_behavior, VALID_FOCAL_BEHAVIOR, "FOCAL_BEHAVIOR"),
            (self.temporal_structure, VALID_TEMPORAL_STRUCTURE, "TEMPORAL_STRUCTURE"),
            (self.trigger, VALID_TRIGGERS, "TRIGGER"),
            (self.camera_height, VALID_CAMERA_HEIGHT, "CAMERA_HEIGHT"),
            (self.camera_angle, VALID_CAMERA_ANGLE, "CAMERA_ANGLE"),
            (self.focal_length_detail, VALID_FOCAL_LENGTH, "FOCAL_LENGTH"),
            (self.focus, VALID_FOCUS, "FOCUS"),
            (self.depth_of_field, VALID_DEPTH_OF_FIELD, "DEPTH_OF_FIELD"),
            (self.start_state, VALID_FRAME_STATES, "START_STATE"),
            (self.end_state, VALID_FRAME_STATES, "END_STATE"),
            (self.hold_constraints, VALID_HOLD_CONSTRAINTS, "HOLD_CONSTRAINTS"),
        )
        for value, allowed, name in checks:
            if value and value not in allowed:
                raise ValueError(f"INVALID_{name}:{value}")
        if self.dolly_zoom is not None:
            valid, violations = validate_dolly_zoom(self.dolly_zoom)
            if not valid:
                raise ValueError(
                    f"INVALID_DOLLY_ZOOM:{';'.join(violations)}"
                )
            if self.path != "DOLLY" or self.focal_behavior != "ZOOM":
                raise ValueError(
                    "DOLLY_ZOOM_MISMATCH:spec requires path=DOLLY and focal_behavior=ZOOM"
                )
        if self.movement_sequence is not None:
            self._validate_movement_sequence(self.movement_sequence)

    @staticmethod
    def _validate_movement_sequence(seq: MovementSequence) -> None:
        """A combined movement must have phases, a trigger, and a terminal."""
        if not seq.phases:
            raise ValueError("INVALID_MOVEMENT_SEQUENCE:no phases")
        for index, phase in enumerate(seq.phases):
            if not phase.camera_action:
                raise ValueError(f"INVALID_MOVEMENT_SEQUENCE:phase {index} has no camera_action")
            if phase.path and phase.path not in VALID_PATHS:
                raise ValueError(f"INVALID_MOVEMENT_SEQUENCE:phase {index} bad path:{phase.path}")
        if not seq.trigger:
            raise ValueError("INVALID_MOVEMENT_SEQUENCE:no trigger")
        if seq.trigger not in VALID_TRIGGERS:
            raise ValueError(f"INVALID_MOVEMENT_SEQUENCE:bad trigger:{seq.trigger}")

    @property
    def qualified_id(self) -> str:
        return f"{self.recipe_id}@{self.version}"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["recipe_family"] = self.recipe_family.value
        d["qualification_state"] = self.qualification_state.value
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CinematicRecipe:
        data = dict(data)
        data["recipe_family"] = RecipeFamily(data.get("recipe_family", "COMPOSITION"))
        data["qualification_state"] = QualificationState(
            data.get("qualification_state", "EXPERIMENTAL")
        )
        if "source_provenance" in data and isinstance(data["source_provenance"], dict):
            data["source_provenance"] = SourceProvenance(**data["source_provenance"])
        if "license_provenance" in data and isinstance(data["license_provenance"], dict):
            data["license_provenance"] = LicenseProvenance(**data["license_provenance"])
        if "terminal_state" in data and isinstance(data["terminal_state"], dict):
            data["terminal_state"] = TerminalState(**data["terminal_state"])
        if "dolly_zoom" in data and isinstance(data["dolly_zoom"], dict):
            data["dolly_zoom"] = DollyZoomSpec(**data["dolly_zoom"])
        if "movement_sequence" in data and isinstance(data["movement_sequence"], dict):
            seq = data["movement_sequence"]
            phases = tuple(
                MovementPhase(**p) if isinstance(p, dict) else p
                for p in seq.get("phases", ())
            )
            terminal = seq.get("terminal_state", {})
            data["movement_sequence"] = MovementSequence(
                phases=phases,
                trigger=seq.get("trigger", ""),
                terminal_state=(
                    TerminalState(**terminal)
                    if isinstance(terminal, dict) else terminal
                ),
            )
        return cls(**data)

    def content_hash(self) -> str:
        """Hash of the recipe content, excluding metadata that changes on every use."""
        canonical = {
            "recipe_id": self.recipe_id,
            "version": self.version,
            "recipe_family": self.recipe_family.value,
            "name": self.name,
            "description": self.description,
            "intent": self.intent,
            "semantic_roles": sorted(self.semantic_roles),
            "profile_compatibility": sorted(self.profile_compatibility),
            "beat_roles": sorted(self.beat_roles),
            "composition": self.composition,
            "subject_role": self.subject_role,
            "evidence_role": self.evidence_role,
            "background_role": self.background_role,
            "entry_behavior": self.entry_behavior,
            "hold_behavior": self.hold_behavior,
            "exit_behavior": self.exit_behavior,
            "camera_behavior": self.camera_behavior,
            "motion_behavior": self.motion_behavior,
            "transition_behavior": self.transition_behavior,
            "viewpoint": self.viewpoint,
            "stabilization": self.stabilization,
            "path": self.path,
            "focal_behavior": self.focal_behavior,
            "temporal_structure": self.temporal_structure,
            "trigger": self.trigger,
            "terminal_state": asdict(self.terminal_state),
            "camera_height": self.camera_height,
            "camera_angle": self.camera_angle,
            "focal_length_detail": self.focal_length_detail,
            "focus": self.focus,
            "depth_of_field": self.depth_of_field,
            "start_state": self.start_state,
            "end_state": self.end_state,
            "hold_constraints": self.hold_constraints,
            "forbidden_actions": sorted(self.forbidden_actions),
            "dolly_zoom": asdict(self.dolly_zoom) if self.dolly_zoom else None,
            "movement_sequence": (
                {
                    "phases": [asdict(p) for p in self.movement_sequence.phases],
                    "trigger": self.movement_sequence.trigger,
                    "terminal_state": asdict(self.movement_sequence.terminal_state),
                }
                if self.movement_sequence else None
            ),
            "duration_range": list(self.duration_range),
            "information_density_range": list(self.information_density_range),
            "required_assets": sorted(self.required_assets),
            "optional_assets": sorted(self.optional_assets),
            "required_capabilities": sorted(self.required_capabilities),
            "parameters": self.parameters,
            "constraints": self.constraints,
            "anti_patterns": sorted(self.anti_patterns),
            "renderer_requirements": sorted(self.renderer_requirements),
            "renderer_preferences": sorted(self.renderer_preferences),
            "prompt_hint": self.prompt_hint,
        }
        blob = json.dumps(canonical, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()


# ── Recipe Parameters ───────────────────────────────────────────────────


@dataclass
class RecipeParameters:
    """Parameterization of a recipe for a specific shot.

    These are suggestions that feed into ShotPlan / MotionPlan. P5.3 does not
    produce ShotPlan or MotionPlan directly — it produces these parameters,
    which the P1 pipeline uses to build the canonical plans.
    """

    duration: float | None = None
    camera_strength: float | None = None
    motion_amplitude: float | None = None
    crop: str | None = None
    position: tuple[float, float] | None = None
    scale: float | None = None
    easing: str | None = None
    evidence_focus: str | None = None
    entry_delay: float | None = None
    hold_ratio: float | None = None
    exit_ratio: float | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if self.position is not None:
            d["position"] = list(self.position)
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RecipeParameters:
        data = dict(data)
        if "position" in data and isinstance(data["position"], list):
            data["position"] = tuple(data["position"])
        return cls(**data)


# ── Recipe Candidate ────────────────────────────────────────────────────


@dataclass
class RecipeCandidate:
    """A recipe retrieved for a specific visual beat."""

    recipe_id: str
    version: str

    semantic_match: float = 0.0
    profile_match: float = 0.0
    asset_match: float = 0.0
    capability_match: float = 0.0
    duration_match: float = 0.0

    variety_score: float = 0.0
    historical_quality_score: float = 0.0

    constraint_violations: list[str] = field(default_factory=list)

    selection_score: float = 0.0
    selection_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── Selection Evidence ──────────────────────────────────────────────────


@dataclass
class RecipeSelectionEvidence:
    """Traceability for why a recipe was selected over others.

    Must answer: WHY_THIS_RECIPE, WHY_NOT_THE_OTHER_RECIPES.
    """

    visual_beat_id: str
    candidate_recipe_ids: list[str] = field(default_factory=list)
    selected_recipe_id: str = ""
    selected_version: str = ""

    selection_factors: dict[str, float] = field(default_factory=dict)
    rejected_candidates: list[str] = field(default_factory=list)
    rejection_reasons: dict[str, str] = field(default_factory=dict)

    creative_variety_context: dict[str, Any] = field(default_factory=dict)
    historical_evidence: dict[str, Any] = field(default_factory=dict)

    timestamp: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── Qualification Evidence ──────────────────────────────────────────────


@dataclass
class QualificationEvidence:
    """Evidence supporting a recipe's qualification state."""

    render_success: bool = False
    profile_compatibility: bool = False
    motion_purpose: bool = False
    information_density: bool = False
    text_dominance: bool = False
    evidence_compatibility: bool = False
    accessibility: bool = False

    p5_1_review: str = ""  # "PASS", "FAIL", "DEFERRED_BY_PROVIDER", ""
    pairwise_result: str = ""

    usage_count: int = 0
    failure_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── Reference Repository ────────────────────────────────────────────────


@dataclass
class ReferenceRepository:
    """An external project in the reference corpus.

    This is not a dependency registry. It records what is reusable, whether it
    is architecture or recipe, whether it is renderer-specific, its license,
    and how it may be adopted. No code is cloned, installed, or executed.
    """

    repository: str
    revision: str
    category: str

    license: str = ""
    license_confidence: str = ""

    agent_interface: str = ""
    renderer: str = ""

    capabilities: list[str] = field(default_factory=list)
    interesting_patterns: list[str] = field(default_factory=list)

    recipe_sources: list[str] = field(default_factory=list)
    architecture_patterns: list[str] = field(default_factory=list)

    security_notes: list[str] = field(default_factory=list)

    adoption_mode: AdoptionMode = AdoptionMode.REFERENCE_ONLY

    def __post_init__(self) -> None:
        if isinstance(self.adoption_mode, str):
            self.adoption_mode = AdoptionMode(self.adoption_mode)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["adoption_mode"] = self.adoption_mode.value
        return d


# ── Reference Grammar ───────────────────────────────────────────────────


@dataclass
class ReferenceGrammar:
    """Abstract grammar extracted from a reference video.

    This is VIDEO -> ABSTRACT GRAMMAR, not VIDEO -> COPY SHOT LIST. It captures
    distributions, families, relationships, and general pacing — never ordered
    shot sequences, timing vectors, or asset sequences.
    """

    reference_id: str

    pacing_signature: str = ""
    shot_duration_distribution: dict[str, float] = field(default_factory=dict)

    composition_families: list[str] = field(default_factory=list)
    camera_families: list[str] = field(default_factory=list)
    transition_families: list[str] = field(default_factory=list)
    motion_language: list[str] = field(default_factory=list)

    speaker_evidence_pattern: str = ""
    information_density_curve: list[float] = field(default_factory=list)
    narrative_arc: str = ""

    caption_behavior: str = ""
    audio_visual_relationship: str = ""

    distinctive_patterns: list[str] = field(default_factory=list)

    source_provenance: SourceProvenance = field(
        default_factory=lambda: SourceProvenance(origin="reference_derived")
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── Creative Variety Score ──────────────────────────────────────────────


@dataclass
class CreativeVarietyScore:
    """How much a recipe choice would add variety to the current cut.

    Variety is the lowest priority. Semantic correctness, evidence correctness,
    renderer capability, and profile compatibility all outrank it. Variety must
    never override semantic match.
    """

    recent_recipe_frequency: float = 0.0
    same_family_frequency: float = 0.0
    neighbor_repetition: float = 0.0
    profile_repetition: float = 0.0
    composition_repetition: float = 0.0
    transition_repetition: float = 0.0

    variety_score: float = 0.0
    semantic_override: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── Recipe Usage Record ─────────────────────────────────────────────────


@dataclass
class RecipeUsageRecord:
    """One usage of a recipe in production, recorded for the CreativeLedger."""

    recipe_id: str
    recipe_version: str
    profile: str
    content_id: str
    beat_role: str

    parameters: dict[str, Any] = field(default_factory=dict)

    usage_time: str = ""
    neighboring_recipes: list[str] = field(default_factory=list)

    p5_1_result: str = ""
    quality_evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


__all__ = [
    "VALID_CAMERA_ANGLE",
    "VALID_CAMERA_HEIGHT",
    "VALID_DEPTH_OF_FIELD",
    "VALID_FOCAL_BEHAVIOR",
    "VALID_FOCAL_LENGTH",
    "VALID_FOCUS",
    "VALID_FRAME_STATES",
    "VALID_HOLD_CONSTRAINTS",
    "VALID_PATHS",
    "VALID_STABILIZATION",
    "VALID_TEMPORAL_STRUCTURE",
    "VALID_TRIGGERS",
    "VALID_VIEWPOINTS",
    "AdoptionMode",
    "CinematicRecipe",
    "CreativeVarietyScore",
    "DeprecationReason",
    "DollyZoomSpec",
    "LicenseProvenance",
    "MovementPhase",
    "MovementSequence",
    "QualificationEvidence",
    "QualificationState",
    "RecipeCandidate",
    "RecipeFamily",
    "RecipeParameters",
    "RecipeSelectionEvidence",
    "RecipeUsageRecord",
    "ReferenceGrammar",
    "ReferenceRepository",
    "SourceProvenance",
    "TerminalState",
    "is_dolly_zoom",
    "validate_dolly_zoom",
]
