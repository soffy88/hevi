from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from obase.persistence import PgPool, insert_one, query, update_one


class PresenterRepository:
    def __init__(self, pool: PgPool) -> None:
        self.pool = pool

    async def create(self, data: dict[str, Any]) -> dict[str, Any]:
        data.setdefault("id", uuid.uuid4())
        now = datetime.now(UTC).replace(tzinfo=None)
        data.setdefault("created_at", now)
        data.setdefault("updated_at", now)
        data.setdefault("delivery_json", {})
        presenter_id = await insert_one(self.pool, table="presenters", data=data, returning="id")
        return await self.get(str(presenter_id)) or {}

    async def get(self, presenter_id: str, user_id: str) -> dict[str, Any] | None:
        rows = await query(
            self.pool,
            sql="SELECT * FROM presenters WHERE id = $1 AND user_id = $2",
            params=[uuid.UUID(presenter_id), user_id],
        )
        return rows[0] if rows else None

    async def list(self, user_id: str) -> list[dict[str, Any]]:
        return await query(
            self.pool,
            sql="SELECT * FROM presenters WHERE user_id = $1 ORDER BY created_at DESC",
            params=[user_id],
        )

    async def update(
        self, presenter_id: str, user_id: str, data: dict[str, Any]
    ) -> dict[str, Any] | None:
        data["updated_at"] = datetime.now(UTC).replace(tzinfo=None)
        row = await self.get(presenter_id, user_id)
        if row is None:
            return None
        await update_one(self.pool, table="presenters", id=uuid.UUID(presenter_id), data=data)
        return await self.get(presenter_id, user_id)
