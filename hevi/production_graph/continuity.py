"""Canonical continuity constraint derivation."""

from __future__ import annotations

from collections.abc import Iterable

from hevi.production_graph.domain import (
    CanonicalShot,
    CharacterState,
    ConstraintSeverity,
    ConstraintType,
    ContinuityConstraint,
)
from hevi.production_graph.ids import stable_id


def derive_continuity_constraints(
    shot: CanonicalShot,
    *,
    character_states: Iterable[CharacterState] = (),
) -> list[ContinuityConstraint]:
    constraints: list[ContinuityConstraint] = []
    for state in character_states:
        if state.character_id not in shot.character_ids:
            continue
        if state.look_variant_id:
            constraints.append(
                ContinuityConstraint(
                    id=stable_id("continuity", f"{shot.id}:look:{state.character_id}"),
                    project_id=shot.project_id,
                    revision_id=shot.revision_id,
                    type=ConstraintType.WARDROBE,
                    scope=f"shot:{shot.id}:character:{state.character_id}",
                    severity=ConstraintSeverity.HARD,
                    expected=state.look_variant_id,
                    source=f"character_state:{state.id}",
                )
            )
        if state.location_id:
            constraints.append(
                ContinuityConstraint(
                    id=stable_id("continuity", f"{shot.id}:location:{state.character_id}"),
                    project_id=shot.project_id,
                    revision_id=shot.revision_id,
                    type=ConstraintType.LOCATION,
                    scope=f"shot:{shot.id}",
                    severity=ConstraintSeverity.HARD,
                    expected=state.location_id,
                    source=f"character_state:{state.id}",
                )
            )
    if shot.camera.axis_id:
        constraints.append(
            ContinuityConstraint(
                id=stable_id("continuity", f"{shot.id}:axis"),
                project_id=shot.project_id,
                revision_id=shot.revision_id,
                type=ConstraintType.CAMERA_AXIS,
                scope=f"shot:{shot.id}",
                expected=shot.camera.axis_id,
                source="shot.camera.axis_id",
            )
        )
    return constraints


__all__ = ["derive_continuity_constraints"]
