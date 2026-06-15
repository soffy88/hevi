from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from obase.persistence import PgPool, insert_one, query, update_one


class OrderRepository:
    def __init__(self, pool: PgPool) -> None:
        self._pool = pool

    async def create_order(self, data: dict[str, Any]) -> dict[str, Any]:
        if "id" not in data:
            data["id"] = uuid.uuid4()
        now = datetime.utcnow()
        data.setdefault("created_at", now)
        data.setdefault("updated_at", now)
        data.setdefault("status", "pending")
        
        order_id = await insert_one(self._pool, table="orders", data=data, returning="id")
        return await self.get_order(str(order_id)) or {}

    async def get_order(self, order_id: str, user_id: str | None = None) -> dict[str, Any] | None:
        conditions = ["id = $1"]
        params: list[Any] = [uuid.UUID(order_id)]
        
        if user_id is not None:
            conditions.append("user_id = $2")
            params.append(uuid.UUID(user_id))
            
        where = " AND ".join(conditions)
        sql = f"SELECT * FROM orders WHERE {where}"
        rows = await query(self._pool, sql=sql, params=params)
        return rows[0] if rows else None

    async def update_order(self, order_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
        updates["updated_at"] = datetime.utcnow()
        await update_one(
            self._pool, table="orders", id=uuid.UUID(order_id), data=updates
        )
        return await self.get_order(order_id)

    async def list_user_orders(self, user_id: str, limit: int = 20) -> list[dict[str, Any]]:
        sql = "SELECT * FROM orders WHERE user_id = $1 ORDER BY created_at DESC"
        return await query(
            self._pool, 
            sql=sql, 
            params=[uuid.UUID(user_id)],
            limit=limit
        )

    async def get_order_by_event_id(self, event_id: str) -> dict[str, Any] | None:
        """Find order by Paddle event ID (for idempotency)."""
        sql = "SELECT * FROM orders WHERE paddle_event_id = $1"
        rows = await query(self._pool, sql=sql, params=[event_id])
        return rows[0] if rows else None
    
    async def is_event_processed(self, event_id: str) -> bool:
        """Check if a webhook event has already been processed."""
        sql = "SELECT 1 FROM orders WHERE paddle_event_id = $1"
        rows = await query(self._pool, sql=sql, params=[event_id])
        return len(rows) > 0
