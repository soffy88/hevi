import json
import uuid
from datetime import UTC, datetime
from typing import Any

from obase.persistence import PgPool, insert_one, query, read_one, update_one

from hevi.core.config import settings
from hevi.execution import ResourceSnapshot, Scheduler, SchedulingDecision, SchedulingRequest
from hevi.tasks.attempt_repository import AttemptRepository
from hevi.tasks.state_machine import validate_task_transition


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

    async def get_task_by_idempotency_key(
        self, user_id: str | None, idempotency_key: str
    ) -> dict[str, Any] | None:
        """Return the task already created for a user/request key, if any."""

        rows = await query(
            self.pool,
            sql=(
                "SELECT * FROM video_tasks "
                "WHERE user_id IS NOT DISTINCT FROM $1 "
                "AND idempotency_key = $2 "
                "LIMIT 1"
            ),
            params=[user_id, idempotency_key],
        )
        return rows[0] if rows else None

    async def update_task(self, task_id: uuid.UUID, data: dict[str, Any]) -> bool:
        """Update task data and append a status event atomically in PostgreSQL.

        The local compatibility repository intentionally keeps using obase's
        generic helper.  Production workers, however, must never commit a
        task projection without the corresponding outbox event: a websocket
        consumer can then rebuild the task truth after a publisher restart.
        """
        if isinstance(self.pool, PgPool):
            return await self._update_task_postgres(task_id, data)
        return await update_one(self.pool, table="video_tasks", id=task_id, data=data)

    async def _update_task_postgres(self, task_id: uuid.UUID, data: dict[str, Any]) -> bool:
        allowed_columns = {
            "topic",
            "duration_archetype",
            "video_provider",
            "audio_provider",
            "status",
            "progress_pct",
            "total_shots",
            "completed_shots",
            "result_video_path",
            "error",
            "config_json",
            "created_at",
            "updated_at",
            "user_id",
            "idempotency_key",
            "queued_at",
            "queue_position",
            "series_id",
            "episode_index",
            "priority",
            "deadline_at",
            "available_at",
            "resource_class",
            "required_vram_mb",
            "expected_cost_usd",
            "tenant_weight",
            "warm_provider",
            "current_attempt_id",
            "scheduled_at",
            "scheduler_score",
            "scheduler_policy_version",
            "scheduler_decision_json",
            "worker_id",
            "lease_token",
            "lease_until",
            "heartbeat_at",
        }
        unknown = set(data) - allowed_columns
        if unknown:
            raise ValueError(f"unsupported video_tasks columns: {sorted(unknown)}")
        if not data:
            return True

        assignments: list[str] = []
        params: list[Any] = []
        for column, value in data.items():
            params.append(value)
            assignments.append(f'"{column}" = ${len(params)}')
        if "updated_at" not in data:
            assignments.append("updated_at = NOW()")
        params.append(task_id)
        task_param = len(params)

        async with self.pool.acquire() as conn, conn.transaction():
            previous = await conn.fetchrow(
                "SELECT id, status FROM video_tasks WHERE id = $1 FOR UPDATE", task_id
            )
            if previous is None:
                return False
            previous_status = str(previous["status"])
            current_status = str(data.get("status", previous_status))
            validate_task_transition(previous_status, current_status)
            updated = await conn.fetchrow(
                "UPDATE video_tasks SET "
                + ", ".join(assignments)
                + f" WHERE id = ${task_param} RETURNING id, status, progress_pct, updated_at",
                *params,
            )
            if updated is None:
                return False
            if previous_status != current_status:
                await conn.execute(
                    """
                    INSERT INTO domain_events
                        (id, aggregate_type, aggregate_id, event_type,
                         schema_version, payload, created_at)
                    VALUES ($1, 'task', $2, $3, 1, $4, NOW())
                    """,
                    uuid.uuid4(),
                    task_id,
                    f"task.status.{current_status}",
                    {
                        "task_id": str(task_id),
                        "from_status": previous_status,
                        "to_status": current_status,
                        "progress_pct": float(updated["progress_pct"] or 0.0),
                    },
                )
        return True

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

    async def save_shot(self, row: dict[str, Any]) -> None:
        """回写一行 shot_states(镜头准备确认等就地更新 selection_json)。"""
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE shot_states SET selection_json = $1, status = $2, "
                "updated_at = $3 WHERE id = $4",
                json.dumps(row.get("selection_json") or {}, ensure_ascii=False),
                str(row.get("status") or "pending"),
                datetime.now(UTC).replace(tzinfo=None),
                row["id"],
            )

    async def get_next_queued_task(self) -> dict[str, Any] | None:
        """Get the oldest queued task (read-only peek; NOT a claim)."""
        results = await query(
            self.pool,
            sql=(
                "SELECT * FROM video_tasks WHERE status = 'queued'"
                " AND (available_at IS NULL OR available_at <= NOW())"
                " ORDER BY queued_at ASC, created_at ASC LIMIT 1"
            ),
        )
        return results[0] if results else None

    async def claim_next_queued_task(
        self,
        worker_id: str | None = None,
        lease_seconds: int | None = None,
        *,
        resource_class: str = "any",
        available_vram_mb: int | None = None,
        capacity_slots: int = 1,
        provider_tokens: dict[str, int] | None = None,
        warm_providers: set[str] | None = None,
        scheduled_only: bool | None = None,
    ) -> dict[str, Any] | None:
        """Select and claim the best eligible queued task atomically.

        PostgreSQL locks a bounded candidate window with ``SKIP LOCKED``;
        ``Scheduler`` then ranks those rows using priority, deadline, resource
        fit, warm provider, quota, expected cost, and tenant fairness before the
        lease update and decision audit are committed together.
        """
        worker_id = worker_id or f"compat-{uuid.uuid4()}"
        lease_seconds = lease_seconds or settings.task_lease_seconds
        if scheduled_only is None:
            # This repository method is also the low-level atomic-claim
            # primitive used by compatibility callers and tests.  The worker
            # facade (``queue.dequeue``) supplies the scheduler policy
            # explicitly; an omitted flag here must retain the legacy claim
            # semantics for queued rows that have not gone through the
            # scheduler yet.
            scheduled_only = False
        lease_token = str(uuid.uuid4())
        scheduler = Scheduler()
        scheduled_clause = " AND scheduled_at IS NOT NULL" if scheduled_only else ""
        async with self.pool.acquire() as conn, conn.transaction():
            rows = await conn.fetch(
                f"""
                SELECT * FROM video_tasks
                WHERE status = 'queued'
                  AND (available_at IS NULL OR available_at <= NOW())
                  AND ($1 = 'any' OR resource_class IN ('any', $1))
                  AND ($2::integer IS NULL OR required_vram_mb <= $2)
                  {scheduled_clause}
                ORDER BY """
                + (
                    "scheduled_at ASC, scheduler_score DESC NULLS LAST, "
                    "queued_at ASC, created_at ASC"
                    if scheduled_only
                    else "priority DESC, deadline_at ASC NULLS LAST, queued_at ASC, created_at ASC"
                )
                + """
                FOR UPDATE SKIP LOCKED
                -- Lock only the row this worker will claim. Locking a whole
                -- candidate window makes concurrent workers skip every other
                -- queued row until the first transaction commits.
                LIMIT 1
                """,
                resource_class,
                available_vram_mb,
            )
            if not rows:
                return None
            decision: SchedulingDecision | None
            if scheduled_only:
                selected = rows[0]
                raw_decision = selected.get("scheduler_decision_json") or {}
                decision = SchedulingDecision(
                    task_id=selected["id"],
                    feasible=True,
                    score=float(selected.get("scheduler_score") or 0.0),
                    components=dict(raw_decision.get("components") or {}),
                    reasons=[],
                    policy_version=int(selected.get("scheduler_policy_version") or 1),
                    worker_id=worker_id,
                )
            else:
                active_rows = await conn.fetch(
                    "SELECT user_id, COUNT(*) AS running FROM video_tasks "
                    "WHERE status IN ('claimed', 'running') GROUP BY user_id"
                )
                tenant_running = {
                    str(row["user_id"] or "anonymous"): int(row["running"])
                    for row in active_rows
                }
                resources = ResourceSnapshot(
                    worker_id=worker_id,
                    resource_class=resource_class,
                    available_vram_mb=available_vram_mb,
                    capacity_slots=capacity_slots,
                    provider_tokens=provider_tokens or {},
                    warm_providers=warm_providers or set(),
                    tenant_running=tenant_running,
                )
                requests = [SchedulingRequest.from_task(dict(row)) for row in rows]
                decision = scheduler.choose(requests, resources)
                if decision is None:
                    return None
                selected = next(row for row in rows if row["id"] == decision.task_id)
            assert decision is not None
            claimed = await conn.fetchrow(
                """
                UPDATE video_tasks
                SET status = 'claimed', worker_id = $1, lease_token = $2,
                    lease_until = NOW() + ($3 * interval '1 second'),
                    heartbeat_at = NOW(), scheduled_at = NULL, updated_at = NOW()
                WHERE id = $4 AND status = 'queued'
                RETURNING video_tasks.*
                """,
                worker_id,
                lease_token,
                lease_seconds,
                selected["id"],
            )
            if claimed is None:
                return None
            await conn.execute(
                """
                INSERT INTO domain_events
                    (id, aggregate_type, aggregate_id, event_type,
                     schema_version, payload, created_at)
                VALUES ($1, 'task', $2, 'task.status.claimed', 1, $3, NOW())
                """,
                uuid.uuid4(),
                selected["id"],
                {
                    "task_id": str(selected["id"]),
                    "from_status": "queued",
                    "to_status": "claimed",
                    "worker_id": worker_id,
                    "lease_token": lease_token,
                },
            )
            await conn.execute(
                """
                INSERT INTO scheduler_dispatches
                    (id, task_id, worker_id, score, policy_version, decision_json)
                VALUES ($1, $2, $3, $4, $5, $6)
                """,
                uuid.uuid4(),
                selected["id"],
                worker_id,
                decision.score,
                decision.policy_version,
                decision.model_dump(mode="json"),
            )
            result = dict(claimed)
            result["_scheduler_decision"] = decision.model_dump(mode="json")
            return result

    async def heartbeat(
        self, task_id: uuid.UUID, lease_token: str, lease_seconds: int = 120
    ) -> bool:
        """Renew a task only for its current owner."""

        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                UPDATE video_tasks
                SET lease_until = NOW() + ($3 * interval '1 second'),
                    heartbeat_at = NOW(), updated_at = NOW()
                WHERE id = $1
                  AND lease_token = $2
                  AND status IN ('claimed', 'running')
                RETURNING id
                """,
                task_id,
                lease_token,
                lease_seconds,
            )
        return row is not None

    async def clear_lease(self, task_id: uuid.UUID, lease_token: str | None = None) -> bool:
        """Clear ownership fields after a terminal transition."""

        async with self.pool.acquire() as conn:
            if lease_token is None:
                result = await conn.execute(
                    """
                    UPDATE video_tasks
                    SET worker_id = NULL, lease_token = NULL, lease_until = NULL,
                        heartbeat_at = NULL, updated_at = NOW()
                    WHERE id = $1
                    """,
                    task_id,
                )
            else:
                result = await conn.execute(
                    """
                    UPDATE video_tasks
                    SET worker_id = NULL, lease_token = NULL, lease_until = NULL,
                        heartbeat_at = NULL, updated_at = NOW()
                    WHERE id = $1 AND lease_token = $2
                    """,
                    task_id,
                    lease_token,
                )
        return bool(result.endswith("1"))

    async def latest_checkpoint(self, task_id: uuid.UUID) -> dict[str, Any] | None:
        """Return the latest durable checkpoint for a production task.

        This method deliberately has no SQLite fallback: callers that run in
        local mode can keep their explicitly local compatibility projection,
        while the PostgreSQL task API always reads checkpoint state from the
        attempt history.
        """
        if not isinstance(self.pool, PgPool):
            return None
        return await AttemptRepository(self.pool).latest(task_id)

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
