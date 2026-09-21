"""Durable process heartbeat for production workers."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from obase.persistence import PgPool


class WorkerHeartbeat:
    """Persist one worker's liveness in PostgreSQL.

    The row is deliberately separate from task leases: a worker can be idle
    while still healthy, and a task lease can remain fresh while a process is
    wedged.  Readiness therefore trusts this process-level heartbeat only.
    """

    def __init__(
        self,
        pool: PgPool,
        *,
        worker_id: str | None = None,
        service: str = "worker",
    ) -> None:
        self.pool = pool
        self.worker_id = worker_id or f"worker-{uuid.uuid4()}"
        self.service = service

    async def beat(self, *, status: str = "running") -> datetime:
        now = datetime.now(UTC)
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO worker_heartbeats
                    (worker_id, service, last_heartbeat_at, status, updated_at)
                VALUES ($1, $2, $3, $4, $3)
                ON CONFLICT (worker_id) DO UPDATE SET
                    service = EXCLUDED.service,
                    last_heartbeat_at = EXCLUDED.last_heartbeat_at,
                    status = EXCLUDED.status,
                    updated_at = EXCLUDED.updated_at
                """,
                self.worker_id,
                self.service,
                now,
                status,
            )
        return now

    async def mark_stopped(self) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE worker_heartbeats
                SET status = 'stopped', updated_at = NOW()
                WHERE worker_id = $1 AND service = $2
                """,
                self.worker_id,
                self.service,
            )

    @staticmethod
    async def readiness(pool: PgPool, *, ttl_seconds: int) -> dict[str, Any]:
        """Return the newest healthy worker heartbeat, if one is fresh."""

        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT worker_id, service, last_heartbeat_at, status
                FROM worker_heartbeats
                WHERE service = 'worker'
                  AND status = 'running'
                  AND last_heartbeat_at >= NOW() - ($1 * interval '1 second')
                ORDER BY last_heartbeat_at DESC
                LIMIT 1
                """,
                ttl_seconds,
            )
        if row is None:
            return {
                "status": "unavailable",
                "worker_id": None,
                "service": "worker",
                "ttl_seconds": ttl_seconds,
            }
        return {
            "status": "ok",
            "worker_id": str(row["worker_id"]),
            "service": str(row["service"]),
            "last_heartbeat_at": row["last_heartbeat_at"].isoformat(),
            "worker_status": str(row["status"]),
            "ttl_seconds": ttl_seconds,
        }


__all__ = ["WorkerHeartbeat"]
