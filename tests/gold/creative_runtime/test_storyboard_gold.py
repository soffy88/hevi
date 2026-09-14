"""Gold behaviour for production-executable storyboard handoff."""

from __future__ import annotations

from uuid import uuid4

import pytest

from hevi.cinematic.shot_intelligence import (
    ShotIntent,
    ShotSelector,
    canonical_json,
    load_plan,
    persist_plan,
    replay_plan,
    validate_shot_plan,
)
from hevi.creative.omodul import ScriptModule, StoryboardModule
from hevi.obase.creative import SceneIntent


def _scenes(project_id):
    return (
        SceneIntent(
            project_id=project_id,
            sequence=1,
            purpose="enter",
            objective="open the gate",
            outcome="gate opens",
        ),
        SceneIntent(
            project_id=project_id,
            sequence=2,
            purpose="turn",
            objective="choose the route",
            outcome="route chosen",
        ),
    )


def _storyboard(project_id):
    bundle = ScriptModule().create(
        project_id=project_id, title="Owned Script", scenes=_scenes(project_id)
    )
    storyboard = StoryboardModule().create(
        project_id=project_id, script=bundle.script, scenes=bundle.scenes
    )
    return bundle, storyboard


def test_script_to_shot_plan_roundtrip(tmp_path) -> None:
    project_id = uuid4()
    _, storyboard = _storyboard(project_id)
    intents = [
        ShotIntent(
            line=shot.action,
            scene_intent=shot.visual_intent,
            narrative_purpose="establishing" if index == 0 else "action",
            subject=shot.subject or "Mara",
            target_duration_s=shot.duration_ms / 1000.0,
        )
        for index, shot in enumerate(storyboard.shots)
    ]
    plan = ShotSelector().plan(intents)
    path = persist_plan(plan, tmp_path / "shot-plan.json")
    loaded = load_plan(path)
    assert canonical_json(loaded) == canonical_json(plan)
    assert replay_plan(plan) == plan
    validation = validate_shot_plan(loaded)
    assert validation.status == "PASS"
    assert all(shot.provenance for shot in loaded.shots)


def test_storyboard_rejects_scene_ref_mismatch() -> None:
    project_id = uuid4()
    script = ScriptModule().create(
        project_id=project_id, title="Owned Script", scenes=_scenes(project_id)
    ).script
    with pytest.raises(ValueError, match="STORYBOARD_SCENE_REF_MISMATCH"):
        StoryboardModule().create(project_id=project_id, script=script, scenes=())
