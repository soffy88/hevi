"""InMemory formal repository implementations for hevi operations bridge (offline / unit tests).
Shared across GraphRepository, TaskRepository, and SubjectRepository per F2 requirements.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any


class InMemoryStore:
    def __init__(self) -> None:
        self.graphs: dict[str, dict[str, Any]] = {}
        self.tasks: dict[str, dict[str, Any]] = {}
        self.subjects: dict[str, dict[str, Any]] = {}
        self.proposals: dict[str, dict[str, Any]] = {}


_GLOBAL_STORE = InMemoryStore()


class InMemoryGraphRepository:
    def __init__(self, store: InMemoryStore | None = None) -> None:
        self._store = store or _GLOBAL_STORE

    async def get(self, graph_id: str) -> dict[str, Any] | None:
        g = self._store.graphs.get(str(graph_id))
        return dict(g) if g else None

    async def create(self, data: dict[str, Any]) -> dict[str, Any]:
        gid = str(data.get("id") or uuid.uuid4())
        data["id"] = uuid.UUID(gid) if isinstance(data.get("id"), str) else data.get("id", uuid.uuid4())
        data.setdefault("revision", 0)
        data.setdefault("nodes", [])
        data.setdefault("edges", [])
        now = datetime.now(UTC).replace(tzinfo=None)
        data.setdefault("created_at", now)
        data.setdefault("updated_at", now)
        self._store.graphs[gid] = data
        return dict(data)

    async def update(self, graph_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
        g = self._store.graphs.get(str(graph_id))
        if not g:
            return None
        g.update(updates)
        g["updated_at"] = datetime.now(UTC).replace(tzinfo=None)
        return dict(g)

    async def list_graphs(self, *, user_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        return [dict(g) for g in self._store.graphs.values() if not g.get("deleted_at")][:limit]


class InMemoryTaskRepository:
    def __init__(self, store: InMemoryStore | None = None) -> None:
        self._store = store or _GLOBAL_STORE

    async def get_task(self, task_id: uuid.UUID | str) -> dict[str, Any] | None:
        t = self._store.tasks.get(str(task_id))
        return dict(t) if t else None

    async def create_task(self, data: dict[str, Any]) -> dict[str, Any]:
        tid = str(data.get("id") or uuid.uuid4())
        data["id"] = uuid.UUID(tid) if isinstance(data.get("id"), str) else data.get("id", uuid.uuid4())
        now = datetime.now(UTC).replace(tzinfo=None)
        data.setdefault("created_at", now)
        data.setdefault("updated_at", now)
        data.setdefault("status", "submitted")
        self._store.tasks[tid] = data
        return dict(data)

    async def list_tasks(self, limit: int = 100, user_id: str | None = None, statuses: list[str] | None = None) -> list[dict[str, Any]]:
        return [dict(t) for t in self._store.tasks.values()][:limit]


class InMemorySubjectRepository:
    def __init__(self, store: InMemoryStore | None = None) -> None:
        self._store = store or _GLOBAL_STORE

    async def get(self, subject_id: str) -> dict[str, Any] | None:
        s = self._store.subjects.get(str(subject_id))
        return dict(s) if s else None

    async def create(self, data: dict[str, Any]) -> dict[str, Any]:
        sid = str(data.get("id") or uuid.uuid4())
        data["id"] = uuid.UUID(sid) if isinstance(data.get("id"), str) else data.get("id", uuid.UUID(sid))
        now = datetime.now(UTC).replace(tzinfo=None)
        data.setdefault("created_at", now)
        data.setdefault("updated_at", now)
        data.setdefault("version", 1)
        self._store.subjects[sid] = data
        return dict(data)

    async def list_subjects(self, *, kind: str | None = None, query_text: str | None = None, user_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        items = [dict(s) for s in self._store.subjects.values() if not s.get("deleted_at")]
        if kind:
            items = [i for i in items if i.get("subject_type") == kind]
        return items[:limit]
