from __future__ import annotations

import uuid
from typing import Any

from obase.persistence import PgPool, insert_one, query, read_one


class UserRepository:
    def __init__(self, pool: PgPool) -> None:
        self._pool = pool

    async def create(self, data: dict[str, Any]) -> dict[str, Any]:
        if "id" not in data:
            data["id"] = uuid.uuid4()
        from datetime import UTC, datetime
        now = datetime.now(UTC).replace(tzinfo=None)
        data.setdefault("created_at", now)
        data.setdefault("updated_at", now)
        
        user_id = await insert_one(
            self._pool, table="users", data=data, returning="id"
        )
        return await self.get(str(user_id)) or {}

    async def get(self, user_id: str) -> dict[str, Any] | None:
        return await read_one(
            self._pool, table="users", id=uuid.UUID(user_id)
        )

    async def get_by_email(self, email: str) -> dict[str, Any] | None:
        rows = await query(
            self._pool,
            sql="SELECT * FROM users WHERE email = $1 AND is_active = TRUE",
            params=[email]
        )
        return rows[0] if rows else None

    async def get_by_oauth(self, provider: str, sub: str) -> dict[str, Any] | None:
        sql = (
            "SELECT * FROM users "
            "WHERE auth_provider = $1 AND oauth_sub = $2 AND is_active = TRUE"
        )
        rows = await query(
            self._pool,
            sql=sql,
            params=[provider, sub]
        )
        return rows[0] if rows else None
