from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from obase.persistence import PgPool, insert_one, query, read_one, update_one


class GraphRepository:
    def __init__(self, pool: PgPool) -> None:
        self._pool = pool

    async def create(self, data: dict[str, Any]) -> dict[str, Any]:
        if "id" not in data:
            data["id"] = uuid.uuid4()
        now = datetime.utcnow()
        data.setdefault("created_at", now)
        data.setdefault("updated_at", now)
        result: dict[str, Any] = await insert_one(self._pool, table="canvas_graphs", data=data)
        return result

    async def get(self, graph_id: str) -> dict[str, Any] | None:
        result: dict[str, Any] | None = await read_one(
            self._pool, table="canvas_graphs", id=uuid.UUID(graph_id)
        )
        return result

    async def update(self, graph_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
        existing = await self.get(graph_id)
        if existing is None:
            return None
        updates["updated_at"] = datetime.utcnow()
        await update_one(
            self._pool, table="canvas_graphs", id=uuid.UUID(graph_id), data=updates
        )
        return await self.get(graph_id)

    async def delete(self, graph_id: str) -> bool:
        existing = await self.get(graph_id)
        if existing is None:
            return False
        success: bool = await update_one(
            self._pool,
            table="canvas_graphs",
            id=uuid.UUID(graph_id),
            data={"deleted_at": datetime.utcnow()},
        )
        return bool(success)

    async def list_graphs(
        self, *, user_id: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        conditions = ["deleted_at IS NULL"]
        params: list[Any] = []
        if user_id is not None:
            conditions.append(f"user_id = ${len(params) + 1}")
            params.append(user_id)
        where = " AND ".join(conditions)
        sql = f"SELECT * FROM canvas_graphs WHERE {where} ORDER BY created_at DESC"
        rows: list[dict[str, Any]] = await query(
            self._pool,
            sql=sql,
            params=params if params else None,
            limit=limit,
        )
        return rows
