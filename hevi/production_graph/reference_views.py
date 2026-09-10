"""Deterministic camera-orientation → IdentityPack view selection."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from hevi.production_graph.domain import CameraSpec, ReferenceItem, ReferenceRole

_VIEW_ANGLES = {
    "front": 0.0,
    "front_right_34": 45.0,
    "right": 90.0,
    "profile_right": 90.0,
    "back_right_34": 135.0,
    "back": 180.0,
    "back_left_34": 225.0,
    "left": 270.0,
    "profile_left": 270.0,
    "front_left_34": 315.0,
}


@dataclass(frozen=True)
class ReferenceViewSelection:
    item: ReferenceItem | None
    view: str
    angular_error_deg: float
    fallback: bool = False


def _distance(left: float, right: float) -> float:
    return abs((left - right + 180.0) % 360.0 - 180.0)


def select_reference_view(
    camera: CameraSpec,
    *,
    character_facing_deg: float | None,
    references: Iterable[ReferenceItem],
) -> ReferenceViewSelection:
    """Pick the closest available identity/look reference by camera delta.

    ``camera.azimuth_deg`` is the camera position and ``character_facing_deg``
    is the character's forward direction.  The difference is the view angle
    seen by the camera.  Ties are resolved lexicographically for replayability.
    """

    candidates = [
        item
        for item in references
        if item.role in {ReferenceRole.CHARACTER_IDENTITY, ReferenceRole.CHARACTER_LOOK}
    ]
    if camera.azimuth_deg is None or character_facing_deg is None:
        item = next(
            (item for item in candidates if str(item.metadata.get("view", "front")) == "front"),
            candidates[0] if candidates else None,
        )
        return ReferenceViewSelection(item=item, view="front", angular_error_deg=0.0, fallback=True)

    target = (camera.azimuth_deg - character_facing_deg) % 360.0
    scored: list[tuple[float, str, str, ReferenceItem]] = []
    for item in candidates:
        view = str(item.metadata.get("view") or "front")
        angle = float(item.metadata.get("azimuth_deg", _VIEW_ANGLES.get(view, 0.0))) % 360.0
        scored.append((_distance(angle, target), view, item.id, item))
    if not scored:
        return ReferenceViewSelection(item=None, view="front", angular_error_deg=0.0, fallback=True)
    error, view, _item_id, item = min(scored)
    return ReferenceViewSelection(item=item, view=view, angular_error_deg=error)


def select_views_for_characters(
    camera: CameraSpec,
    *,
    facing_by_character: Mapping[str, float | None],
    references_by_character: Mapping[str, Iterable[ReferenceItem]],
) -> dict[str, ReferenceViewSelection]:
    return {
        character_id: select_reference_view(
            camera,
            character_facing_deg=facing_by_character.get(character_id),
            references=references_by_character.get(character_id, ()),
        )
        for character_id in sorted(references_by_character)
    }


__all__ = ["ReferenceViewSelection", "select_reference_view", "select_views_for_characters"]
