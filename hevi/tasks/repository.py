import uuid
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

    async def list_tasks(self, limit: int = 100, user_id: str | None = None) -> list[dict[str, Any]]:
        """List recent tasks, optionally filtered by user."""
        if user_id:
            return await query(
                self.pool,
                sql="SELECT * FROM video_tasks WHERE user_id = $1 ORDER BY created_at DESC",
                params=[user_id],
                limit=limit,
            )
        return await query(
            self.pool, sql="SELECT * FROM video_tasks ORDER BY created_at DESC", limit=limit
        )

    async def create_shot_state(self, data: dict[str, Any]) -> dict[str, Any]:
        """Create a shot state entry."""
        if "id" not in data:
            data["id"] = uuid.uuid4()
        return await insert_one(self.pool, table="shot_states", data=data)  # type: ignore

    async def get_shots(self, task_id: uuid.UUID) -> list[dict[str, Any]]:
        """Retrieve all shots for a task."""
        return await query(
            self.pool,
            sql="SELECT * FROM shot_states WHERE task_id = $1 ORDER BY shot_index ASC",
            params=[task_id],
        )
