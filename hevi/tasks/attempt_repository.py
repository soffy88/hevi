"""Durable task-attempt and checkpoint persistence.

The task row is a projection used by the API.  This repository owns the
execution history so a worker can die after any checkpoint and another worker
can resume from the last committed boundary.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from obase.persistence import PgPool


def _now() -> datetime:
    return datetime.now(UTC)


class AttemptRepository:
    def __init__(self, pool: PgPool) -> None:
        self.pool = pool

    async def start(
        self,
        task_id: uuid.UUID,
        *,
        worker_id: str,
        lease_token: str,
        lease_until: datetime | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create the next attempt unless the task already has one in flight."""

        async with self.pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                "SELECT current_attempt_id FROM video_tasks WHERE id = $1 FOR UPDATE",
                task_id,
            )
            if row is None:
                raise ValueError(f"Task {task_id} not found")
            current_id = row["current_attempt_id"]
            if current_id is not None:
                current = await conn.fetchrow(
                    """SELECT * FROM task_attempts
                       WHERE id = $1
                         AND status IN ('claimed', 'running')
                         AND lease_token = $2
                         AND (lease_until IS NULL OR lease_until > NOW())""",
                    current_id,
                    lease_token,
                )
                if current is not None:
                    return dict(current)
                await conn.execute(
                    """UPDATE task_attempts
                       SET status = 'interrupted', finished_at = NOW(),
                           error = 'superseded after lease recovery', lease_until = NULL
                       WHERE id = $1 AND status IN ('claimed', 'running')""",
                    current_id,
                )
            return await self._insert_for_claim(
                conn,
                task_id,
                worker_id=worker_id,
                lease_token=lease_token,
                lease_until=lease_until,
                metadata=metadata,
            )

    async def heartbeat(
        self,
        attempt_id: uuid.UUID,
        *,
        lease_token: str,
        lease_seconds: int = 120,
    ) -> bool:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                UPDATE task_attempts
                SET lease_until = NOW() + ($3 * interval '1 second'),
                    heartbeat_at = NOW()
                WHERE id = $1 AND lease_token = $2
                  AND status IN ('claimed', 'running')
                RETURNING id
                """,
                attempt_id,
                lease_token,
                lease_seconds,
            )
        return row is not None

    async def mark_running(self, attempt_id: uuid.UUID, *, lease_token: str) -> bool:
        return await self._mark_status(attempt_id, lease_token=lease_token, status="running")

    async def finish(
        self,
        attempt_id: uuid.UUID,
        *,
        lease_token: str,
        status: str,
        error: str | None = None,
    ) -> bool:
        if status not in {"succeeded", "failed", "cancelled", "interrupted", "paused"}:
            raise ValueError(f"invalid terminal attempt status: {status}")
        return await self._mark_status(
            attempt_id,
            lease_token=lease_token,
            status=status,
            error=error,
            terminal=True,
        )

    async def checkpoint(
        self,
        *,
        attempt_id: uuid.UUID,
        task_id: uuid.UUID,
        stage: str,
        progress_pct: float,
        completed_shots: int = 0,
        total_shots: int = 0,
        state: dict[str, Any] | None = None,
        artifact_manifest: dict[str, Any] | None = None,
        sequence: int | None = None,
    ) -> dict[str, Any]:
        """Append a checkpoint; retries of the same sequence are idempotent."""

        async with self.pool.acquire() as conn, conn.transaction():
            if sequence is None:
                sequence = int(
                    await conn.fetchval(
                        """
                        SELECT COALESCE(MAX(sequence), -1) + 1
                        FROM attempt_checkpoints WHERE attempt_id = $1
                        """,
                        attempt_id,
                    )
                )
            checkpoint_id = uuid.uuid4()
            row = await conn.fetchrow(
                """
                INSERT INTO attempt_checkpoints
                    (id, attempt_id, task_id, sequence, stage, progress_pct,
                     completed_shots, total_shots, state_json,
                     artifact_manifest_json, created_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                ON CONFLICT (attempt_id, sequence) DO UPDATE SET
                    stage = EXCLUDED.stage,
                    progress_pct = EXCLUDED.progress_pct,
                    completed_shots = EXCLUDED.completed_shots,
                    total_shots = EXCLUDED.total_shots,
                    state_json = EXCLUDED.state_json,
                    artifact_manifest_json = EXCLUDED.artifact_manifest_json
                RETURNING *
                """,
                checkpoint_id,
                attempt_id,
                task_id,
                sequence,
                stage,
                max(0.0, min(100.0, float(progress_pct))),
                max(0, int(completed_shots)),
                max(0, int(total_shots)),
                state or {},
                artifact_manifest,
                _now(),
            )
        return dict(row)

    async def latest(self, task_id: uuid.UUID) -> dict[str, Any] | None:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT c.*, a.attempt_no, a.status AS attempt_status
                FROM attempt_checkpoints c
                JOIN task_attempts a ON a.id = c.attempt_id
                WHERE c.task_id = $1
                ORDER BY c.created_at DESC, c.sequence DESC
                LIMIT 1
                """,
                task_id,
            )
        return dict(row) if row is not None else None

    async def recover_expired(self, *, limit: int = 100) -> list[dict[str, Any]]:
        """Convert expired ownership into resumable queued work atomically."""

        async with self.pool.acquire() as conn, conn.transaction():
            rows = await conn.fetch(
                """
                SELECT id, task_id, attempt_no, worker_id, lease_token
                FROM task_attempts
                WHERE status IN ('claimed', 'running')
                  AND lease_until IS NOT NULL AND lease_until < NOW()
                  AND (heartbeat_at IS NULL OR heartbeat_at < NOW() - interval '30 seconds')
                ORDER BY lease_until ASC
                FOR UPDATE SKIP LOCKED
                LIMIT $1
                """,
                limit,
            )
            recovered: list[dict[str, Any]] = []
            for row in rows:
                updated = await conn.fetchrow(
                    """
                    UPDATE task_attempts
                    SET status = 'interrupted', finished_at = NOW(),
                        error = 'attempt lease expired; queued for cross-worker recovery',
                        lease_until = NULL
                    WHERE id = $1 AND status IN ('claimed', 'running')
                    RETURNING *
                    """,
                    row["id"],
                )
                if updated is None:
                    continue
                await conn.execute(
                    """
                    UPDATE video_tasks
                    SET status = 'queued', worker_id = NULL, lease_token = NULL,
                        lease_until = NULL, heartbeat_at = NULL,
                        current_attempt_id = NULL,
                        available_at = NOW(), updated_at = NOW()
                    WHERE id = $1 AND current_attempt_id = $2
                    """,
                    row["task_id"],
                    row["id"],
                )
                await conn.execute(
                    """
                    INSERT INTO domain_events
                        (id, aggregate_type, aggregate_id, event_type,
                         schema_version, payload, created_at)
                    VALUES ($1, 'task', $2, 'task.status.queued', 1, $3, NOW())
                    """,
                    uuid.uuid4(),
                    row["task_id"],
                    {
                        "task_id": str(row["task_id"]),
                        "from_status": "running",
                        "to_status": "queued",
                        "reason": "attempt_lease_expired",
                    },
                )
                recovered.append(dict(updated))
            # Roll forward tasks claimed by the pre-attempt worker during a
            # rolling deployment.  They have no attempt row, but their
            # durable task lease is still sufficient evidence of ownership
            # loss and must not remain stuck forever.
            legacy_rows = await conn.fetch(
                """
                SELECT id, lease_token
                FROM video_tasks
                WHERE current_attempt_id IS NULL
                  AND status IN ('claimed', 'running')
                  AND lease_until IS NOT NULL AND lease_until < NOW()
                  AND (heartbeat_at IS NULL OR heartbeat_at < NOW() - interval '30 seconds')
                FOR UPDATE SKIP LOCKED
                LIMIT $1
                """,
                max(0, limit - len(recovered)),
            )
            for row in legacy_rows:
                updated = await conn.fetchrow(
                    """
                    UPDATE video_tasks
                    SET status = 'queued', worker_id = NULL, lease_token = NULL,
                        lease_until = NULL, heartbeat_at = NULL,
                        available_at = NOW(), scheduled_at = NULL, updated_at = NOW()
                    WHERE id = $1 AND current_attempt_id IS NULL
                    RETURNING id
                    """,
                    row["id"],
                )
                if updated is not None:
                    await conn.execute(
                        """
                        INSERT INTO domain_events
                            (id, aggregate_type, aggregate_id, event_type,
                             schema_version, payload, created_at)
                        VALUES ($1, 'task', $2, 'task.status.queued', 1, $3, NOW())
                        """,
                        uuid.uuid4(),
                        row["id"],
                        {
                            "task_id": str(row["id"]),
                            "from_status": "running_or_claimed",
                            "to_status": "queued",
                            "reason": "legacy_lease_expired",
                        },
                    )
                    recovered.append({"task_id": updated["id"], "legacy": True})
        return recovered

    @staticmethod
    async def _insert_for_claim(
        conn: Any,
        task_id: uuid.UUID,
        *,
        worker_id: str,
        lease_token: str,
        lease_until: datetime | None,
        metadata: dict[str, Any] | None,
    ) -> dict[str, Any]:
        attempt_id = uuid.uuid4()
        attempt_no = int(
            await conn.fetchval(
                "SELECT COALESCE(MAX(attempt_no), 0) + 1 FROM task_attempts WHERE task_id = $1",
                task_id,
            )
        )
        row = await conn.fetchrow(
            """
            INSERT INTO task_attempts
                (id, task_id, attempt_no, status, worker_id, lease_token,
                 lease_until, heartbeat_at, started_at, metadata, created_at)
            VALUES ($1, $2, $3, 'claimed', $4, $5, $6, NOW(), NOW(), $7, NOW())
            RETURNING *
            """,
            attempt_id,
            task_id,
            attempt_no,
            worker_id,
            lease_token,
            lease_until,
            metadata or {},
        )
        await conn.execute(
            "UPDATE video_tasks SET current_attempt_id = $1 WHERE id = $2",
            attempt_id,
            task_id,
        )
        return dict(row)

    async def _mark_status(
        self,
        attempt_id: uuid.UUID,
        *,
        lease_token: str,
        status: str,
        error: str | None = None,
        terminal: bool = False,
    ) -> bool:
        finished_sql = ", finished_at = NOW(), lease_until = NULL" if terminal else ""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                f"""
                UPDATE task_attempts
                SET status = $3, error = $4{finished_sql}
                WHERE id = $1 AND lease_token = $2
                  AND status IN ('claimed', 'running')
                RETURNING id
                """,
                attempt_id,
                lease_token,
                status,
                error,
            )
        return row is not None


__all__ = ["AttemptRepository"]
