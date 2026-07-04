from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from obase.persistence import PgPool, insert_one, query, read_one, update_one


class SeriesRepository:
    def __init__(self, pool: PgPool) -> None:
        self.pool = pool

    async def create(self, data: dict[str, Any]) -> dict[str, Any]:
        data.setdefault("id", uuid.uuid4())
        now = datetime.now(UTC).replace(tzinfo=None)
        data.setdefault("created_at", now)
        data.setdefault("updated_at", now)
        new_id = await insert_one(self.pool, table="series", data=data)
        return (await self.get(str(new_id))) or data

    async def get(self, series_id: str) -> dict[str, Any] | None:
        result: dict[str, Any] | None = await read_one(
            self.pool, table="series", id=uuid.UUID(series_id)
        )
        if result is not None and result.get("deleted_at") is not None:
            return None
        return result

    async def update(self, series_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
        updates["updated_at"] = datetime.now(UTC).replace(tzinfo=None)
        await update_one(self.pool, table="series", id=uuid.UUID(series_id), data=updates)
        return await self.get(series_id)

    async def list_series(self, *, user_id: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM series WHERE deleted_at IS NULL"
        params: list[Any] = []
        if user_id:
            sql += " AND user_id = $1"
            params.append(user_id)
        sql += " ORDER BY created_at DESC"
        return await query(self.pool, sql=sql, params=params or None)

    async def episodes(self, series_id: str) -> list[dict[str, Any]]:
        return await query(
            self.pool,
            sql="SELECT * FROM video_tasks WHERE series_id = $1 ORDER BY episode_index ASC",
            params=[uuid.UUID(series_id)],
        )
