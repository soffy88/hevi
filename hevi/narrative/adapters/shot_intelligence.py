"""Project a SceneBlueprint into provider-neutral ShotIntent values."""

from __future__ import annotations

from hevi.cinematic.shot_intelligence.models import ShotIntent
from hevi.narrative.models import SceneBlueprint


def scene_to_shot_intents(scene: SceneBlueprint, line: str) -> list[ShotIntent]:
    return [ShotIntent(
        line=line,
        scene_intent=scene.visual_intent or scene.purpose,
        narrative_purpose=scene.objective.text,
        subject=scene.characters[0] if scene.characters else "",
        dialogue_present=bool(scene.dialogue_intent),
        narration_present=not bool(scene.dialogue_intent),
        pacing=scene.pace,
        style=scene.emotional_tone,
    )]
