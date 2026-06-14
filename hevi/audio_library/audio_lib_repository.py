from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from obase.persistence import PgPool, insert_one, query, soft_delete_one


class AudioLibraryRepository:
    def __init__(self, pool: PgPool) -> None:
        self._pool = pool

    async def create(self, data: dict[str, Any]) -> dict[str, Any]:
        if "id" not in data:
            data["id"] = uuid.uuid4()
        now = datetime.utcnow()
        data.setdefault("created_at", now)
        data.setdefault("updated_at", now)
        data.setdefault("is_official", False)
        
        asset_id = await insert_one(
            self._pool, table="audio_assets", data=data, returning="id"
        )
        return await self.get(str(asset_id)) or {}

    async def get(self, asset_id: str) -> dict[str, Any] | None:
        rows = await query(
            self._pool,
            sql="SELECT * FROM audio_assets WHERE id = $1 AND deleted_at IS NULL",
            params=[uuid.UUID(asset_id)]
        )
        return rows[0] if rows else None

    async def delete(self, asset_id: str) -> bool:
        return await soft_delete_one(
            self._pool, table="audio_assets", id=uuid.UUID(asset_id)
        )

    async def search(
        self,
        *,
        asset_type: str | None = None,
        mood: str | None = None,
        tags: list[str] | None = None,
        query_text: str | None = None,
        user_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        conditions = ["deleted_at IS NULL"]
        params: list[Any] = []
        idx = 1

        # Multi-tenancy: Official + user's own
        if user_id:
            conditions.append(f"(is_official = TRUE OR user_id = ${idx})")
            params.append(user_id)
            idx += 1
        else:
            conditions.append("is_official = TRUE")

        if asset_type:
            conditions.append(f"asset_type = ${idx}")
            params.append(asset_type)
            idx += 1

        if mood:
            conditions.append(f"mood = ${idx}")
            params.append(mood)
            idx += 1

        if tags:
            # JSONB contains all tags. Pass tags directly as list.
            conditions.append(f"tags @> ${idx}")
            params.append(tags)
            idx += 1

        if query_text:
            conditions.append(f"name ILIKE ${idx}")
            params.append(f"%{query_text}%")
            idx += 1

        where = " AND ".join(conditions)
        sql = f"SELECT * FROM audio_assets WHERE {where} ORDER BY created_at DESC"
        
        rows: list[dict[str, Any]] = await query(
            self._pool,
            sql=sql,
            params=params if params else None,
            limit=limit,
        )
        return rows
