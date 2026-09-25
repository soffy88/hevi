"""HEVI P2 — canonical ProductionProfile definitions + registry.

Single canonical registry for the four P2 profiles. Profiles CONFIGURE and
CONSTRAIN the canonical P0/P1 chain; they never own completion authority.
"""

from __future__ import annotations

from uuid import uuid4

from hevi.production.p2_types import (
    AssetPolicy,
    CaptionPolicy,
    EditGrammar,
    MotionGrammar,
    MusicPolicy,
    ProductionProfile,
    ProductionProfileRegistry,
    ProfilePolicies,
    ProfileQAExtension,
    ShotGrammar,
    TextPolicy,
    VisualLanguage,
)

_PROJECT_ID = uuid4()

_BOOK_POLICIES = ProfilePolicies(
    visual_language=VisualLanguage(
        aesthetic="cinematic",
        color_palette=("warm", "restrained"),
        typography={"primary": "serif"},
        iconography=("book", "human", "metaphor"),
        composition_rules=("book_anchor", "human_context", "no_bullet_list"),
    ),
    shot_grammar=ShotGrammar(
        allowed_roles=("ESTABLISH", "DETAIL", "FOLLOW", "REVEAL", "EXPLAIN", "COMPARE", "PAYOFF"),
        preferred_roles=("ESTABLISH", "DETAIL", "PAYOFF"),
        forbidden_sequences=(("ESTABLISH", "ESTABLISH"),),
        max_role_repetition=2,
        role_transition_preferences={"ESTABLISH": ("DETAIL", "FOLLOW", "REVEAL")},
        duration_tendencies={"ESTABLISH": (2.0, 5.0)},
    ),
    motion_grammar=MotionGrammar(
        allowed_purposes=("REVEAL_STRUCTURE", "FOCUS_DETAIL", "FOLLOW_SUBJECT", "SHOW_SCALE", "CONNECT_RELATIONSHIP"),
        preferred_purposes=("FOCUS_DETAIL", "REVEAL_STRUCTURE"),
        forbidden_patterns=("random_zoom", "random_pan", "constant_slow_zoom"),
        motion_density="sparse",
        motion_intensity="subtle",
        transition_motion_policy="cut",
    ),
    edit_grammar=EditGrammar(
        preferred_cut_reasons=("NEW_INFORMATION", "SUBJECT_CHANGE", "PAYOFF"),
        transition_policy={"default": "CUT"},
        rhythm="information_driven",
        continuity_priority="strict",
        montage_policy="none",
        ending_policy="payoff",
    ),
    asset_policy=AssetPolicy(
        provenance_weight=1.0,
        action_match_weight=0.8,
        emotional_relevance_weight=1.5,
        semantic_validity_weight=1.0,
        preferred_sources=("book_cover", "human_context", "metaphor"),
        forbidden_sources=("ppt_slide", "bullet_list"),
    ),
    text_policy=TextPolicy(
        allowed_text_types=("subtitle", "short_quote", "book_title"),
        max_lines_per_shot=2,
        max_chars_per_line=40,
        emphasis_markers=("quote",),
        style_tokens=("serif",),
    ),
    caption_policy=CaptionPolicy(placement="bottom", density="moderate", max_lines=2),
    music_policy=MusicPolicy(required=False, role="support", ducking_policy="aggressive"),
    forbidden_patterns=("ppt_book_summary", "bullet_list_review", "full_cover_slideshow", "generic_stock_loop"),
)

_WHITEBOARD_POLICIES = ProfilePolicies(
    visual_language=VisualLanguage(
        aesthetic="whiteboard",
        color_palette=("white", "black", "accent"),
        typography={"primary": "handwriting"},
        iconography=("stroke", "arrow", "highlight", "sticker"),
        composition_rules=("draw_structure", "safe_zone", "element_density"),
    ),
    shot_grammar=ShotGrammar(
        allowed_roles=("ESTABLISH", "EXPLAIN", "REVEAL", "DETAIL", "COMPARE", "FOLLOW", "TRANSITION", "PAYOFF"),
        preferred_roles=("EXPLAIN", "DETAIL"),
        forbidden_sequences=(("COMPARE", "COMPARE"),),
        max_role_repetition=2,
        role_transition_preferences={"EXPLAIN": ("DETAIL", "COMPARE", "TRANSITION")},
        duration_tendencies={"EXPLAIN": (3.0, 6.0)},
    ),
    motion_grammar=MotionGrammar(
        allowed_purposes=(
            "REVEAL_STRUCTURE", "CONNECT_RELATIONSHIP", "FOCUS_DETAIL", "TRANSITION_CONTEXT",
            "SHOW_SCALE", "SHOW_ORBIT", "SHOW_COLLAPSE", "FOLLOW_SUBJECT",
        ),
        preferred_purposes=("REVEAL_STRUCTURE", "CONNECT_RELATIONSHIP"),
        forbidden_patterns=("random_animation", "decorative_motion"),
        motion_density="moderate",
        motion_intensity="moderate",
        transition_motion_policy="cut",
    ),
    edit_grammar=EditGrammar(
        preferred_cut_reasons=("NEW_INFORMATION", "ACTION_CHANGE", "CAUSE_EFFECT", "COMPARE"),
        transition_policy={"default": "CUT"},
        rhythm="information_driven",
        continuity_priority="strict",
        montage_policy="none",
        ending_policy="payoff",
    ),
    asset_policy=AssetPolicy(
        drawable_compatibility_weight=1.5,
        element_density_constraints={"max_elements": 6.0},
        preferred_sources=("whiteboard_scene", "diagram", "handwriting"),
        forbidden_sources=("prerendered_video_substitute",),
    ),
    text_policy=TextPolicy(
        allowed_text_types=("subtitle", "handwriting_term", "label"),
        max_lines_per_shot=2,
        max_chars_per_line=24,
        emphasis_markers=("handwriting",),
        style_tokens=("handwriting",),
    ),
    caption_policy=CaptionPolicy(placement="bottom", density="moderate", max_lines=2),
    music_policy=MusicPolicy(required=False, role="atmosphere", ducking_policy="aggressive"),
    forbidden_patterns=("prerendered_whiteboard_video", "random_animation", "text_only_scene"),
)

_SCIENCE_POLICIES = ProfilePolicies(
    visual_language=VisualLanguage(
        aesthetic="scientific",
        color_palette=("deep_space", "accent"),
        typography={"primary": "sans"},
        iconography=("dataset", "diagram", "observation"),
        composition_rules=("source_visible", "scale_visible", "process_visible"),
    ),
    shot_grammar=ShotGrammar(
        allowed_roles=("ESTABLISH", "DETAIL", "EXPLAIN", "COMPARE", "FOLLOW", "REVEAL", "PAYOFF"),
        preferred_roles=("EXPLAIN", "DETAIL", "COMPARE"),
        forbidden_sequences=(("ESTABLISH", "ESTABLISH"),),
        max_role_repetition=2,
        role_transition_preferences={"EXPLAIN": ("DETAIL", "COMPARE", "FOLLOW")},
        duration_tendencies={"EXPLAIN": (3.0, 6.0)},
    ),
    motion_grammar=MotionGrammar(
        allowed_purposes=(
            "REVEAL_STRUCTURE",
            "SHOW_SCALE",
            "SHOW_ORBIT",
            "SHOW_COLLAPSE",
            "CONNECT_RELATIONSHIP",
            "FOCUS_DETAIL",
            "COMPARE_STATE",
            "FOLLOW_SUBJECT",
        ),
        preferred_purposes=("REVEAL_STRUCTURE", "SHOW_SCALE", "SHOW_ORBIT"),
        forbidden_patterns=("decorative_motion", "random_zoom"),
        motion_density="moderate",
        motion_intensity="moderate",
        transition_motion_policy="cut",
    ),
    edit_grammar=EditGrammar(
        preferred_cut_reasons=("NEW_INFORMATION", "SCALE_CHANGE", "CAUSE_EFFECT", "COMPARE", "ACTION_CHANGE"),
        transition_policy={"default": "CUT"},
        rhythm="information_driven",
        continuity_priority="strict",
        montage_policy="none",
        ending_policy="payoff",
    ),
    asset_policy=AssetPolicy(
        provenance_weight=1.5,
        semantic_validity_weight=1.5,
        action_match_weight=1.2,
        preferred_sources=("NASA", "ESA", "NOAA", "USGS", "CERN", "university", "official"),
        forbidden_sources=("generic_galaxy", "generic_stars", "fictional_as_real"),
    ),
    text_policy=TextPolicy(
        allowed_text_types=("subtitle", "label", "scale", "term"),
        max_lines_per_shot=2,
        max_chars_per_line=32,
        emphasis_markers=("term", "scale"),
        style_tokens=("sans",),
    ),
    caption_policy=CaptionPolicy(placement="bottom", density="moderate", max_lines=2),
    music_policy=MusicPolicy(required=False, role="atmosphere", ducking_policy="aggressive"),
    forbidden_patterns=("generic_galaxy_substitute", "fictional_as_real", "text_only_scene"),
)

_HISTORY_POLICIES = ProfilePolicies(
    visual_language=VisualLanguage(
        aesthetic="historical",
        color_palette=("archival", "map", "sepia"),
        typography={"primary": "serif"},
        iconography=("map", "document", "portrait", "timeline"),
        composition_rules=("time_visible", "place_visible", "actor_visible"),
    ),
    shot_grammar=ShotGrammar(
        allowed_roles=("ESTABLISH", "REVEAL", "DETAIL", "COMPARE", "FOLLOW", "EXPLAIN", "TRANSITION", "PAYOFF"),
        preferred_roles=("ESTABLISH", "DETAIL", "COMPARE"),
        forbidden_sequences=(("DETAIL", "DETAIL"),),
        max_role_repetition=2,
        role_transition_preferences={"ESTABLISH": ("REVEAL", "DETAIL", "COMPARE")},
        duration_tendencies={"ESTABLISH": (3.0, 6.0)},
    ),
    motion_grammar=MotionGrammar(
        allowed_purposes=(
            "REVEAL_STRUCTURE", "FOCUS_DETAIL", "TRANSITION_CONTEXT", "CONNECT_RELATIONSHIP",
            "SHOW_SCALE", "FOLLOW_SUBJECT",
        ),
        preferred_purposes=("REVEAL_STRUCTURE", "FOCUS_DETAIL"),
        forbidden_patterns=("random_zoom", "decorative_motion"),
        motion_density="sparse",
        motion_intensity="subtle",
        transition_motion_policy="cut",
    ),
    edit_grammar=EditGrammar(
        preferred_cut_reasons=("NEW_INFORMATION", "SUBJECT_CHANGE", "TEMPORAL_CHANGE", "CAUSE_EFFECT", "COMPARE"),
        transition_policy={"default": "CUT"},
        rhythm="information_driven",
        continuity_priority="strict",
        montage_policy="none",
        ending_policy="payoff",
    ),
    asset_policy=AssetPolicy(
        historical_accuracy_weight=1.5,
        provenance_weight=1.5,
        preferred_sources=("archive", "museum", "map", "document", "verified_photo"),
        forbidden_sources=("ppt_timeline", "fake_archival"),
    ),
    text_policy=TextPolicy(
        allowed_text_types=("subtitle", "date", "place", "name"),
        max_lines_per_shot=2,
        max_chars_per_line=32,
        emphasis_markers=("date", "place"),
        style_tokens=("serif",),
    ),
    caption_policy=CaptionPolicy(placement="bottom", density="moderate", max_lines=2),
    music_policy=MusicPolicy(required=False, role="atmosphere", ducking_policy="aggressive"),
    forbidden_patterns=("ppt_timeline", "static_photo_slideshow", "fake_archival_photo"),
)


def _profile(
    pid: str,
    domain: str,
    audience: str,
    emotional: str,
    policies: ProfilePolicies,
    qa: tuple[ProfileQAExtension, ...],
    caps: tuple[str, ...],
) -> ProductionProfile:
    return ProductionProfile(
        project_id=_PROJECT_ID,
        profile_id=pid,
        profile_version="1.0",
        content_domain=domain,
        audience_intent=audience,
        emotional_intent=emotional,
        policies=policies,
        qa_extensions=qa,
        required_capabilities=caps,
        forbidden_patterns=policies.forbidden_patterns,
    )


def build_default_registry() -> ProductionProfileRegistry:
    reg = ProductionProfileRegistry()
    reg.register(
        _profile(
            "EMOTIONAL_BOOK_REVIEW",
            "emotional book review",
            "emotional resonance",
            "one primary emotion",
            _BOOK_POLICIES,
            (
                ProfileQAExtension(gate_id="BOOK_SOURCE_TRUTH", description="real verifiable book source"),
                ProfileQAExtension(gate_id="BOOK_EMOTIONAL_COHERENCE", description="one emotion coherent arc"),
            ),
            ("edge_tts", "faster_whisper", "remotion", "ffmpeg"),
        )
    )
    reg.register(
        _profile(
            "WHITEBOARD_EXPLAINER",
            "whiteboard process explanation",
            "understand a process",
            "clarity",
            _WHITEBOARD_POLICIES,
            (
                ProfileQAExtension(gate_id="WHITEBOARD_DRAW_SEMANTICS", description="draw primitives tied to semantics"),
                ProfileQAExtension(gate_id="WHITEBOARD_TIMING", description="drawing timing fits narration"),
            ),
            ("edge_tts", "faster_whisper", "remotion", "ffmpeg"),
        )
    )
    reg.register(
        _profile(
            "SCIENCE_EXPLAINER",
            "scientific explanation",
            "understand nature",
            "wonder",
            _SCIENCE_POLICIES,
            (
                ProfileQAExtension(gate_id="SCIENCE_PROVENANCE", description="official science provenance"),
                ProfileQAExtension(gate_id="SCIENCE_SEMANTIC_VALIDITY", description="visual matches action/process"),
            ),
            ("edge_tts", "faster_whisper", "remotion", "ffmpeg"),
        )
    )
    reg.register(
        _profile(
            "HISTORICAL_NARRATIVE",
            "historical narrative",
            "understand change over time",
            "reflection",
            _HISTORY_POLICIES,
            (
                ProfileQAExtension(gate_id="HISTORY_TEMPORAL_VALIDITY", description="time/actor/place coherent"),
                ProfileQAExtension(gate_id="HISTORY_PROVENANCE", description="archival provenance, no fake archival"),
            ),
            ("edge_tts", "faster_whisper", "remotion", "ffmpeg"),
        )
    )
    return reg


_REGISTRY: ProductionProfileRegistry | None = None


def get_registry() -> ProductionProfileRegistry:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = build_default_registry()
    return _REGISTRY


__all__ = ["build_default_registry", "get_registry"]
