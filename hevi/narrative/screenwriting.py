"""Structured screenwriting intelligence proposals."""

from __future__ import annotations

from dataclasses import dataclass

from hevi.narrative.dramaturgy import DramaturgyPlan, plan_dramaturgy
from hevi.narrative.models import EpisodeBlueprint, SceneBlueprint, StoryBible


@dataclass(frozen=True)
class NarrativeReview:
    status: str
    findings: tuple[str, ...] = ()


class NarrativePlanner:
    """Deterministic planning facade; LLM proposals are validated upstream."""

    def plan_story(self, bible: StoryBible) -> DramaturgyPlan:
        return plan_story(bible)

    def plan_sequence(self, bible: StoryBible, episode: EpisodeBlueprint) -> EpisodeBlueprint:
        return plan_sequence(bible, episode)

    def plan_scene(self, scene: SceneBlueprint) -> SceneBlueprint:
        return plan_scene(scene)


def plan_story(bible: StoryBible) -> DramaturgyPlan:
    return plan_dramaturgy(bible, "CUSTOM")


def plan_sequence(bible: StoryBible, episode: EpisodeBlueprint) -> EpisodeBlueprint:
    return episode


def plan_scene(scene: SceneBlueprint) -> SceneBlueprint:
    return scene


def evaluate_scene(bible: StoryBible, scene: SceneBlueprint) -> NarrativeReview:
    missing = [ref for ref in scene.required_facts if ref not in {fact.id for fact in bible.established_facts}]
    return NarrativeReview("FAIL" if missing else "PASS", tuple(f"missing fact:{ref}" for ref in missing))


def revise_scene(scene: SceneBlueprint, **changes: object) -> SceneBlueprint:
    from dataclasses import replace

    return replace(scene, **changes)  # type: ignore[arg-type]
