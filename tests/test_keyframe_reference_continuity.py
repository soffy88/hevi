from __future__ import annotations

import pytest

from hevi.production_graph import (
    CameraSpec,
    CanonicalShot,
    CharacterState,
    ConstraintType,
    KeyframeLockError,
    KeyframeRole,
    ReferenceBundle,
    ReferenceItem,
    ReferenceLockError,
    ReferenceRole,
    action_keyframes,
    add_reference,
    derive_continuity_constraints,
    lock_keyframe,
    lock_reference,
    replace_keyframe,
    select_reference_view,
    validate_keyframes,
)


def _shot() -> CanonicalShot:
    return CanonicalShot(
        project_id="p",
        revision_id="r",
        scene_id="s",
        character_ids=["c"],
        action_description="open the gate",
        camera=CameraSpec(azimuth_deg=90, axis_id="axis-1"),
        performance={"action_beats": ["reach", "open", "look back"]},
    )


def test_action_beats_become_independent_start_peak_end_keyframes() -> None:
    shot = _shot()
    frames = action_keyframes(shot)
    validate_keyframes(shot, frames)
    assert [frame.role for frame in frames] == [KeyframeRole.START, KeyframeRole.PEAK, KeyframeRole.END]
    assert [frame.desired_state["action"] for frame in frames] == ["reach", "open", "look back"]


def test_locked_keyframe_cannot_be_overwritten() -> None:
    frame = action_keyframes(_shot())[0]
    locked = lock_keyframe(frame)
    with pytest.raises(KeyframeLockError):
        replace_keyframe(locked, locked.model_copy(update={"desired_state": {"action": "other"}}))


def test_camera_orientation_selects_right_view_deterministically() -> None:
    shot = _shot()
    refs = [
        ReferenceItem(
            role=ReferenceRole.CHARACTER_IDENTITY,
            artifact_id="front-artifact",
            metadata={"view": "front"},
        ),
        ReferenceItem(
            role=ReferenceRole.CHARACTER_IDENTITY,
            artifact_id="right-artifact",
            metadata={"view": "right"},
        ),
    ]
    selection = select_reference_view(shot.camera, character_facing_deg=0, references=refs)
    assert selection.view == "right"
    assert selection.item is not None and selection.item.artifact_id == "right-artifact"


def test_missing_orientation_falls_back_to_front_without_fabricating_view() -> None:
    refs = [
        ReferenceItem(
            role=ReferenceRole.CHARACTER_IDENTITY,
            artifact_id="front-artifact",
            metadata={"view": "front"},
        )
    ]
    selection = select_reference_view(
        CameraSpec(), character_facing_deg=None, references=refs
    )
    assert selection.fallback is True
    assert selection.view == "front"


def test_reference_bundle_lock_and_continuity_constraints() -> None:
    shot = _shot()
    bundle = ReferenceBundle(project_id="p", revision_id="r", shot_id=shot.id)
    item = ReferenceItem(
        role=ReferenceRole.CHARACTER_LOOK,
        production_entity_id="c",
        artifact_id="look",
    )
    locked = lock_reference(add_reference(bundle, item))
    with pytest.raises(ReferenceLockError):
        add_reference(locked, item.model_copy(update={"id": "other"}))
    constraints = derive_continuity_constraints(
        shot,
        character_states=[
            CharacterState(
                project_id="p",
                revision_id="r",
                character_id="c",
                look_variant_id="look-v1",
                location_id="loc-1",
            )
        ],
    )
    assert {constraint.type for constraint in constraints} == {
        ConstraintType.WARDROBE,
        ConstraintType.LOCATION,
        ConstraintType.CAMERA_AXIS,
    }
