"""Durable provider health/quota/outcome state used by the policy engine."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from obase.persistence import PgPool


class ProviderStateRepository:
    def __init__(self, pool: PgPool) -> None:
        self.pool = pool

    async def get(self, provider_id: str) -> dict[str, Any] | None:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM provider_runtime_state WHERE provider_id = $1",
                provider_id,
            )
        return dict(row) if row is not None else None

    async def upsert(
        self,
        provider_id: str,
        *,
        health: float | None = None,
        balance_usd: Decimal | float | None = None,
        quota_remaining: int | None = None,
        p95_latency_ms: float | None = None,
        error_rate: float | None = None,
        quality_score: float | None = None,
        source: str = "runtime",
    ) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO provider_runtime_state
                    (provider_id, health, balance_usd, quota_remaining,
                     p95_latency_ms, error_rate, quality_score, source, updated_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW())
                ON CONFLICT (provider_id) DO UPDATE SET
                    health = COALESCE(EXCLUDED.health, provider_runtime_state.health),
                    balance_usd = COALESCE(
                        EXCLUDED.balance_usd, provider_runtime_state.balance_usd
                    ),
                    quota_remaining = COALESCE(
                        EXCLUDED.quota_remaining, provider_runtime_state.quota_remaining
                    ),
                    p95_latency_ms = COALESCE(
                        EXCLUDED.p95_latency_ms, provider_runtime_state.p95_latency_ms
                    ),
                    error_rate = COALESCE(EXCLUDED.error_rate, provider_runtime_state.error_rate),
                    quality_score = COALESCE(
                        EXCLUDED.quality_score, provider_runtime_state.quality_score
                    ),
                    source = EXCLUDED.source,
                    updated_at = NOW()
                """,
                provider_id,
                health,
                balance_usd,
                quota_remaining,
                p95_latency_ms,
                error_rate,
                quality_score,
                source,
            )

    async def record_outcome(
        self,
        provider_id: str,
        *,
        task_class: str,
        status: str,
        latency_ms: float | None = None,
        cost_usd: Decimal | float | None = None,
        quality_score: float | None = None,
        error_code: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> uuid.UUID:
        outcome_id = uuid.uuid4()
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO provider_outcomes
                    (id, provider_id, task_class, status, latency_ms, cost_usd,
                     quality_score, error_code, metadata, created_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                """,
                outcome_id,
                provider_id,
                task_class,
                status,
                latency_ms,
                cost_usd,
                quality_score,
                error_code,
                metadata or {},
                datetime.now(UTC),
            )
            # The policy engine consumes the durable outcome history rather
            # than a permanently hard-coded quality ranking. Keep the
            # rolling prior on the runtime row so routing remains a single
            # cheap read while the raw observations remain auditable.
            await conn.execute(
                """
                INSERT INTO provider_runtime_state
                    (provider_id, quality_score, source, updated_at)
                SELECT $1::varchar, AVG(quality_score), 'outcome_aggregate', NOW()
                FROM provider_outcomes
                WHERE provider_id = $1::varchar AND quality_score IS NOT NULL
                ON CONFLICT (provider_id) DO UPDATE SET
                    quality_score = EXCLUDED.quality_score,
                    source = EXCLUDED.source,
                    updated_at = EXCLUDED.updated_at
                """,
                provider_id,
            )
        return outcome_id


__all__ = ["ProviderStateRepository"]
