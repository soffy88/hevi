"""Compile previs state into existing HEVI scene-stage handoff shapes."""

from __future__ import annotations

from typing import Any

from hevi.previs.oprim.contracts import PrevisScene


def compile_previs_scene(scene: PrevisScene) -> dict[str, Any]:
    errors = scene.validate()
    if errors:
        return {"status": "blocked", "scene": scene.to_dict(), "errors": errors}
    return {
        "status": "planned",
        "scene": scene.to_dict(),
        "scene_stage": {
            "scene_id": scene.scene_id,
            "title": scene.title,
            "characters": [item.label for item in scene.cast],
            "camera_setups": [
                {
                    "id": cue.cue_id,
                    "at_s": cue.time_s,
                    "shot_size": cue.shot_size,
                    "movement": cue.movement,
                    "azimuth_deg": cue.azimuth_deg,
                    "elevation_deg": cue.elevation_deg,
                }
                for cue in scene.cameras
            ],
            "timeline": [
                {"id": cue.cue_id, "start_s": cue.start_s, "end_s": cue.end_s, "prompt": cue.prompt}
                for cue in scene.timeline
            ],
        },
        "handoff": "hevi.director.scene_stage / scene_block_workflow",
    }


__all__ = ["compile_previs_scene"]
