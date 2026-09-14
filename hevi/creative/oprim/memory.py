"""Project-isolated, rebuildable lexical creative memory index."""

from __future__ import annotations

import re
from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class MemoryRecord:
    project_id: UUID
    record_id: str
    kind: str
    text: str
    source_ref: str
    credential: bool = False


@dataclass(frozen=True)
class MemoryHit:
    record: MemoryRecord
    score: float


class CreativeMemoryIndex:
    """In-memory projection; callers may persist/rebuild records externally."""

    def __init__(self) -> None:
        self._records: dict[tuple[UUID, str], MemoryRecord] = {}

    def add(self, record: MemoryRecord) -> None:
        if record.credential:
            raise ValueError("CREDENTIAL_INDEXING_FORBIDDEN")
        self._records[(record.project_id, record.record_id)] = record

    def remove_project(self, project_id: UUID) -> None:
        for key in tuple(key for key in self._records if key[0] == project_id):
            del self._records[key]

    def rebuild(self, records: tuple[MemoryRecord, ...]) -> None:
        self._records.clear()
        for record in records:
            self.add(record)

    def recall(self, *, project_id: UUID, query: str, limit: int = 5) -> tuple[MemoryHit, ...]:
        if limit < 1:
            raise ValueError("limit must be positive")
        query_tokens = set(self._tokens(query))
        hits: list[MemoryHit] = []
        for record in self._records.values():
            if record.project_id != project_id:
                continue
            tokens = set(self._tokens(record.text))
            score = len(query_tokens & tokens) / max(1, len(query_tokens | tokens))
            if score > 0:
                hits.append(MemoryHit(record, score))
        return tuple(sorted(hits, key=lambda hit: (-hit.score, hit.record.record_id))[:limit])

    @staticmethod
    def _tokens(text: str) -> tuple[str, ...]:
        return tuple(re.findall(r"[\w\u4e00-\u9fff]+", text.casefold()))


__all__ = ["CreativeMemoryIndex", "MemoryHit", "MemoryRecord"]
