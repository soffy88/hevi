"""PostgreSQL repositories for the durable case-learning execution records."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from obase.persistence import PgPool

from .case_analysis import CaseAnalysis


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class CaseAnalysisRepository:
    def __init__(self, pool: PgPool) -> None:
        self.pool = pool

    async def get_owned(self, analysis_id: str, *, user_id: str) -> dict[str, Any] | None:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM video_case_analyses WHERE id=$1 AND user_id=$2",
                uuid.UUID(analysis_id), uuid.UUID(user_id),
            )
        return dict(row) if row else None

    async def find_idempotent(
        self, *, case_id: str, user_id: str, key: str
    ) -> dict[str, Any] | None:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM video_case_analyses "
                "WHERE case_id=$1 AND user_id=$2 AND idempotency_key=$3",
                uuid.UUID(case_id), uuid.UUID(user_id), key,
            )
        return dict(row) if row else None

    async def create_pending(
        self, *, case_id: str, user_id: str, key: str, analyzer_version: str
    ) -> dict[str, Any]:
        analysis_id = uuid.uuid4()
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "INSERT INTO video_case_analyses "
                "(id,case_id,user_id,status,analyzer_version,idempotency_key) "
                "VALUES ($1,$2,$3,'pending',$4,$5) RETURNING *",
                analysis_id, uuid.UUID(case_id), uuid.UUID(user_id), analyzer_version, key,
            )
        if row is None:
            raise RuntimeError("CASE_ANALYSIS_PERSISTENCE_FAILED")
        return dict(row)

    async def mark_running(self, analysis_id: str, *, user_id: str) -> bool:
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE video_case_analyses SET status='running', started_at=COALESCE(started_at,NOW()), updated_at=NOW() "
                "WHERE id=$1 AND user_id=$2 AND status IN ('pending','running')",
                uuid.UUID(analysis_id), uuid.UUID(user_id),
            )
        return str(result).endswith("1")

    async def succeed(
        self, analysis_id: str, *, user_id: str, analysis: CaseAnalysis
    ) -> bool:
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE video_case_analyses SET status='succeeded', analysis_json=$1, completed_at=NOW(), updated_at=NOW() "
                "WHERE id=$2 AND user_id=$3 AND status IN ('pending','running')",
                analysis.model_dump(mode="json"), uuid.UUID(analysis_id), uuid.UUID(user_id),
            )
        return str(result).endswith("1")

    async def fail(
        self, analysis_id: str, *, user_id: str, reason: str
    ) -> bool:
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE video_case_analyses SET status='failed', failure_reason=$1, completed_at=NOW(), updated_at=NOW() "
                "WHERE id=$2 AND user_id=$3 AND status NOT IN ('succeeded','failed')",
                reason[:2000], uuid.UUID(analysis_id), uuid.UUID(user_id),
            )
        return str(result).endswith("1")


class CaseReproductionRepository:
    def __init__(self, pool: PgPool) -> None:
        self.pool = pool

    async def get_owned(self, reproduction_id: str, *, user_id: str) -> dict[str, Any] | None:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM case_reproductions WHERE id=$1 AND user_id=$2",
                uuid.UUID(reproduction_id), uuid.UUID(user_id),
            )
        return dict(row) if row else None

    async def find_idempotent(
        self, *, case_id: str, user_id: str, key: str
    ) -> dict[str, Any] | None:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM case_reproductions WHERE case_id=$1 AND user_id=$2 AND idempotency_key=$3",
                uuid.UUID(case_id), uuid.UUID(user_id), key,
            )
        return dict(row) if row else None

    async def create_pending(
        self, *, case_id: str, user_id: str, workspace_id: str | None,
        key: str, provider_id: str, model_id: str, model_version: str | None,
        generation_mode: str, compiled_prompt: str,
        reference_bindings: list[dict[str, Any]], parameters: dict[str, Any],
        task_id: str,
    ) -> dict[str, Any]:
        reproduction_id = uuid.uuid4()
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "INSERT INTO case_reproductions "
                "(id,workspace_id,user_id,case_id,task_id,status,provider_id,model_id,model_version,"
                "generation_mode,compiled_prompt,reference_binding_snapshot,generation_parameters,idempotency_key) "
                "VALUES ($1,$2,$3,$4,$5,'pending',$6,$7,$8,$9,$10,$11,$12,$13) RETURNING *",
                reproduction_id, workspace_id, uuid.UUID(user_id), uuid.UUID(case_id), uuid.UUID(task_id),
                provider_id, model_id, model_version, generation_mode, compiled_prompt,
                reference_bindings, parameters, key,
            )
        if row is None:
            raise RuntimeError("CASE_REPRODUCTION_PERSISTENCE_FAILED")
        return dict(row)

    async def mark_running(self, reproduction_id: str, *, user_id: str) -> bool:
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE case_reproductions SET status='running', started_at=COALESCE(started_at,NOW()) "
                "WHERE id=$1 AND user_id=$2 AND status IN ('pending','running')",
                uuid.UUID(reproduction_id), uuid.UUID(user_id),
            )
        return str(result).endswith("1")

    async def update_plan(
        self, reproduction_id: str, *, user_id: str, compiled_prompt: str,
        reference_bindings: list[dict[str, Any]], parameters: dict[str, Any]
    ) -> bool:
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE case_reproductions SET compiled_prompt=$1, reference_binding_snapshot=$2, "
                "generation_parameters=$3 WHERE id=$4 AND user_id=$5 AND status='running'",
                compiled_prompt, reference_bindings, parameters,
                uuid.UUID(reproduction_id), uuid.UUID(user_id),
            )
        return str(result).endswith("1")

    async def attach_verdict(
        self, reproduction_id: str, *, user_id: str, verdict_id: str
    ) -> bool:
        """Attach canonical verdict evidence only within the owner fence."""
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE case_reproductions SET verdict_id=$1 "
                "WHERE id=$2 AND user_id=$3 AND status IN ('running','generated','verdicted')",
                uuid.UUID(verdict_id), uuid.UUID(reproduction_id), uuid.UUID(user_id),
            )
        return str(result).endswith("1")

    async def succeed(
        self, reproduction_id: str, *, user_id: str, output_asset_id: str,
        verdict_id: str, cost_amount: float | None, latency_ms: float,
    ) -> bool:
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE case_reproductions SET status='succeeded', output_asset_id=$1, verdict_id=$2, "
                "cost_amount=$3, latency_ms=$4, completed_at=NOW() "
                "WHERE id=$5 AND user_id=$6 AND status IN ('pending','running','generated','verdicted')",
                uuid.UUID(output_asset_id), uuid.UUID(verdict_id),
                Decimal(str(cost_amount)) if cost_amount is not None else None,
                latency_ms, uuid.UUID(reproduction_id), uuid.UUID(user_id),
            )
        return str(result).endswith("1")

    async def record_generated(
        self, reproduction_id: str, *, user_id: str, output_asset_id: str,
        latency_ms: float, cost_amount: float | None = None,
    ) -> bool:
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE case_reproductions SET status='generated', output_asset_id=$1, "
                "latency_ms=$2, cost_amount=COALESCE($3,cost_amount) "
                "WHERE id=$4 AND user_id=$5 AND status IN ('running','pending')",
                uuid.UUID(output_asset_id), latency_ms,
                Decimal(str(cost_amount)) if cost_amount is not None else None,
                uuid.UUID(reproduction_id), uuid.UUID(user_id),
            )
        return str(result).endswith("1")

    async def record_verdicted(
        self, reproduction_id: str, *, user_id: str, verdict_id: str
    ) -> bool:
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE case_reproductions SET status='verdicted', verdict_id=$1 "
                "WHERE id=$2 AND user_id=$3 AND status IN ('generated','running')",
                uuid.UUID(verdict_id), uuid.UUID(reproduction_id), uuid.UUID(user_id),
            )
        return str(result).endswith("1")

    async def fail(
        self, reproduction_id: str, *, user_id: str, failure_code: str,
        failure_detail: str, latency_ms: float | None = None, cost_amount: float | None = None,
    ) -> bool:
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE case_reproductions SET status='failed', failure_code=$1, failure_detail=$2, "
                "latency_ms=COALESCE($3,latency_ms), cost_amount=COALESCE($4,cost_amount), completed_at=NOW() "
                "WHERE id=$5 AND user_id=$6 AND status NOT IN ('succeeded','failed')",
                failure_code[:128], failure_detail[:4000], latency_ms,
                Decimal(str(cost_amount)) if cost_amount is not None else None,
                uuid.UUID(reproduction_id), uuid.UUID(user_id),
            )
        return str(result).endswith("1")


__all__ = ["CaseAnalysisRepository", "CaseReproductionRepository"]
