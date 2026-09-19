"""Creative agent memory (Gap Closure W9: Q01, Q02).

The HEVI creative runtime remembers across sessions through the real
HEVI memory authority (:class:`hevi.memory.store.MemoryStore`, SQLite,
WAL) — not Veya standalone memory, which is a produce contract and is
never claimed as memory here. Two scopes:

- USER_MEMORY: creator-level preferences (visual style, narration style,
  pacing, naming, subtitle, provider bias) — all projects.
- PROJECT_CONVENTION: per-project confirmed practices and corrections.

Precedence is explicit and tested: an explicit current instruction beats
a project convention, which beats a general user preference. Disabled
entries are ignored, never deleted silently. PII and secrets never enter
memory: writes carrying them refuse with stable codes.

Storage is append-only rows over the shared store (latest row per
(scope, key) wins), namespaced so user and project rows never collide.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from hevi.memory.store import MemoryStore

USER_SCOPE = "user"
PROJECT_SCOPE_PREFIX = "project:"

_SECRET_RE = re.compile(
    r"sk-[A-Za-z0-9]{8,}|api[_-]?key\s*[:=]|authorization\s*:|bearer\s+[A-Za-z0-9]",
    re.IGNORECASE,
)
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"(?<!\d)(1\d{10}|\d{3,4}[- ]\d{7,8}|\d{7,11})(?!\d)")
_ID_RE = re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")


class MemoryError(ValueError):
    """Refusal with a stable machine code."""


class MemorySource(StrEnum):
    INSTRUCTION = "instruction"
    PROJECT_CONVENTION = "convention"
    USER_PREFERENCE = "preference"


class MemoryEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    entry_key: str = Field(min_length=1)
    scope: str = Field(min_length=1)
    project_id: str = ""
    content: str = ""
    disabled: bool = False
    session_id: str = ""
    stored_at: str = ""


class ResolvedMemory(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    entry_key: str
    content: str
    source: MemorySource
    scope: str


def _namespaced_key(scope: str, project_id: str, key: str, owner_id: str = "") -> str:
    """Owner-first namespace (D5-A): memory is private to its owner.

    ``owner`` is server-derived; it is never accepted from a client body.
    """
    owner = str(owner_id or "").strip() or "shared"
    if scope == USER_SCOPE:
        return f"owner:{owner}:user-pref:{key}"
    return f"owner:{owner}:project:{project_id}:convention:{key}"


def _scope_of(namespaced: str) -> tuple[str, str, str]:
    """Parse back (owner_id, scope, project_id) from a namespaced key."""
    if not namespaced.startswith("owner:"):
        return "", "unknown", ""
    rest = namespaced[len("owner:") :]
    owner, _, remainder = rest.partition(":")
    if remainder.startswith("user-pref:"):
        return owner, USER_SCOPE, ""
    if remainder.startswith(PROJECT_SCOPE_PREFIX):
        after = remainder[len(PROJECT_SCOPE_PREFIX) :]
        project_id, _, _ = after.partition(":convention:")
        return owner, f"{PROJECT_SCOPE_PREFIX}{project_id}", project_id
    return owner, "unknown", ""


def check_memory_safety(content: str) -> None:
    """PII/secret gate: forbidden content refuses before any write."""

    if _SECRET_RE.search(content):
        raise MemoryError("MEMORY_SECRET_REFUSED")
    if _EMAIL_RE.search(content) or _ID_RE.search(content) or _PHONE_RE.search(content):
        raise MemoryError("MEMORY_PII_REFUSED")


class CreativeMemory:
    """Scoped creative memory over the shared HEVI MemoryStore authority."""

    KIND = "semantic"

    def __init__(self, store: MemoryStore) -> None:
        self._store = store

    @classmethod
    def at_path(cls, db_path: Path | str) -> CreativeMemory:
        return cls(MemoryStore(Path(db_path)))

    def remember(
        self,
        *,
        scope: str,
        key: str,
        content: str,
        project_id: str = "",
        session_id: str = "",
        owner_id: str = "",
    ) -> MemoryEntry:
        """Store one scoped memory. Secrets/PII refuse; never stored redacted.

        ``owner_id`` must be the server-derived owner; it is never taken from
        a client request body.
        """

        if scope != USER_SCOPE and not scope.startswith(PROJECT_SCOPE_PREFIX):
            raise MemoryError(f"MEMORY_SCOPE_UNKNOWN:{scope}")
        if scope.startswith(PROJECT_SCOPE_PREFIX) and not project_id:
            raise MemoryError("MEMORY_PROJECT_SCOPE_NEEDS_PROJECT_ID")
        if not key.strip():
            raise MemoryError("MEMORY_KEY_EMPTY")
        if not content.strip():
            raise MemoryError("MEMORY_CONTENT_EMPTY")
        check_memory_safety(content)
        namespaced = _namespaced_key(scope, project_id, key.strip(), owner_id)
        payload: dict[str, Any] = {
            "content": content,
            "scope": scope,
            "project_id": project_id,
            "owner_id": owner_id,
            "disabled": False,
            "session_id": session_id,
            "stored_at": datetime.now(UTC).isoformat(),
        }
        self._store.remember(self.KIND, namespaced, payload)
        return MemoryEntry(
            entry_key=key.strip(),
            scope=scope,
            project_id=project_id,
            content=content,
            session_id=session_id,
            stored_at=payload["stored_at"],
        )

    def edit(
        self,
        *,
        scope: str,
        key: str,
        content: str,
        project_id: str = "",
        session_id: str = "",
        owner_id: str = "",
    ) -> MemoryEntry:
        """Edit = append a newer row; latest row per (scope, key) wins."""

        return self.remember(
            scope=scope,
            key=key,
            content=content,
            project_id=project_id,
            session_id=session_id,
            owner_id=owner_id,
        )

    def disable(self, *, scope: str, key: str, project_id: str = "", owner_id: str = "") -> None:
        """Disable/ignore: tombstone row; history preserved, recall skips."""

        namespaced = _namespaced_key(scope, project_id, key.strip(), owner_id)
        self._store.remember(
            self.KIND,
            namespaced,
            {
                "content": "",
                "scope": scope,
                "project_id": project_id,
                "owner_id": owner_id,
                "disabled": True,
                "session_id": "",
                "stored_at": datetime.now(UTC).isoformat(),
            },
        )

    def _latest(self, owner_id: str = "") -> dict[tuple[str, str, str], dict[str, Any]]:
        owner = str(owner_id or "").strip() or "shared"
        latest: dict[tuple[str, str, str], dict[str, Any]] = {}
        for hit in self._store.recent(self.KIND, limit=1000):
            entry_owner, scope, project_id = _scope_of(hit.key)
            if scope == "unknown" or entry_owner != owner:
                continue
            entry_key = hit.key.split(":")[-1]
            marker = (scope, entry_key, project_id)
            if marker not in latest:
                latest[marker] = {**dict(hit.payload), "_key": entry_key}
        return latest

    def inspect(
        self,
        *,
        scope: str,
        project_id: str = "",
        include_disabled: bool = False,
        owner_id: str = "",
    ) -> tuple[MemoryEntry, ...]:
        """MEMORY_INSPECTION: creators can list what the agent remembers.

        Only the caller's own owner namespace is ever returned.
        """

        entries: list[MemoryEntry] = []
        for (entry_scope, entry_key, entry_project), payload in sorted(
            self._latest(owner_id).items()
        ):
            if entry_scope != scope:
                continue
            if scope.startswith(PROJECT_SCOPE_PREFIX) and entry_project != project_id:
                continue
            if payload.get("disabled") and not include_disabled:
                continue
            entries.append(
                MemoryEntry(
                    entry_key=entry_key,
                    scope=entry_scope,
                    project_id=entry_project,
                    content=str(payload.get("content", "")),
                    disabled=bool(payload.get("disabled", False)),
                    session_id=str(payload.get("session_id", "")),
                    stored_at=str(payload.get("stored_at", "")),
                )
            )
        return tuple(entries)

    def recall_for_project(
        self, project_id: str, query: str, *, k: int = 5, owner_id: str = ""
    ) -> tuple[MemoryEntry, ...]:
        """Cross-session recall: user prefs + this project's conventions.

        Scoped to the caller's owner namespace only.
        """

        owner = str(owner_id or "").strip() or "shared"
        hits = self._store.recall(query, k=max(k * 4, 10), kinds=(self.KIND,))
        seen: set[tuple[str, str, str]] = set()
        entries: list[MemoryEntry] = []
        for hit in hits:
            entry_owner, scope, hit_project = _scope_of(hit.key)
            if scope == "unknown" or entry_owner != owner:
                continue
            if scope.startswith(PROJECT_SCOPE_PREFIX) and hit_project != project_id:
                continue
            payload = dict(hit.payload)
            if payload.get("disabled"):
                continue
            entry_key = hit.key.split(":")[-1]
            marker = (scope, entry_key, hit_project)
            if marker in seen:
                continue
            seen.add(marker)
            entries.append(
                MemoryEntry(
                    entry_key=entry_key,
                    scope=scope,
                    project_id=hit_project,
                    content=str(payload.get("content", "")),
                    session_id=str(payload.get("session_id", "")),
                    stored_at=str(payload.get("stored_at", "")),
                )
            )
            if len(entries) >= k:
                break
        return tuple(entries)

    def resolve(
        self, project_id: str, *, instruction: str = "", owner_id: str = ""
    ) -> tuple[ResolvedMemory, ...]:
        """Precedence: explicit instruction > project convention > user preference.

        Same entry_key at a higher precedence shadows the lower one; the
        shadowed row stays stored and inspectable. Owner-scoped.
        """

        latest = self._latest(owner_id)
        by_key: dict[str, MemoryEntry] = {}
        for scope in (USER_SCOPE, f"{PROJECT_SCOPE_PREFIX}{project_id}"):
            for (entry_scope, entry_key, entry_project), payload in latest.items():
                if entry_scope != scope or payload.get("disabled"):
                    continue
                if scope.startswith(PROJECT_SCOPE_PREFIX) and entry_project != project_id:
                    continue
                by_key[entry_key] = MemoryEntry(
                    entry_key=entry_key,
                    scope=entry_scope,
                    project_id=entry_project,
                    content=str(payload.get("content", "")),
                    session_id=str(payload.get("session_id", "")),
                    stored_at=str(payload.get("stored_at", "")),
                )
        resolved = [
            ResolvedMemory(
                entry_key=key,
                content=entry.content,
                source=MemorySource.PROJECT_CONVENTION
                if entry.scope.startswith(PROJECT_SCOPE_PREFIX)
                else MemorySource.USER_PREFERENCE,
                scope=entry.scope,
            )
            for key, entry in sorted(by_key.items())
        ]
        if instruction:
            resolved.append(
                ResolvedMemory(
                    entry_key="__instruction__",
                    content=instruction,
                    source=MemorySource.INSTRUCTION,
                    scope="instruction",
                )
            )
        return tuple(resolved)


__all__ = [
    "CreativeMemory",
    "MemoryEntry",
    "MemoryError",
    "MemorySource",
    "ResolvedMemory",
    "check_memory_safety",
]
