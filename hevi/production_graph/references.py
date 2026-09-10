"""Typed, lock-aware reference bundles backed by existing artifacts."""

from __future__ import annotations

from hevi.production_graph.domain import ReferenceBundle, ReferenceItem


class ReferenceLockError(ValueError):
    """Raised when a locked reference bundle/item would be changed."""


def add_reference(bundle: ReferenceBundle, item: ReferenceItem) -> ReferenceBundle:
    if bundle.locked:
        raise ReferenceLockError(f"reference bundle {bundle.id} is locked")
    if item.locked and not (item.artifact_id or item.production_entity_id):
        raise ValueError("a locked reference must identify an artifact or production entity")
    if any(existing.id == item.id for existing in bundle.items):
        raise ValueError(f"reference item {item.id} already exists")
    return bundle.model_copy(update={"items": [*bundle.items, item]}, deep=True)


def lock_reference(bundle: ReferenceBundle) -> ReferenceBundle:
    return bundle.model_copy(
        update={"locked": True, "items": [item.model_copy(update={"locked": True}) for item in bundle.items]},
        deep=True,
    )


__all__ = ["ReferenceLockError", "add_reference", "lock_reference"]
