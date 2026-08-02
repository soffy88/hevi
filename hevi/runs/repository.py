from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from obase.persistence import PgPool, insert_one, query, read_one, update_one


class AutomationRunRepository:
    """Repository for adapter sessions, intentionally separate from video tasks."""

    def __init__(self, pool: PgPool) -> None:
        self.pool = pool

    async def create(self, data: dict[str, Any]) -> dict[str, Any]:
        data.setdefault("id", uuid.uuid4())
        now = datetime.now(UTC).replace(tzinfo=None)
        data.setdefault("created_at", now)
        data.setdefault("updated_at", now)
        data.setdefault("input_json", {})
        data.setdefault("state_json", {})
        data.setdefault("task_ids", [])
        run_id = await insert_one(self.pool, table="automation_runs", data=data, returning="id")
        return await self.get(str(run_id)) or {}

    async def get(self, run_id: str) -> dict[str, Any] | None:
        return await read_one(self.pool, table="automation_runs", id=uuid.UUID(run_id))

    async def list_for_user(self, *, kind: str, user_id: str) -> list[dict[str, Any]]:
        return await query(
            self.pool,
            sql=(
                "SELECT * FROM automation_runs WHERE kind = $1 AND user_id = $2 "
                "ORDER BY created_at DESC"
            ),
            params=[kind, user_id],
        )

    async def update(self, run_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
        data["updated_at"] = datetime.now(UTC).replace(tzinfo=None)
        await update_one(self.pool, table="automation_runs", id=uuid.UUID(run_id), data=data)
        return await self.get(run_id)
