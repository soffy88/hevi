"""Frozen Narrative Intelligence v1 contract snapshot definition."""

from __future__ import annotations

NARRATIVE_CONTRACT_VERSION = 1


def contract_snapshot() -> dict[str, object]:
    return {
        "contract_version": NARRATIVE_CONTRACT_VERSION,
        "schema_versions": {
            "StoryBible": "1.0",
            "Character": "1.0",
            "CharacterRelationship": "1.0",
            "TimelineEvent": "1.0",
            "SceneBlueprint": "1.0",
            "NarrativeRevision": "1.0",
            "RevisionReceipt": "1.0",
            "NarrativeProvenance": "1.0",
            "NarrativeQualityReport": "1.0",
        },
        "StoryBible": [
            "project_id", "schema_version", "premise", "theme", "dramatic_question",
            "characters", "relationships", "world_rules", "locations", "timeline",
            "established_facts", "continuity_constraints", "episodes", "sequences",
            "style_profile", "narrative_voice", "unresolved_threads", "resolved_threads",
            "source_refs", "revision", "updated_at",
        ],
        "Character": [
            "id", "name", "aliases", "role", "motivation", "goal", "fear", "conflict",
            "traits", "knowledge_state", "relationship_ids", "arc", "visual_identity_ref", "voice_identity_ref",
        ],
        "CharacterRelationship": [
            "id", "from_character", "to_character", "relation_type", "strength", "trust",
            "conflict", "public_state", "private_state", "valid_from", "valid_to",
        ],
        "TimelineEvent": ["id", "label", "order", "timestamp", "source_refs"],
        "SceneBlueprint": [
            "scene_id", "sequence_id", "purpose", "objective", "obstacle", "conflict", "turn", "outcome",
            "characters", "location", "time", "incoming_state", "outgoing_state", "required_facts",
            "forbidden_claims", "dialogue_intent", "visual_intent", "emotional_tone", "pace", "source_refs",
            "evidence_refs", "continuity_constraints",
        ],
        "NarrativeRevision": ["asset_id", "base_revision", "new_revision", "change_type", "reason", "author", "created_at"],
        "RevisionReceipt": ["asset_id", "previous_revision", "new_revision", "committed", "validation"],
        "NarrativeProvenance": [
            "project_revision", "story_bible_revision", "episode_revision", "scene_revision", "llm_provider",
            "llm_model", "source_refs", "evidence_refs", "continuity_report_id", "review_report_id", "shot_plan_id",
        ],
        "NarrativeQualityReport": ["status", "findings", "ready"],
        "ShotAdapter": {
            "input": "SceneBlueprint",
            "output": "list[ShotIntent]",
            "direction": "narrative -> scene -> shot; no reverse canonical mutation",
            "renderer_dependency": False,
        },
    }
