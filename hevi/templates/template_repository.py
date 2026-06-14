from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from obase.persistence import PgPool, insert_one, query, soft_delete_one, update_one


class TemplateRepository:
    def __init__(self, pool: PgPool) -> None:
        self._pool = pool

    async def create(self, data: dict[str, Any]) -> dict[str, Any]:
        if "id" not in data:
            data["id"] = uuid.uuid4()
        now = datetime.utcnow()
        data.setdefault("created_at", now)
        data.setdefault("updated_at", now)
        data.setdefault("is_official", False)
        data.setdefault("version", 1)
        
        template_id = await insert_one(
            self._pool, table="templates", data=data, returning="id"
        )
        return await self.get(str(template_id)) or {}

    async def get(self, template_id: str) -> dict[str, Any] | None:
        # We manually query to ensure deleted_at IS NULL
        rows = await query(
            self._pool, 
            sql="SELECT * FROM templates WHERE id = $1 AND deleted_at IS NULL", 
            params=[uuid.UUID(template_id)]
        )
        return rows[0] if rows else None

    async def update(
        self, template_id: str, updates: dict[str, Any]
    ) -> dict[str, Any] | None:
        updates["updated_at"] = datetime.utcnow()
        await update_one(
            self._pool,
            table="templates",
            id=uuid.UUID(template_id),
            data=updates,
        )
        return await self.get(template_id)

    async def delete(self, template_id: str) -> bool:
        return await soft_delete_one(
            self._pool, table="templates", id=uuid.UUID(template_id)
        )

    async def list_templates(
        self,
        *,
        category: str | None = None,
        official_only: bool = False,
        user_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        conditions = ["deleted_at IS NULL"]
        params: list[Any] = []
        idx = 1

        if official_only:
            conditions.append(f"is_official = ${idx}")
            params.append(True)
            idx += 1
        elif user_id is not None:
            conditions.append(f"(is_official = TRUE OR user_id = ${idx})")
            params.append(user_id)
            idx += 1
        else:
            conditions.append("is_official = TRUE")

        if category:
            conditions.append(f"category = ${idx}")
            params.append(category)
            idx += 1

        where = " AND ".join(conditions)
        sql = f"SELECT * FROM templates WHERE {where} ORDER BY created_at DESC"
        
        rows: list[dict[str, Any]] = await query(
            self._pool,
            sql=sql,
            params=params if params else None,
            limit=limit,
        )
        return rows
