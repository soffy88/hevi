"""Bounded narrative working-set construction."""

from __future__ import annotations

from dataclasses import dataclass

from hevi.narrative.models import SceneBlueprint, StoryBible


@dataclass(frozen=True)
class ContextBudget:
    max_tokens: int
    reserved_generation_tokens: int
    priority_classes: tuple[str, ...] = ("P0", "P1", "P2", "P3")


@dataclass(frozen=True)
class NarrativeContext:
    relevant_characters: tuple[str, ...]
    relevant_relationships: tuple[str, ...]
    recent_events: tuple[str, ...]
    required_world_rules: tuple[str, ...]
    open_threads: tuple[str, ...]
    scene_constraints: tuple[str, ...]
    relevant_source_evidence: tuple[str, ...]
    prior_scene_summary: str = ""
    context_truncated: bool = False
    dropped_refs: tuple[str, ...] = ()


class NarrativeContextBuilder:
    def build(self, bible: StoryBible, scene: SceneBlueprint, budget: ContextBudget) -> NarrativeContext:
        characters = tuple(item for item in scene.characters if any(character.id == item for character in bible.characters))
        relationships = tuple(relation.id for relation in bible.relationships if relation.from_character in characters or relation.to_character in characters)
        sources = tuple(dict.fromkeys((*scene.source_refs, *scene.evidence_refs)))
        context = NarrativeContext(
            relevant_characters=characters,
            relevant_relationships=relationships,
            recent_events=tuple(event.id for event in bible.timeline[-3:]),
            required_world_rules=tuple(rule.id for rule in bible.world_rules),
            open_threads=tuple(thread.id for thread in bible.unresolved_threads),
            scene_constraints=tuple(constraint.id for constraint in scene.continuity_constraints),
            relevant_source_evidence=sources,
        )
        refs = sum(len(getattr(context, field)) for field in ("relevant_characters", "relevant_relationships", "recent_events", "required_world_rules", "open_threads", "scene_constraints", "relevant_source_evidence"))
        limit = max(0, budget.max_tokens - budget.reserved_generation_tokens)
        if refs <= limit:
            return context
        dropped = tuple(context.open_threads + context.recent_events)
        return NarrativeContext(context.relevant_characters, context.relevant_relationships, (), context.required_world_rules, (), context.scene_constraints, context.relevant_source_evidence, context.prior_scene_summary, True, dropped)
