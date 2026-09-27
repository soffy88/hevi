"""HEVI P5.1 — fine-cut contract, knowledge-talk profile, reference style.

``FineCutContract`` is a set of *production constraints* handed to the existing
P1/P2 chain. It is not a second edit pipeline and it owns no rendering: the
contract narrows what P1 and P2 are already allowed to plan.

``KNOWLEDGE_TALK_FINECUT`` is registered into the **existing**
``ProductionProfileRegistry`` singleton (the one P2 already owns) rather than a
new registry, so ``DUPLICATE_*_REGISTRY`` stays 0 while the profile is genuinely
available to profile selection. Its emphasis is evidence density, real
interfaces, speaker/evidence alternation, caption restraint and semantic motion.

Reference videos are *inspiration*, never a source of copy: only rhythm, ratios,
families and behaviour are abstracted (§54, §55).
"""

from __future__ import annotations

import itertools
import re
from dataclasses import asdict, dataclass, field
from typing import Any
from uuid import uuid4

from hevi.ops.p5_1_types import (
    CanonicalArtifact,
    EvidenceSourceType,
    FineCutContract,
    ReferenceStyleProfile,
    RepairScope,
    ShotPresentationRole,
)

# ── Fine-cut contracts per profile (§56) ─────────────────────────────────

#: Editorial contract defaults per existing P2 profile. These constrain P1/P2
#: planning; they never re-plan production themselves.
PROFILE_FINECUT_CONTRACTS: dict[str, FineCutContract] = {
    "KNOWLEDGE_TALK_FINECUT": FineCutContract(
        target_duration_s=0.0,
        shot_density_per_minute=18.0,
        min_shot_s=1.6,
        max_shot_s=7.0,
        speaker_policy="SEMANTIC_ALTERNATION",
        evidence_policy="EVIDENCE_FIRST_REAL_UI",
        caption_policy="RESTRAINED_NO_OCCLUSION",
        motion_policy="SEMANTIC_ONLY",
        transition_policy="MATCHED_TO_BEAT",
        information_density_policy="BALANCED_ONE_LEAD_CHANNEL",
        revision_policy="MAX_3_ROUNDS",
    ),
    "EMOTIONAL_BOOK_REVIEW": FineCutContract(
        target_duration_s=0.0,
        shot_density_per_minute=7.0,
        min_shot_s=3.0,
        max_shot_s=14.0,
        speaker_policy="DIRECT_ADDRESS_PRIORITY",
        evidence_policy="BOOK_EVIDENCE_TRUTH",
        caption_policy="TEXT_RESTRAINT",
        motion_policy="SEMANTIC_SLOW",
        transition_policy="SOFT_DISSOLVE",
        information_density_policy="SPACIOUS",
        revision_policy="MAX_3_ROUNDS",
    ),
    "SCIENCE_EXPLAINER": FineCutContract(
        shot_density_per_minute=14.0,
        min_shot_s=2.0,
        max_shot_s=9.0,
        speaker_policy="SEMANTIC_ALTERNATION",
        evidence_policy="DATA_VISUALIZATION_TRUTH",
        caption_policy="RESTRAINED",
        motion_policy="SEMANTIC_ONLY",
        transition_policy="MATCHED_TO_BEAT",
        information_density_policy="BALANCED",
        revision_policy="MAX_3_ROUNDS",
    ),
    "WHITEBOARD_EXPLAINER": FineCutContract(
        shot_density_per_minute=12.0,
        min_shot_s=2.0,
        max_shot_s=10.0,
        speaker_policy="SEMANTIC_ALTERNATION",
        evidence_policy="DRAWING_SEMANTICS",
        caption_policy="RESTRAINED",
        motion_policy="SEMANTIC_ONLY",
        transition_policy="MATCHED_TO_BEAT",
        information_density_policy="BALANCED",
        revision_policy="MAX_3_ROUNDS",
    ),
    "HISTORICAL_NARRATIVE": FineCutContract(
        shot_density_per_minute=8.0,
        min_shot_s=2.5,
        max_shot_s=12.0,
        speaker_policy="NARRATION_LEAD",
        evidence_policy="ARCHIVAL_TRUTH",
        caption_policy="RESTRAINED",
        motion_policy="SEMANTIC_ONLY",
        transition_policy="MATCHED_TO_BEAT",
        information_density_policy="BALANCED",
        revision_policy="MAX_3_ROUNDS",
    ),
}


def contract_for(profile_id: str) -> FineCutContract:
    """Return the editorial contract for a profile, defaulting to knowledge talk."""
    return PROFILE_FINECUT_CONTRACTS.get(profile_id, PROFILE_FINECUT_CONTRACTS["KNOWLEDGE_TALK_FINECUT"])


def contract_shot_bounds(contract: FineCutContract) -> tuple[float, float]:
    return (contract.min_shot_s, contract.max_shot_s)


# ── KNOWLEDGE_TALK_FINECUT profile extension (§57) ──────────────────────

KNOWLEDGE_TALK_FINECUT = "KNOWLEDGE_TALK_FINECUT"

#: Narration signals that mark a production as knowledge-style talking head.
_KNOWLEDGE_MARKERS = (
    "教程",
    "教你",
    "步骤",
    "实战",
    "配置",
    "安装",
    "部署",
    "接口",
    "api",
    "原理",
    "架构",
    "源码",
    "调试",
    "优化",
    "对比",
    "评测",
    "how to",
    "tutorial",
    "setup",
    "deploy",
    "walkthrough",
    "architecture",
)


def looks_like_knowledge_talk(narration: str, topic: str = "") -> bool:
    text = f"{topic} {narration}".lower()
    return any(marker in text for marker in _KNOWLEDGE_MARKERS)


def register_knowledge_talk_profile() -> str:
    """Register ``KNOWLEDGE_TALK_FINECUT`` into the existing P2 profile registry.

    The registry is P2's single ``ProductionProfileRegistry``; this adds a
    profile to it rather than creating a parallel one, which is what keeps
    ``DUPLICATE_*_REGISTRY == 0`` while still letting profile selection find it.
    """
    from hevi.production.p2_profiles import get_registry
    from hevi.production.p2_types import (
        AssetPolicy,
        CaptionPolicy,
        EditGrammar,
        MotionGrammar,
        MusicPolicy,
        ProductionProfile,
        ProfilePolicies,
        ShotGrammar,
        TextPolicy,
        VisualLanguage,
    )

    registry = get_registry()
    if registry.resolve(KNOWLEDGE_TALK_FINECUT) is not None:
        return KNOWLEDGE_TALK_FINECUT

    policies = ProfilePolicies(
        visual_language=VisualLanguage(
            aesthetic="CLEAN_TECHNICAL",
            color_palette=("#0F172A", "#1E293B", "#38BDF8", "#F8FAFC", "#F97316"),
            typography={"display": "Inter", "body": "Inter", "mono": "JetBrains Mono"},
            iconography=("cursor", "window-chrome", "terminal", "chart"),
            composition_rules=(
                "evidence occupies the frame when a real interface is being shown",
                "speaker never covers live evidence",
                "one lead channel per moment",
            ),
        ),
        shot_grammar=ShotGrammar(
            allowed_roles=("ESTABLISH", "REVEAL", "EXPLAIN", "FOLLOW", "DETAIL", "COMPARE",
                           "TRANSITION", "PAYOFF"),
            preferred_roles=("EXPLAIN", "REVEAL", "DETAIL", "COMPARE"),
            forbidden_sequences=(("EXPLAIN", "EXPLAIN"),),
            max_role_repetition=2,
            duration_tendencies={"EXPLAIN": (2.0, 7.0), "REVEAL": (1.6, 5.0)},
        ),
        motion_grammar=MotionGrammar(
            allowed_purposes=(
                "REVEAL_STRUCTURE", "FOLLOW_SUBJECT", "FOCUS_DETAIL", "CONNECT_RELATIONSHIP",
                "COMPARE_STATE", "SHOW_SCALE", "TRANSITION_CONTEXT",
            ),
            preferred_purposes=("FOCUS_DETAIL", "REVEAL_STRUCTURE", "COMPARE_STATE"),
            forbidden_patterns=("decorative_bounce", "random_zoom", "idle_wiggle"),
            motion_density="LOW",
            motion_intensity="MEDIUM",
            transition_motion_policy="MATCHED_TO_BEAT",
        ),
        edit_grammar=EditGrammar(
            preferred_cut_reasons=("SEMANTIC_SHIFT", "EVIDENCE_ARRIVAL", "ROLE_SWITCH",
                                   "INFORMATION_GAIN"),
            transition_policy={"default": "cut", "evidence_arrival": "short_dissolve"},
            rhythm="SEMANTIC",
            continuity_priority="SEMANTIC",
            montage_policy="NONE",
            ending_policy="PAYOFF_HOLD",
        ),
        text_policy=TextPolicy(
            allowed_text_types=("CAPTION", "LABEL", "DATA_CALLOUT"),
            max_lines_per_shot=2,
            max_chars_per_line=21,
            emphasis_markers=("注意", "重点", "关键"),
            style_tokens=("RESTRAINED", "NO_WALL_OF_TEXT"),
        ),
        caption_policy=CaptionPolicy(
            placement="lower_third",
            density="restrained",
            max_lines=2,
            emphasis="key_terms",
            style_token="must_not_occlude_subject",
        ),
        music_policy=MusicPolicy(required=False, ducking_policy="aggressive"),
        asset_policy=AssetPolicy(
            preferred_sources=(
                "verified_first_party_evidence",
                "verified_real_screenshot",
                "verified_source_asset",
                "licensed_contextual_asset",
                "labelled_generated_visualization",
                "symbolic_visual",
            ),
            forbidden_sources=("unsourced_product_ui", "mock_ui_as_evidence"),
            element_density_constraints={"max_competing_channels": 3},
        ),
        forbidden_patterns=(
            "FAKE_PRODUCT_UI",
            "GENERATED_INTERFACE_AS_REAL",
            "DECORATIVE_MOTION",
            "SPEAKER_FULL_SCREEN_OVER_DEMO",
            "WALL_OF_TEXT",
        ),
    )

    profile = ProductionProfile(
        project_id=uuid4(),
        profile_id=KNOWLEDGE_TALK_FINECUT,
        profile_version="1.0",
        content_domain="KNOWLEDGE_TALK",
        audience_intent="learn a real thing they can verify themselves",
        emotional_intent="trust through proof rather than assertion",
        policies=policies,
        required_capabilities=("edge_tts", "remotion", "ffmpeg"),
        forbidden_patterns=policies.forbidden_patterns,
    )
    registry.register(profile)
    return KNOWLEDGE_TALK_FINECUT


def resolve_profile_id(narration: str, topic: str = "", explicit: str = "") -> str:
    """Resolve which production profile a request belongs to.

    Knowledge talk is detected first because it is the profile whose whole point
    is evidence-first visuals; the P2 selector still owns the fallback.
    """
    if explicit:
        return explicit
    if looks_like_knowledge_talk(narration, topic):
        return KNOWLEDGE_TALK_FINECUT
    return "EMOTIONAL_BOOK_REVIEW"


# ── Real UI evidence requirement (§58) ───────────────────────────────────

#: Claims that assert a product capability. These demand a real interface.
_CAPABILITY_CLAIM = re.compile(
    r"(支持|提供|具备|可以|能够|自带|集成|集成)\s*[^。！？]{0,20}|"
    r"\b(supports?|provides?|ships with|integrates with|allows you to)\b",
    re.IGNORECASE,
)


@dataclass
class EvidenceRequirement:
    """What a capability claim obliges the production to show."""

    claim: str = ""
    requires_real_interface: bool = False
    acceptable: tuple[EvidenceSourceType, ...] = ()
    forbidden: tuple[EvidenceSourceType, ...] = ()
    allowed_fallback: EvidenceSourceType | None = None
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["acceptable"] = [t.value for t in self.acceptable]
        d["forbidden"] = [t.value for t in self.forbidden]
        d["allowed_fallback"] = self.allowed_fallback.value if self.allowed_fallback else None
        return d


def requirement_for_claim(claim: str) -> EvidenceRequirement:
    """Decide what evidence a claim is allowed to be backed by.

    "This product supports X" obliges the video to show the real interface. If
    it cannot be obtained, the honest answer is a *labelled* symbolic
    visualization — never a generated interface passed off as the real one.
    """
    asserts_capability = bool(_CAPABILITY_CLAIM.search(claim or ""))
    if not asserts_capability:
        return EvidenceRequirement(
            claim=claim,
            requires_real_interface=False,
            acceptable=(
                EvidenceSourceType.OFFICIAL_SCREENSHOT,
                EvidenceSourceType.REAL_INTERFACE,
                EvidenceSourceType.DOCUMENT_EXCERPT,
                EvidenceSourceType.OFFICIAL_IMAGE,
                EvidenceSourceType.DATA_VISUALIZATION,
                EvidenceSourceType.REAL_PHOTO,
            ),
            forbidden=(EvidenceSourceType.GENERATED_VISUALIZATION,),
            note="no capability asserted; real sources preferred",
        )
    return EvidenceRequirement(
        claim=claim,
        requires_real_interface=True,
        acceptable=(
            EvidenceSourceType.OFFICIAL_SCREENSHOT,
            EvidenceSourceType.REAL_INTERFACE,
            EvidenceSourceType.DOCUMENT_EXCERPT,
        ),
        forbidden=(EvidenceSourceType.GENERATED_VISUALIZATION,),
        allowed_fallback=EvidenceSourceType.SYMBOLIC,
        note=(
            "capability claim: must show the real product interface, or fall back to "
            "an explicitly labelled symbolic visualization"
        ),
    )


# ── Reference style abstraction (§54, §55) ───────────────────────────────

#: Fields a reference profile may carry. Shot sequences, source footage and
#: protected graphic assets have no field here by construction.
_REFERENCE_FIELDS = (
    "shot_rhythm",
    "speaker_evidence_ratio",
    "transition_family",
    "information_density",
    "caption_behavior",
    "motion_language",
)


@dataclass
class ReferenceDecomposition:
    """Result of abstracting a reference video into style only."""

    profile: ReferenceStyleProfile
    rejected_elements: list[str] = field(default_factory=list)
    ok: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile": self.profile.to_dict(),
            "rejected_elements": self.rejected_elements,
            "ok": self.ok,
        }


def decompose_reference(
    *,
    shot_rhythm: str = "",
    speaker_evidence_ratio: str = "",
    transition_family: str = "",
    information_density: str = "",
    caption_behavior: str = "",
    motion_language: str = "",
    shot_sequence: list[str] | None = None,
    source_assets: list[str] | None = None,
    source_ref: str = "",
) -> ReferenceDecomposition:
    """Abstract a reference into style, refusing to retain any of its content.

    ``REFERENCE_IS_INSPIRATION_NOT_COPY``: any shot sequence or source asset
    handed in is explicitly rejected and recorded, so a caller cannot quietly
    smuggle copyrighted material into the production through this door.
    """
    rejected: list[str] = []
    if shot_sequence:
        rejected.append(f"SHOT_SEQUENCE_REJECTED:{len(shot_sequence)}_shots")
    if source_assets:
        rejected.append(f"SOURCE_ASSETS_REJECTED:{len(source_assets)}_assets")

    profile = ReferenceStyleProfile(
        shot_rhythm=shot_rhythm[:200],
        speaker_evidence_ratio=speaker_evidence_ratio[:200],
        transition_family=transition_family[:200],
        information_density=information_density[:200],
        caption_behavior=caption_behavior[:200],
        motion_language=motion_language[:200],
        source_ref=source_ref[:300],
        inspiration_only=True,
    )
    return ReferenceDecomposition(profile=profile, rejected_elements=rejected, ok=True)


def reference_maps_to_artifact(
    profile: ReferenceStyleProfile, artifact: CanonicalArtifact
) -> bool:
    """Which canonical artifact a reference abstraction is allowed to influence.

    A reference may shape pacing and layout, never the truth of the evidence.
    """
    return artifact in (
        CanonicalArtifact.SHOT_PLAN,
        CanonicalArtifact.VISUAL_BEAT,
        CanonicalArtifact.MOTION_PLAN,
        CanonicalArtifact.CAPTION_STYLE,
    )


# ── Role balance expectation (§21-§25) ──────────────────────────────────


def expected_role_alternation(
    decisions: list[Any], *, minimum_switches: int = 2
) -> tuple[bool, str]:
    """Check a cut actually alternates between speaker and evidence roles.

    §92 requires at least two speaker/evidence role switches in a real
    knowledge video. A cut that never changes role is not a talking-head video
    with evidence, it is a talking head.
    """
    if not decisions:
        return False, "NO_DECISIONS"
    roles = [
        d.role
        for d in decisions
        if d.role
        in (
            ShotPresentationRole.DIRECT_ADDRESS,
            ShotPresentationRole.EMOTIONAL_PRESENCE,
            ShotPresentationRole.EVIDENCE_DOMINANT,
            ShotPresentationRole.DEMONSTRATION,
        )
    ]
    switches = sum(1 for a, b in itertools.pairwise(roles) if a is not b)
    if switches < minimum_switches:
        return False, f"ROLE_SWITCHES_{switches}_BELOW_{minimum_switches}"
    return True, f"ROLE_SWITCHES_{switches}"


def repair_scope_for_role_change(
    current: ShotPresentationRole, desired: ShotPresentationRole
) -> RepairScope:
    """The cheapest repair scope that can change a shot's presentation role."""
    if current is desired:
        return RepairScope.ASSET_ONLY
    if {current, desired} <= {
        ShotPresentationRole.DIRECT_ADDRESS,
        ShotPresentationRole.EMOTIONAL_PRESENCE,
    }:
        return RepairScope.SHOT_ONLY
    if {current, desired} & {
        ShotPresentationRole.EVIDENCE_DOMINANT,
        ShotPresentationRole.DEMONSTRATION,
    }:
        return RepairScope.ASSET_ONLY
    return RepairScope.SHOT_ONLY


__all__ = [
    "KNOWLEDGE_TALK_FINECUT",
    "PROFILE_FINECUT_CONTRACTS",
    "EvidenceRequirement",
    "FineCutContract",
    "ReferenceDecomposition",
    "ReferenceStyleProfile",
    "contract_for",
    "contract_shot_bounds",
    "decompose_reference",
    "expected_role_alternation",
    "looks_like_knowledge_talk",
    "reference_maps_to_artifact",
    "register_knowledge_talk_profile",
    "repair_scope_for_role_change",
    "requirement_for_claim",
    "resolve_profile_id",
]
