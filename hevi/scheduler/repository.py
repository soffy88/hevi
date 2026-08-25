"""PostgreSQL coordination for the standalone scheduler service."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from obase.persistence import PgPool

from hevi.execution import ResourceSnapshot, Scheduler, SchedulingRequest


class SchedulerRepository:
    def __init__(self, pool: PgPool) -> None:
        self.pool = pool

    async def acquire_leader(
        self, name: str, owner_id: str, *, lease_seconds: int = 15
    ) -> bool:
        """Acquire/renew one leader lease without a process-local mutex."""

        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO scheduler_leases
                    (name, owner_id, lease_until, heartbeat_at, updated_at)
                VALUES ($1, $2, NOW() + ($3 * interval '1 second'), NOW(), NOW())
                ON CONFLICT (name) DO UPDATE SET
                    owner_id = EXCLUDED.owner_id,
                    lease_until = EXCLUDED.lease_until,
                    heartbeat_at = EXCLUDED.heartbeat_at,
                    updated_at = EXCLUDED.updated_at
                WHERE scheduler_leases.lease_until < NOW()
                   OR scheduler_leases.owner_id = EXCLUDED.owner_id
                RETURNING owner_id
                """,
                name,
                owner_id,
                lease_seconds,
            )
        return row is not None and str(row["owner_id"]) == owner_id

    async def schedule_once(
        self,
        resources: ResourceSnapshot,
        *,
        candidate_limit: int = 128,
        policy_version: int = 1,
    ) -> int:
        """Rank queued tasks and persist dispatch decisions atomically.

        Workers only claim rows with ``scheduled_at`` set.  The worker-side
        claim remains an ownership transaction, but policy calculation and
        queue ordering now live in this service.
        """

        scheduler = Scheduler(policy_version=policy_version)
        now = datetime.now(UTC).replace(tzinfo=None)
        async with self.pool.acquire() as conn, conn.transaction():
            rows = await conn.fetch(
                """
                SELECT * FROM video_tasks
                WHERE status = 'queued'
                  AND (available_at IS NULL OR available_at <= NOW())
                  AND scheduled_at IS NULL
                ORDER BY priority DESC, deadline_at ASC NULLS LAST,
                         queued_at ASC, created_at ASC
                FOR UPDATE SKIP LOCKED
                LIMIT $1
                """,
                candidate_limit,
            )
            if not rows:
                return 0

            active_rows = await conn.fetch(
                """SELECT user_id, COUNT(*) AS running
                   FROM video_tasks
                   WHERE status IN ('claimed', 'running')
                   GROUP BY user_id"""
            )
            running = {
                str(row["user_id"] or "anonymous"): int(row["running"])
                for row in active_rows
            }
            resources = resources.model_copy(update={"tenant_running": running})
            requests = [SchedulingRequest.from_task(dict(row)) for row in rows]
            decisions = scheduler.rank(requests, resources)
            selected = [decision for decision in decisions if decision.feasible]
            if not selected:
                return 0

            count = 0
            for decision in selected:
                await conn.execute(
                    """
                    UPDATE video_tasks
                    SET scheduled_at = $1,
                        scheduler_score = $2,
                        scheduler_policy_version = $3,
                        scheduler_decision_json = $4,
                        updated_at = NOW()
                    WHERE id = $5 AND status = 'queued' AND scheduled_at IS NULL
                    """,
                    now,
                    decision.score,
                    decision.policy_version,
                    decision.model_dump(mode="json"),
                    decision.task_id,
                )
                await conn.execute(
                    """
                    INSERT INTO scheduler_dispatches
                        (id, task_id, worker_id, score, policy_version, decision_json)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    """,
                    uuid.uuid4(),
                    decision.task_id,
                    resources.worker_id,
                    decision.score,
                    decision.policy_version,
                    decision.model_dump(mode="json"),
                )
                count += 1
            return count


__all__ = ["SchedulerRepository"]
