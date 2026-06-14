from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from obase.persistence import PgPool, insert_one, query, read_one, update_one

SUBJECT_KINDS: frozenset[str] = frozenset({"character", "portrait", "product", "scene"})


class SubjectRepository:
    def __init__(self, pool: PgPool) -> None:
        self._pool = pool

    async def create(self, data: dict[str, Any]) -> dict[str, Any]:
        if "id" not in data:
            data["id"] = uuid.uuid4()
        now = datetime.utcnow()
        data.setdefault("created_at", now)
        data.setdefault("updated_at", now)
        data.setdefault("deleted_at", None)
        data.setdefault("version", 1)
        result: dict[str, Any] = await insert_one(self._pool, table="subjects", data=data)
        return result

    async def get(self, subject_id: str) -> dict[str, Any] | None:
        result: dict[str, Any] | None = await read_one(
            self._pool, table="subjects", id=uuid.UUID(subject_id)
        )
        if result is not None and result.get("deleted_at") is not None:
            return None
        return result

    async def update(
        self, subject_id: str, updates: dict[str, Any]
    ) -> dict[str, Any] | None:
        existing = await self.get(subject_id)
        if existing is None:
            return None
        updates["updated_at"] = datetime.utcnow()
        updates["version"] = existing.get("version", 1) + 1
        await update_one(
            self._pool,
            table="subjects",
            id=uuid.UUID(subject_id),
            data=updates,
        )
        return await self.get(subject_id)

    async def soft_delete(self, subject_id: str) -> bool:
        existing = await self.get(subject_id)
        if existing is None:
            return False
        success: bool = await update_one(
            self._pool,
            table="subjects",
            id=uuid.UUID(subject_id),
            data={"deleted_at": datetime.utcnow()},
        )
        return bool(success)

    async def list_subjects(
        self,
        *,
        kind: str | None = None,
        query_text: str | None = None,
        user_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        conditions = ["deleted_at IS NULL"]
        params: list[Any] = []
        idx = 1

        if kind is not None:
            conditions.append(f"subject_type = ${idx}")
            params.append(kind)
            idx += 1

        if user_id is not None:
            conditions.append(f"user_id = ${idx}")
            params.append(user_id)
            idx += 1

        if query_text is not None:
            conditions.append(f"(name ILIKE ${idx} OR description ILIKE ${idx})")
            params.append(f"%{query_text}%")
            idx += 1

        where = " AND ".join(conditions)
        sql = f"SELECT * FROM subjects WHERE {where} ORDER BY created_at DESC"
        rows: list[dict[str, Any]] = await query(
            self._pool,
            sql=sql,
            params=params if params else None,
            limit=limit,
        )
        return rows
