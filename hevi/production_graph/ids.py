"""Stable identifiers for canonical production objects.

Canonical IDs are UUID strings.  New objects use random UUIDs; imports from
legacy schemas use UUID5 so the same legacy identity maps to the same
canonical object on every retry.  The legacy ID is never used as a primary
key in the canonical store.
"""

from __future__ import annotations

from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

CanonicalId = str


def new_id() -> CanonicalId:
    """Allocate a new canonical identity."""

    return str(uuid4())


def stable_id(kind: str, legacy_id: str) -> CanonicalId:
    """Map a legacy identity to a deterministic canonical UUID."""

    kind = kind.strip()
    legacy_id = legacy_id.strip()
    if not kind or not legacy_id:
        raise ValueError("stable IDs require a non-empty kind and legacy_id")
    return str(uuid5(NAMESPACE_URL, f"hevi:production:{kind}:{legacy_id}"))


def canonical_id(kind: str, legacy_id: str | None = None) -> CanonicalId:
    """Return a deterministic imported ID or a fresh ID for new data."""

    return stable_id(kind, legacy_id) if legacy_id is not None else new_id()


def is_canonical_id(value: str) -> bool:
    """Return whether *value* is a UUID-shaped canonical ID."""

    try:
        UUID(value)
    except AttributeError, ValueError, TypeError:
        return False
    return True


__all__ = ["CanonicalId", "canonical_id", "is_canonical_id", "new_id", "stable_id"]
