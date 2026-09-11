"""Cinematic and Director shot DTOs → canonical scene/beat/shot records."""

from __future__ import annotations

from collections.abc import Iterable

from hevi.cinematic.schemas import CineShot
from hevi.cinematic.schemas import Scene as CineScene
from hevi.director.pipeline_schemas import ShotListItem
from hevi.production_graph.domain import (
    Beat,
    CameraSpec,
    CanonicalShot,
    GenerationIntent,
    Scene,
    ShotSize,
)
from hevi.production_graph.ids import stable_id


def _shot_size(value: str) -> ShotSize:
    normalized = value.strip().lower()
    aliases = {
        "远景": ShotSize.WIDE,
        "全景": ShotSize.FULL,
        "中景": ShotSize.MEDIUM,
        "近景": ShotSize.MEDIUM_CLOSE,
        "特写": ShotSize.CLOSE_UP,
    }
    return aliases.get(
        normalized, ShotSize(normalized) if normalized in ShotSize else ShotSize.MEDIUM
    )


def cinematic_scene_to_scene(
    scene: CineScene, *, project_id: str, revision_id: str, episode_id: str
) -> Scene:
    return Scene(
        id=stable_id("scene", f"{project_id}:cinematic:{scene.scene_id}"),
        project_id=project_id,
        revision_id=revision_id,
        episode_id=episode_id,
        character_ids=[stable_id("character", f"{project_id}:{cid}") for cid in scene.characters],
        location_id=(
            stable_id("location", f"{project_id}:{scene.space_anchor}")
            if scene.space_anchor
            else None
        ),
        purpose=scene.slug,
        legacy_ids={"cinematic.scene_id": scene.scene_id},
    )


def cinematic_beats_to_beats(
    scene: CineScene, *, project_id: str, revision_id: str, scene_id: str
) -> list[Beat]:
    result: list[Beat] = []
    for order, beat in enumerate(scene.beats):
        dialogue = beat.dialogue
        result.append(
            Beat(
                id=stable_id("beat", f"{project_id}:cinematic:{beat.beat_id}"),
                project_id=project_id,
                revision_id=revision_id,
                scene_id=scene_id,
                order=order,
                action=beat.action,
                dialogue=dialogue.text if dialogue else "",
                speaker_id=(
                    stable_id("character", f"{project_id}:{dialogue.speaker}") if dialogue else None
                ),
                emotion=beat.emotion_expression,
                performance={"atmosphere": beat.atmosphere, "lighting": beat.lighting},
                legacy_ids={"cinematic.beat_id": beat.beat_id},
            )
        )
    return result


def cinematic_shots_to_shots(
    shots: Iterable[CineShot], *, project_id: str, revision_id: str, scene_id: str
) -> list[CanonicalShot]:
    """Project CineShots without importing their final provider prompt."""

    result: list[CanonicalShot] = []
    for shot in shots:
        character_ids = [
            stable_id("character", f"{project_id}:{character_id}")
            for character_id in shot.on_screen
        ]
        result.append(
            CanonicalShot(
                id=stable_id("shot", f"{project_id}:cinematic:{shot.shot_id}"),
                project_id=project_id,
                revision_id=revision_id,
                scene_id=scene_id,
                beat_ids=[
                    stable_id("beat", f"{project_id}:cinematic:{bid}") for bid in shot.beat_ids
                ],
                character_ids=character_ids,
                camera=CameraSpec(
                    shot_size=_shot_size(shot.camera.shot_size or shot.shot_size),
                    movement=shot.camera.movement,
                ),
                dialogue=([shot.dialogue_inline.text] if shot.dialogue_inline else []),
                duration_target=shot.est_duration_s,
                action_description=shot.emotion_expression,
                cinematography_notes=", ".join(
                    part for part in (shot.atmosphere, shot.lighting) if part
                ),
                generation_intent=(
                    GenerationIntent.ANIMATION
                    if shot.style == "animation"
                    else GenerationIntent.IMAGE_TO_VIDEO
                ),
                legacy_ids={"cinematic.shot_id": shot.shot_id},
            )
        )
    return result


def director_shot_to_shot(
    shot: ShotListItem, *, project_id: str, revision_id: str, scene_id: str
) -> CanonicalShot:
    """Adapt the existing Director shot list into a provider-free shot."""

    return CanonicalShot(
        id=stable_id("shot", f"{project_id}:director:{shot.shot_id}"),
        project_id=project_id,
        revision_id=revision_id,
        scene_id=scene_id,
        character_ids=[
            stable_id("character", f"{project_id}:{name}") for name in shot.character_names
        ],
        prop_ids=[stable_id("prop", f"{project_id}:{name}") for name in shot.prop_names],
        blocking=list(shot.blocking),
        camera=CameraSpec(
            shot_size=_shot_size(shot.shot_size),
            movement=shot.camera,
            angle=shot.camera_angle or "eye_level",
            azimuth_deg=shot.azimuth_deg,
        ),
        duration_target=shot.duration_s,
        action_description=shot.visual_prompt,
        cinematography_notes=shot.camera,
        generation_intent=GenerationIntent.IMAGE_TO_VIDEO,
        legacy_ids={"director.shot_id": shot.shot_id},
    )


__all__ = [
    "cinematic_beats_to_beats",
    "cinematic_scene_to_scene",
    "cinematic_shots_to_shots",
    "director_shot_to_shot",
]
