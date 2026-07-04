import uuid
from datetime import UTC, datetime
from typing import Any

from obase.persistence import PgPool, insert_one, query, read_one, update_one


class TaskRepository:
    def __init__(self, pool: PgPool):
        self.pool = pool

    async def create_task(self, data: dict[str, Any]) -> dict[str, Any]:
        """Create a new video task."""
        # Ensure ID is present if not provided
        if "id" not in data:
            data["id"] = uuid.uuid4()
        task_id = await insert_one(self.pool, table="video_tasks", data=data, returning="id")
        return await self.get_task(task_id) or {}

    async def get_task(self, task_id: uuid.UUID) -> dict[str, Any] | None:
        """Retrieve a task by ID."""
        return await read_one(self.pool, table="video_tasks", id=task_id)

    async def update_task(self, task_id: uuid.UUID, data: dict[str, Any]) -> bool:
        """Update task data."""
        return await update_one(self.pool, table="video_tasks", id=task_id, data=data)

    async def list_tasks(
        self,
        limit: int = 100,
        user_id: str | None = None,
        statuses: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """List recent tasks, optionally filtered by user and/or status."""
        conditions: list[str] = []
        params: list[Any] = []

        if user_id:
            params.append(user_id)
            conditions.append(f"user_id = ${len(params)}")

        if statuses:
            placeholders = ", ".join(f"${len(params) + i + 1}" for i in range(len(statuses)))
            conditions.append(f"status IN ({placeholders})")
            params.extend(statuses)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        sql = f"SELECT * FROM video_tasks {where} ORDER BY created_at DESC"
        return await query(self.pool, sql=sql, params=params or None, limit=limit)

    async def create_shot_state(self, data: dict[str, Any]) -> dict[str, Any]:
        """Create a shot state entry."""
        if "id" not in data:
            data["id"] = uuid.uuid4()
        # created_at 是 NOT NULL 且无 server_default(ORM 默认不经 insert_one 生效);此前
        # 该方法零调用故未暴露。补默认,任何调用方无需操心。
        data.setdefault("created_at", datetime.now(UTC).replace(tzinfo=None))
        return await insert_one(self.pool, table="shot_states", data=data)  # type: ignore

    async def get_shots(self, task_id: uuid.UUID) -> list[dict[str, Any]]:
        """Retrieve all shots for a task."""
        return await query(
            self.pool,
            sql="SELECT * FROM shot_states WHERE task_id = $1 ORDER BY shot_index ASC",
            params=[task_id],
        )

    async def delete_shots(self, task_id: uuid.UUID) -> None:
        """删某 task 的所有 shot_states(C3 regenerate 前清旧,再落新)。"""
        async with self.pool.acquire() as conn:
            await conn.execute("DELETE FROM shot_states WHERE task_id = $1", task_id)

    async def get_next_queued_task(self) -> dict[str, Any] | None:
        """Get the oldest queued task (read-only peek; NOT a claim)."""
        results = await query(
            self.pool,
            sql=(
                "SELECT * FROM video_tasks WHERE status = 'queued'"
                " ORDER BY queued_at ASC, created_at ASC LIMIT 1"
            ),
        )
        return results[0] if results else None

    async def claim_next_queued_task(self) -> dict[str, Any] | None:
        """Atomically claim the oldest queued task (queued → claimed).

        FOR UPDATE SKIP LOCKED makes this safe for multiple concurrent workers /
        horizontally-scaled replicas: each gets a distinct task, no double-dequeue.
        The intermediate 'claimed' status removes it from the queue while letting
        run_task's running/completed guard still fire (claimed ∉ {running,completed}).
        """
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "UPDATE video_tasks SET status = 'claimed', updated_at = NOW() "
                "WHERE id = ("
                "  SELECT id FROM video_tasks WHERE status = 'queued'"
                "  ORDER BY queued_at ASC, created_at ASC"
                "  FOR UPDATE SKIP LOCKED LIMIT 1"
                ") RETURNING *"
            )
            return dict(row) if row else None

    async def get_queued_count(self) -> int:
        """Get total number of queued tasks."""
        results = await query(
            self.pool, sql="SELECT COUNT(*) as count FROM video_tasks WHERE status = 'queued'"
        )
        return int(results[0]["count"]) if results else 0

    async def get_tasks_ahead(self, queued_at: datetime) -> int:
        """Get count of tasks queued before the given timestamp."""
        results = await query(
            self.pool,
            sql=(
                "SELECT COUNT(*) as count FROM video_tasks"
                " WHERE status = 'queued' AND queued_at < $1"
            ),
            params=[queued_at],
        )
        return int(results[0]["count"]) if results else 0
