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

_VIEW_ALIASES = {
    "front-left 3/4": "front_left_34",
    "front right 3/4": "front_right_34",
    "back-left 3/4": "back_left_34",
    "back right 3/4": "back_right_34",
    "left profile": "left",
    "right profile": "right",
    "front-left": "front_left_34",
    "front-right": "front_right_34",
    "back-left": "back_left_34",
    "back-right": "back_right_34",
}


def _normalise_view(value: object) -> str:
    raw = str(value or "front").strip().lower().replace("–", "-")
    return _VIEW_ALIASES.get(raw, raw.replace("-", "_").replace(" ", "_"))


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
            (item for item in candidates if _normalise_view(item.metadata.get("view")) == "front"),
            candidates[0] if candidates else None,
        )
        return ReferenceViewSelection(item=item, view="front", angular_error_deg=0.0, fallback=True)

    target = (camera.azimuth_deg - character_facing_deg) % 360.0
    scored: list[tuple[float, str, str, ReferenceItem]] = []
    for item in candidates:
        view = _normalise_view(item.metadata.get("view"))
        angle = float(item.metadata.get("azimuth_deg", _VIEW_ANGLES.get(view, 0.0))) % 360.0
        scored.append((_distance(angle, target), view, item.id, item))
    if not scored:
        return ReferenceViewSelection(item=None, view="front", angular_error_deg=0.0, fallback=True)
    error, view, _item_id, item = min(scored)
    return ReferenceViewSelection(
        item=item, view=view, angular_error_deg=error, fallback=error > 0.0
    )


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
