from __future__ import annotations

import pytest

from hevi.cinematic.schemas import Beat, CineShot, CineShotCamera, Scene
from hevi.production_graph import (
    CanonicalShot,
    Character,
    Episode,
    ProductionGraphSnapshot,
    ProductionProject,
    ProductionRevision,
)
from hevi.production_graph.adapters.cinematic import (
    cinematic_beats_to_beats,
    cinematic_scene_to_scene,
    cinematic_shots_to_shots,
)


def test_cinematic_projection_drops_provider_transport_fields() -> None:
    legacy_scene = Scene(
        scene_id="S1",
        characters=["C1"],
        beats=[Beat(beat_id="B1", action="walk")],
    )
    legacy_shot = CineShot(
        shot_id="SH1",
        scene_id="S1",
        beat_ids=["B1"],
        on_screen=["C1"],
        camera=CineShotCamera(shot_size="close_up", movement="push_in"),
        prompt="walk toward the door",
    )
    scene = cinematic_scene_to_scene(
        legacy_scene, project_id="p", revision_id="r", episode_id="episode"
    )
    beats = cinematic_beats_to_beats(
        legacy_scene, project_id="p", revision_id="r", scene_id=scene.id
    )
    shots = cinematic_shots_to_shots(
        [legacy_shot], project_id="p", revision_id="r", scene_id=scene.id
    )

    payload = shots[0].model_dump(mode="json")
    assert payload["action_description"] == ""
    assert "prompt" not in payload
    assert "provider" not in payload
    assert shots[0].camera.movement == "push_in"
    assert beats[0].action == "walk"


def test_canonical_shot_rejects_provider_specific_fields() -> None:
    with pytest.raises(ValueError):
        CanonicalShot.model_validate(
            {"project_id": "p", "scene_id": "s", "seedance_image_indices": [1]}
        )


def test_scene_beat_shot_are_referentially_integrated() -> None:
    project = ProductionProject(user_id="u")
    revision = ProductionRevision(project_id=project.id)
    project = project.model_copy(update={"current_revision_id": revision.id})
    legacy_scene = Scene(
        scene_id="S1",
        characters=["C1"],
        beats=[Beat(beat_id="B1", action="walk")],
    )
    scene = cinematic_scene_to_scene(
        legacy_scene, project_id=project.id, revision_id=revision.id, episode_id="episode"
    )
    episode = Episode(project_id=project.id, revision_id=revision.id, id="episode")
    beats = cinematic_beats_to_beats(
        legacy_scene, project_id=project.id, revision_id=revision.id, scene_id=scene.id
    )
    shots = cinematic_shots_to_shots(
        [CineShot(shot_id="SH1", scene_id="S1", beat_ids=["B1"])],
        project_id=project.id,
        revision_id=revision.id,
        scene_id=scene.id,
    )
    snapshot = ProductionGraphSnapshot(
        project=project,
        revision=revision,
        characters=[
            Character(
                project_id=project.id,
                revision_id=revision.id,
                id=scene.character_ids[0],
                canonical_name="C1",
            )
        ],
        episodes=[episode],
        scenes=[scene],
        beats=beats,
        shots=shots,
    )
    snapshot.validate_referential_integrity()
