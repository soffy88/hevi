"""Bounded, optimistic-concurrency narrative revision contract."""

from __future__ import annotations

from dataclasses import dataclass

from hevi.narrative.models import NarrativeRevision


class StaleRevisionError(ValueError):
    """A revision attempted to overwrite a newer canonical asset."""


@dataclass(frozen=True)
class RevisionStore:
    revisions: dict[str, str]

    def __init__(self) -> None:
        object.__setattr__(self, "revisions", {})

    def read(self, asset_id: str) -> str | None:
        return self.revisions.get(asset_id)

    def commit(self, revision: NarrativeRevision) -> str:
        current = self.read(revision.asset_id)
        if current != revision.base_revision:
            raise StaleRevisionError(f"STALE_REVISION:{revision.asset_id}")
        self.revisions[revision.asset_id] = revision.new_revision
        return revision.new_revision
