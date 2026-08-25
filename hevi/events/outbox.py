"""Transactional outbox contracts and PostgreSQL access.

Writers append events in the same transaction as their aggregate update.  A
separate publisher can safely claim unpublished rows later; losing the
publisher never loses the event or the production state.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from obase.persistence import PgPool
from pydantic import BaseModel, Field

from hevi.monitoring.metrics import outbox_events_total


class DomainEvent(BaseModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    event_type: str
    aggregate_type: str = "production"
    aggregate_id: uuid.UUID
    schema_version: int = 1
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    payload: dict[str, Any] = Field(default_factory=dict)
    claim_token: uuid.UUID | None = None


class OutboxRepository:
    def __init__(self, pool: PgPool) -> None:
        self.pool = pool

    async def append(self, event: DomainEvent) -> DomainEvent:
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO domain_events
                    (id, aggregate_type, aggregate_id, event_type,
                     schema_version, payload, created_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                """,
                event.id,
                event.aggregate_type,
                event.aggregate_id,
                event.event_type,
                event.schema_version,
                event.payload,
                event.occurred_at,
            )
        return event

    async def claim_unpublished(
        self, limit: int = 100, lease_seconds: int = 60
    ) -> list[DomainEvent]:
        """Claim a replayable batch; acknowledgement remains explicit."""

        claim_token = uuid.uuid4()
        async with self.pool.acquire() as conn, conn.transaction():
            rows = await conn.fetch(
                """
                WITH candidates AS (
                    SELECT id
                    FROM domain_events
                    WHERE published_at IS NULL
                      AND (claimed_until IS NULL OR claimed_until < NOW())
                      AND NOT EXISTS (
                          SELECT 1 FROM event_dead_letters dl
                          WHERE dl.event_id = domain_events.id
                            AND dl.dead_lettered_at IS NOT NULL
                      )
                    ORDER BY created_at ASC
                    FOR UPDATE SKIP LOCKED
                    LIMIT $1
                )
                UPDATE domain_events AS event
                SET claim_token = $2,
                    claimed_until = NOW() + ($3 * interval '1 second')
                FROM candidates
                WHERE event.id = candidates.id
                RETURNING event.id, event.aggregate_type, event.aggregate_id,
                          event.event_type, event.schema_version, event.payload,
                          event.created_at, event.claim_token
                """,
                limit,
                claim_token,
                lease_seconds,
            )
        events = [
            DomainEvent(
                id=row["id"],
                aggregate_type=row["aggregate_type"],
                aggregate_id=row["aggregate_id"],
                event_type=row["event_type"],
                schema_version=row["schema_version"],
                payload=_decode_json(row["payload"]),
                occurred_at=row["created_at"],
                claim_token=row["claim_token"],
            )
            for row in rows
        ]
        outbox_events_total.labels(operation="claim", status="success").inc(len(events))
        return events

    async def mark_published(
        self, event_ids: list[uuid.UUID], claim_token: uuid.UUID | None = None
    ) -> int:
        if not event_ids:
            return 0
        async with self.pool.acquire() as conn:
            if claim_token is None:
                result = await conn.execute(
                    """
                    UPDATE domain_events
                    SET published_at = NOW(), claim_token = NULL, claimed_until = NULL
                    WHERE id = ANY($1::uuid[]) AND published_at IS NULL
                    """,
                    event_ids,
                )
            else:
                result = await conn.execute(
                    """
                    UPDATE domain_events
                    SET published_at = NOW(), claim_token = NULL, claimed_until = NULL
                    WHERE id = ANY($1::uuid[]) AND claim_token = $2
                      AND published_at IS NULL
                    """,
                    event_ids,
                    claim_token,
                )
        count = int(result.rsplit(" ", 1)[-1])
        outbox_events_total.labels(operation="publish", status="success").inc(count)
        return count

    async def replay(
        self,
        *,
        aggregate_id: uuid.UUID | None = None,
        after: datetime | None = None,
        limit: int = 500,
    ) -> list[DomainEvent]:
        """Read an ordered event history for reconnect/rebuild consumers."""

        clauses = ["created_at IS NOT NULL"]
        params: list[Any] = []
        if aggregate_id is not None:
            params.append(aggregate_id)
            clauses.append(f"aggregate_id = ${len(params)}")
        if after is not None:
            params.append(after)
            clauses.append(f"created_at > ${len(params)}")
        params.append(limit)
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, aggregate_type, aggregate_id, event_type,
                       schema_version, payload, created_at, claim_token
                FROM domain_events
                WHERE """
                + " AND ".join(clauses)
                + f" ORDER BY created_at ASC, id ASC LIMIT ${len(params)}",
                *params,
            )
        events = [
            DomainEvent(
                id=row["id"],
                aggregate_type=row["aggregate_type"],
                aggregate_id=row["aggregate_id"],
                event_type=row["event_type"],
                schema_version=row["schema_version"],
                payload=_decode_json(row["payload"]),
                occurred_at=row["created_at"],
                claim_token=row["claim_token"],
            )
            for row in rows
        ]
        outbox_events_total.labels(operation="replay", status="success").inc(len(events))
        return events

    async def release_claim(self, claim_token: uuid.UUID) -> int:
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE domain_events
                SET claim_token = NULL, claimed_until = NULL
                WHERE claim_token = $1 AND published_at IS NULL
                """,
                claim_token,
            )
        count = int(result.rsplit(" ", 1)[-1])
        outbox_events_total.labels(operation="release", status="success").inc(count)
        return count

    async def record_failure(
        self, event_id: uuid.UUID, error: str, *, max_attempts: int = 8
    ) -> bool:
        """Record a delivery failure and return whether it entered the DLQ."""

        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO event_dead_letters
                    (event_id, attempts, last_error, first_failed_at,
                     dead_lettered_at, updated_at)
                VALUES ($1, 1, $2, NOW(),
                        CASE WHEN $3 <= 1 THEN NOW() ELSE NULL END, NOW())
                ON CONFLICT (event_id) DO UPDATE SET
                    attempts = event_dead_letters.attempts + 1,
                    last_error = EXCLUDED.last_error,
                    dead_lettered_at = CASE
                        WHEN event_dead_letters.attempts + 1 >= $3 THEN NOW()
                        ELSE event_dead_letters.dead_lettered_at
                    END,
                    updated_at = NOW()
                RETURNING attempts, dead_lettered_at
                """,
                event_id,
                error[:4000],
                max_attempts,
            )
        return row is not None and row["dead_lettered_at"] is not None

    async def read_consumer_batch(
        self,
        consumer_name: str,
        *,
        limit: int = 100,
        aggregate_id: uuid.UUID | None = None,
    ) -> list[DomainEvent]:
        """Read events after a per-instance cursor without consuming globally."""

        async with self.pool.acquire() as conn:
            cursor = await conn.fetchrow(
                """SELECT last_created_at, last_event_id
                   FROM event_consumer_offsets
                   WHERE consumer_name = $1""",
                consumer_name,
            )
            clauses = ["published_at IS NOT NULL"]
            params: list[Any] = []
            if aggregate_id is not None:
                params.append(aggregate_id)
                clauses.append(f"aggregate_id = ${len(params)}")
            if cursor is not None and cursor["last_created_at"] is not None:
                created_param = len(params) + 1
                event_param = created_param + 1
                params.extend([cursor["last_created_at"], cursor["last_event_id"]])
                clauses.append(
                    f"(created_at > ${created_param} "
                    f"OR (created_at = ${created_param} AND id > ${event_param}))"
                )
            params.append(limit)
            rows = await conn.fetch(
                """SELECT id, aggregate_type, aggregate_id, event_type,
                          schema_version, payload, created_at, claim_token
                   FROM domain_events
                   WHERE """
                + " AND ".join(clauses)
                + f" ORDER BY created_at ASC, id ASC LIMIT ${len(params)}",
                *params,
            )
        return [
            DomainEvent(
                id=row["id"],
                aggregate_type=row["aggregate_type"],
                aggregate_id=row["aggregate_id"],
                event_type=row["event_type"],
                schema_version=row["schema_version"],
                payload=_decode_json(row["payload"]),
                occurred_at=row["created_at"],
                claim_token=row["claim_token"],
            )
            for row in rows
        ]

    async def advance_consumer(self, consumer_name: str, event: DomainEvent) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO event_consumer_offsets
                    (consumer_name, last_created_at, last_event_id, updated_at)
                VALUES ($1, $2, $3, NOW())
                ON CONFLICT (consumer_name) DO UPDATE SET
                    last_created_at = EXCLUDED.last_created_at,
                    last_event_id = EXCLUDED.last_event_id,
                    updated_at = NOW()
                WHERE event_consumer_offsets.last_created_at IS NULL
                   OR (EXCLUDED.last_created_at > event_consumer_offsets.last_created_at)
                   OR (EXCLUDED.last_created_at = event_consumer_offsets.last_created_at
                       AND EXCLUDED.last_event_id > event_consumer_offsets.last_event_id)
                """,
                consumer_name,
                event.occurred_at,
                event.id,
            )


def _decode_json(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    return dict(value or {})


__all__ = ["DomainEvent", "OutboxRepository"]
