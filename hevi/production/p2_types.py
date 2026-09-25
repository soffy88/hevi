"""HEVI P2 Production Profiles / Creative Direction — canonical types.

This module implements the P2 visual narrative chain extensions:
ProductionProfile → CreativeDirectionPlan → Profile-specific constraints
→ VisualBeat → AssetResolution → ShotPlan → MotionPlan → EditPlan
→ Proof → QA → Final

All types are extensions of existing P0/P1 infrastructure, not replacements.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import Field

from hevi.layer4_legacy.obase_support.creative import (
    CreativeObject,
    ProvenanceRef,
)

# ──────────────────────────────────────────────────────────────────────
# PROFILE IDENTITIES
# ──────────────────────────────────────────────────────────────────────

class ProfileId(StrEnum):
    EMOTIONAL_BOOK_REVIEW = "EMOTIONAL_BOOK_REVIEW"
    WHITEBOARD_EXPLAINER = "WHITEBOARD_EXPLAINER"
    SCIENCE_EXPLAINER = "SCIENCE_EXPLAINER"
    HISTORICAL_NARRATIVE = "HISTORICAL_NARRATIVE"


# ──────────────────────────────────────────────────────────────────────
# VISUAL LANGUAGE / GRAMMAR
# ──────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class VisualLanguage:
    """Visual language specification for a profile."""
    aesthetic: str  # cinematic, whiteboard, scientific, historical
    color_palette: tuple[str, ...] = ()
    typography: dict[str, str] = field(default_factory=dict)
    iconography: tuple[str, ...] = ()
    composition_rules: tuple[str, ...] = ()


@dataclass(frozen=True)
class ShotGrammar:
    """Shot grammar specification for a profile."""
    allowed_roles: tuple[str, ...] = ()
    preferred_roles: tuple[str, ...] = ()
    forbidden_sequences: tuple[tuple[str, str], ...] = ()
    max_role_repetition: int = 2
    role_transition_preferences: dict[str, tuple[str, ...]] = field(default_factory=dict)
    duration_tendencies: dict[str, tuple[float, float]] = field(default_factory=dict)


@dataclass(frozen=True)
class MotionGrammar:
    """Motion grammar specification for a profile."""
    allowed_purposes: tuple[str, ...] = ()
    preferred_purposes: tuple[str, ...] = ()
    forbidden_patterns: tuple[str, ...] = ()
    motion_density: str = "moderate"  # sparse, moderate, dense
    motion_intensity: str = "moderate"  # subtle, moderate, dynamic
    transition_motion_policy: str = "cut"  # cut, fade, match, motion


@dataclass(frozen=True)
class EditGrammar:
    """Edit grammar specification for a profile."""
    preferred_cut_reasons: tuple[str, ...] = ()
    transition_policy: dict[str, str] = field(default_factory=dict)
    rhythm: str = "information_driven"  # information_driven, rhythmic, montage
    continuity_priority: str = "strict"  # strict, flexible, loose
    montage_policy: str = "none"  # none, allowed, preferred
    ending_policy: str = "payoff"  # payoff, open, cliffhanger


# ──────────────────────────────────────────────────────────────────────
# ASSET POLICY / TEXT POLICY / CAPTION POLICY / MUSIC POLICY
# ──────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class AssetPolicy:
    """Asset policy specification for a profile."""
    provenance_weight: float = 1.0
    action_match_weight: float = 1.0
    emotional_relevance_weight: float = 1.0
    semantic_validity_weight: float = 1.0
    historical_accuracy_weight: float = 1.0
    drawable_compatibility_weight: float = 1.0
    element_density_constraints: dict[str, float] = field(default_factory=dict)
    preferred_sources: tuple[str, ...] = ()
    forbidden_sources: tuple[str, ...] = ()


@dataclass(frozen=True)
class TextPolicy:
    """Text policy specification for a profile."""
    allowed_text_types: tuple[str, ...] = ()
    max_lines_per_shot: int = 2
    max_chars_per_line: int = 40
    emphasis_markers: tuple[str, ...] = ()
    style_tokens: tuple[str, ...] = ()


@dataclass(frozen=True)
class CaptionPolicy:
    """Caption policy specification for a profile."""
    placement: str = "bottom"  # bottom, top, center, side
    density: str = "moderate"  # sparse, moderate, dense
    max_lines: int = 2
    emphasis: str = "key_terms"  # key_terms, emotional_beats, all
    style_token: str = "default"


@dataclass(frozen=True)
class MusicPolicy:
    """Music policy specification for a profile."""
    required: bool = False
    role: str = "support"  # lead, support, atmosphere
    ducking_policy: str = "aggressive"  # aggressive, moderate, gentle
    energy_curve: str = "match_narrative"  # match_narrative, steady, arc
    forbidden_genres: tuple[str, ...] = ()


# ──────────────────────────────────────────────────────────────────────
# PROFILE POLICIES / QA EXTENSIONS
# ──────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ProfilePolicies:
    """Complete profile policy bundle."""
    visual_language: VisualLanguage
    shot_grammar: ShotGrammar
    motion_grammar: MotionGrammar
    edit_grammar: EditGrammar
    asset_policy: AssetPolicy
    text_policy: TextPolicy
    caption_policy: CaptionPolicy
    music_policy: MusicPolicy
    forbidden_patterns: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProfileQAExtension:
    """Profile-specific QA gate extension."""
    gate_id: str
    description: str
    severity: str = "HARD"  # HARD, SOFT
    check_fn: str = ""  # reference to check function name


# ──────────────────────────────────────────────────────────────────────
# PRODUCTION PROFILE
# ──────────────────────────────────────────────────────────────────────

class ProductionProfile(CreativeObject):
    """Canonical production profile definition."""
    profile_id: str
    profile_version: str = "1.0"
    content_domain: str = ""
    audience_intent: str = ""
    emotional_intent: str = ""
    policies: ProfilePolicies
    qa_extensions: tuple[ProfileQAExtension, ...] = ()
    required_capabilities: tuple[str, ...] = ()
    forbidden_patterns: tuple[str, ...] = ()
    preferred_renderers: tuple[str, ...] = ("remotion",)
    allowed_renderers: tuple[str, ...] = ("remotion", "ffmpeg", "hyperframes", "manim")

    def stable_hash(self) -> str:
        """Hash excluding mutable fields."""
        payload = self.model_dump(
            mode="json",
            exclude_none=True,
            exclude={"created_at", "updated_at", "content_hash"},
        )
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


# ──────────────────────────────────────────────────────────────────────
# PROFILE REGISTRY
# ──────────────────────────────────────────────────────────────────────

class ProductionProfileRegistry:
    """Single canonical registry for all production profiles."""

    def __init__(self) -> None:
        self._profiles: dict[str, ProductionProfile] = {}
        self._versions: dict[str, list[str]] = {}

    def register(self, profile: ProductionProfile) -> None:
        key = f"{profile.profile_id}@v{profile.profile_version}"
        if key in self._profiles:
            raise ValueError(f"Profile already registered: {key}")
        self._profiles[key] = profile
        if profile.profile_id not in self._versions:
            self._versions[profile.profile_id] = []
        self._versions[profile.profile_id].append(profile.profile_version)

    def resolve(self, profile_id: str, version: str | None = None) -> ProductionProfile | None:
        if version:
            return self._profiles.get(f"{profile_id}@v{version}")
        # Return latest version
        versions = self._versions.get(profile_id, [])
        if not versions:
            return None
        latest = sorted(versions, key=lambda v: tuple(map(int, v.split("."))))[-1]
        return self._profiles.get(f"{profile_id}@v{latest}")

    def validate(self, profile_id: str, version: str) -> tuple[bool, list[str]]:
        profile = self.resolve(profile_id, version)
        if not profile:
            return False, [f"Profile not found: {profile_id}@v{version}"]
        errors = []
        # Validate required fields
        if not profile.policies.shot_grammar.allowed_roles:
            errors.append("shot_grammar.allowed_roles is empty")
        if not profile.policies.motion_grammar.allowed_purposes:
            errors.append("motion_grammar.allowed_purposes is empty")
        if not profile.policies.edit_grammar.preferred_cut_reasons:
            errors.append("edit_grammar.preferred_cut_reasons is empty")
        if not profile.policies.asset_policy.preferred_sources:
            errors.append("asset_policy.preferred_sources is empty")
        return len(errors) == 0, errors

    def list_profiles(self) -> list[ProductionProfile]:
        return list(self._profiles.values())

    def compatibility_check(self, profile_id: str, version: str, capabilities: tuple[str, ...]) -> tuple[bool, list[str]]:
        profile = self.resolve(profile_id, version)
        if not profile:
            return False, [f"Profile not found: {profile_id}@v{version}"]
        missing = [c for c in profile.required_capabilities if c not in capabilities]
        return len(missing) == 0, missing


# ──────────────────────────────────────────────────────────────────────
# CREATIVE DIRECTION PLAN
# ──────────────────────────────────────────────────────────────────────

class CreativeDirectionPlan(CreativeObject):
    """Instantiated creative direction for a specific production run."""
    profile_id: str
    profile_version: str
    creative_objective: str = ""
    audience_effect: str = ""
    visual_language: VisualLanguage
    dominant_visual_modes: tuple[str, ...] = ()
    shot_role_preferences: dict[str, float] = Field(default_factory=dict)
    motion_preferences: dict[str, float] = Field(default_factory=dict)
    edit_preferences: dict[str, float] = Field(default_factory=dict)
    asset_strategy: dict[str, Any] = Field(default_factory=dict)
    text_strategy: dict[str, Any] = Field(default_factory=dict)
    caption_strategy: dict[str, Any] = Field(default_factory=dict)
    music_strategy: dict[str, Any] = Field(default_factory=dict)
    hook_strategy: str = ""
    development_strategy: str = ""
    payoff_strategy: str = ""
    pacing_strategy: str = ""
    forbidden_patterns: tuple[str, ...] = ()
    profile_revision: int = 0
    lineage: tuple[str, ...] = Field(default_factory=tuple)


# ──────────────────────────────────────────────────────────────────────
# PROFILE FINGERPRINT
# ──────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ProfileFingerprint:
    """Structural fingerprint of a profile's creative behavior."""
    profile_id: str
    profile_version: str
    shot_role_histogram: dict[str, int] = field(default_factory=dict)
    motion_purpose_histogram: dict[str, int] = field(default_factory=dict)
    asset_type_histogram: dict[str, int] = field(default_factory=dict)
    cut_reason_histogram: dict[str, int] = field(default_factory=dict)
    text_density: float = 0.0
    average_shot_duration: float = 0.0
    visual_mode_distribution: dict[str, int] = field(default_factory=dict)

    def similarity(self, other: ProfileFingerprint) -> float:
        """Compute structural similarity (0-1)."""
        all_keys = set(self.shot_role_histogram.keys()) | set(other.shot_role_histogram.keys())
        if not all_keys:
            return 1.0
        diff = sum(abs(self.shot_role_histogram.get(k, 0) - other.shot_role_histogram.get(k, 0)) for k in all_keys)
        total = sum(self.shot_role_histogram.values()) + sum(other.shot_role_histogram.values())
        return 1.0 - (diff / total) if total > 0 else 1.0

    def distinct_from(self, other: ProfileFingerprint, threshold: float = 0.7) -> bool:
        """Check if structurally distinct from another profile."""
        return self.similarity(other) < threshold


# ──────────────────────────────────────────────────────────────────────
# PROFILE SPECIFIC EXTENSIONS
# ──────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class BookSource:
    """Verified book source for EMOTIONAL_BOOK_REVIEW."""
    title: str
    author: str
    edition: str = ""
    source_provenance: ProvenanceRef | None = None
    verified: bool = False


@dataclass(frozen=True)
class WhiteboardScenePlan:
    """Semantic whiteboard scene plan for WHITEBOARD_EXPLAINER."""
    scene_id: UUID
    semantic_primitives: tuple[str, ...]  # stroke_draw, arrow_draw, highlight_draw, etc.
    temporal_sequence: tuple[float, ...]  # timestamps
    spatial_layout: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ScienceAssetProvenance:
    """Provenance for scientific assets."""
    source_institution: str
    dataset_uri: str | None = None
    verification_method: str = ""
    is_generated: bool = False
    generation_method: str = ""


@dataclass(frozen=True)
class HistoryAssetProvenance:
    """Provenance for historical assets."""
    source_type: str  # archival, map, document, painting, museum, generated
    source_institution: str = ""
    date_created: str = ""
    is_reconstruction: bool = False
    reconstruction_method: str = ""


# ──────────────────────────────────────────────────────────────────────
# PROFILE QUALIFICATION GATES
# ──────────────────────────────────────────────────────────────────────

P2_GATES = (
    "PROFILE_RESOLUTION",
    "PROFILE_LINEAGE",
    "CREATIVE_DIRECTION_CONSUMED",
    "SHOT_GRAMMAR",
    "MOTION_GRAMMAR",
    "EDIT_GRAMMAR",
    "PROFILE_ASSET_POLICY",
    "PROFILE_FORBIDDEN_PATTERNS",
    "PROFILE_VISUAL_IDENTITY",
    "PROFILE_ISOLATION",
    "BOOK_SOURCE_TRUTH",
    "BOOK_EMOTIONAL_COHERENCE",
    "WHITEBOARD_DRAW_SEMANTICS",
    "WHITEBOARD_TIMING",
    "SCIENCE_PROVENANCE",
    "SCIENCE_SEMANTIC_VALIDITY",
    "HISTORY_TEMPORAL_VALIDITY",
    "HISTORY_PROVENANCE",
    "PROFILE_RESOLUTION",
    "PROFILE_LINEAGE",
    "CREATIVE_DIRECTION_CONSUMED",
)

ADVERSARIAL_P2_GATES = (
    "CASE_P2_1_BYPASS_P1_VISUALBEAT",
    "CASE_P2_2_DIRECT_RENDER",
    "CASE_P2_3_SECOND_QA_AUTHORITY",
    "CASE_P2_4_SAME_VISUAL_GRAMMAR",
    "CASE_P2_5_WHITEBOARD_RANDOM_ANIMATION",
    "CASE_P2_6_SCIENCE_GENERIC_SUBSTITUTE",
    "CASE_P2_7_HISTORY_FAKE_ARCHIVAL",
    "CASE_P2_8_BOOK_HALLUCINATED_QUOTE",
    "CASE_P2_9_STALE_SHOTPLAN",
    "CASE_P2_10_AUDIO_REGENERATED",
    "CASE_P2_11_PROFILE_LEAK",
    "CASE_P2_12_SILENT_RANDOM_SELECTION",
)

__all__ = [
    "ADVERSARIAL_P2_GATES",
    "P2_GATES",
    "AssetPolicy",
    "BookSource",
    "CaptionPolicy",
    "CreativeDirectionPlan",
    "EditGrammar",
    "HistoryAssetProvenance",
    "MotionGrammar",
    "MusicPolicy",
    "ProductionProfile",
    "ProductionProfileRegistry",
    "ProfileFingerprint",
    "ProfileId",
    "ProfilePolicies",
    "ProfileQAExtension",
    "ScienceAssetProvenance",
    "ShotGrammar",
    "TextPolicy",
    "VisualLanguage",
    "WhiteboardScenePlan",
]
