"""Scene blueprint validation and planning boundary."""

from __future__ import annotations

from hevi.narrative.models import SceneBlueprint


def validate_scene(scene: SceneBlueprint) -> None:
    if not scene.scene_id or not scene.sequence_id:
        raise ValueError("scene and sequence ids are required")
    if not scene.purpose or not scene.objective.text:
        raise ValueError("scene purpose and objective are required")
    if not scene.characters:
        raise ValueError("scene requires at least one character")
