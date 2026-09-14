"""HEVI-native script and production-executable storyboard composition."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

from hevi.obase.creative import (
    SceneIntent,
    Script,
    ScriptScene,
    Storyboard,
    StoryboardScene,
    StoryboardShot,
)


@dataclass(frozen=True)
class ScriptBundle:
    script: Script
    scenes: tuple[ScriptScene, ...]


class ScriptModule:
    def create(
        self,
        *,
        project_id: UUID,
        title: str,
        scenes: tuple[SceneIntent, ...],
        language: str = "en",
    ) -> ScriptBundle:
        if not scenes:
            raise ValueError("SCRIPT_EMPTY")
        script_scenes = tuple(
            ScriptScene(
                scene_id=scene.object_id,
                location=str(scene.location_id or "UNSPECIFIED"),
                action=scene.objective,
                dialogue=(),
                production_notes=tuple(
                    item for item in (scene.obstacle, scene.turn, scene.outcome) if item
                ),
            )
            for scene in scenes
        )
        script = Script(
            project_id=project_id,
            title=title,
            scene_ids=tuple(scene.scene_id for scene in script_scenes),
            language=language,
        )
        return ScriptBundle(script, script_scenes)


@dataclass(frozen=True)
class StoryboardBundle:
    storyboard: Storyboard
    shots: tuple[StoryboardShot, ...]


class StoryboardModule:
    """Map scene intent into downstream shot constraints, not renderer config."""

    def create(
        self,
        *,
        project_id: UUID,
        script: Script,
        scenes: tuple[ScriptScene, ...],
        default_duration_ms: int = 3000,
    ) -> StoryboardBundle:
        if default_duration_ms <= 0:
            raise ValueError("STORYBOARD_INVALID_DURATION")
        if {scene.scene_id for scene in scenes} != set(script.scene_ids):
            raise ValueError("STORYBOARD_SCENE_REF_MISMATCH")
        shots: list[StoryboardShot] = []
        storyboard_scenes: list[StoryboardScene] = []
        for scene in scenes:
            shot = StoryboardShot(
                shot_id=uuid4(),
                visual_intent=scene.action,
                framing="MEDIUM",
                subject=None,
                action=scene.action,
                environment=scene.location,
                duration_ms=default_duration_ms,
            )
            shots.append(shot)
            storyboard_scenes.append(
                StoryboardScene(scene_id=scene.scene_id, shot_ids=(shot.shot_id,))
            )
        storyboard = Storyboard(
            project_id=project_id,
            title=script.title,
            script_id=script.object_id,
            scenes=tuple(storyboard_scenes),
            shots=tuple(shots),
        )
        return StoryboardBundle(storyboard, tuple(shots))


__all__ = ["ScriptBundle", "ScriptModule", "StoryboardBundle", "StoryboardModule"]
