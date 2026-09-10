"""First-class, independently lockable shot keyframes."""

from __future__ import annotations

from collections.abc import Iterable

from hevi.production_graph.domain import CanonicalShot, Keyframe, KeyframeRole
from hevi.production_graph.ids import stable_id


class KeyframeLockError(ValueError):
    """Raised when a locked keyframe would be replaced."""


def action_keyframes(shot: CanonicalShot) -> list[Keyframe]:
    """Promote action-arc semantics into START/PEAK/END entities."""

    beats = [item for item in shot.performance.get("action_beats", []) if str(item).strip()]
    if not beats:
        beats = [shot.action_description or "hold the established opening state"]
    states = [
        (KeyframeRole.START, beats[0]),
        (KeyframeRole.PEAK, beats[min(1, len(beats) - 1)]),
        (KeyframeRole.END, beats[-1]),
    ]
    return [
        Keyframe(
            id=stable_id("keyframe", f"{shot.id}:{role.value}"),
            project_id=shot.project_id,
            revision_id=shot.revision_id,
            shot_id=shot.id,
            role=role,
            desired_state={"action": state},
        )
        for role, state in states
    ]


def validate_keyframes(shot: CanonicalShot, keyframes: Iterable[Keyframe]) -> None:
    items = list(keyframes)
    if any(item.shot_id != shot.id for item in items):
        raise ValueError("keyframe belongs to a different shot")
    roles = [item.role for item in items]
    if len(roles) != len(set(roles)):
        raise ValueError("a shot may have at most one keyframe for each role")


def replace_keyframe(existing: Keyframe, replacement: Keyframe) -> Keyframe:
    if existing.id != replacement.id or existing.shot_id != replacement.shot_id:
        raise ValueError("replacement must target the same keyframe identity")
    if existing.locked:
        raise KeyframeLockError(f"keyframe {existing.id} is locked")
    return replacement.model_copy(update={"state_version": existing.state_version + 1})


def lock_keyframe(keyframe: Keyframe) -> Keyframe:
    return keyframe.model_copy(update={"locked": True})


__all__ = ["KeyframeLockError", "action_keyframes", "lock_keyframe", "replace_keyframe", "validate_keyframes"]
