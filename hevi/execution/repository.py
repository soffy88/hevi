"""PostgreSQL repository for immutable execution-plan versions."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal, cast

from obase.persistence import PgPool

from .plan import ExecutionPlan, ImmutablePlanViolation


def _uuid(value: str | uuid.UUID | None) -> uuid.UUID | None:
    if value is None:
        return None
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def _plan_from_row(row: Any) -> ExecutionPlan:
    created_at = row["created_at"]
    if isinstance(created_at, datetime):
        created_at = created_at.isoformat()
    raw_json = row["plan_json"]
    if isinstance(raw_json, str):
        import json

        raw_json = json.loads(raw_json)
    return ExecutionPlan(
        id=str(row["id"]),
        production_id=str(row["production_id"]),
        revision_id=str(row["revision_id"]),
        plan_version=int(row["plan_version"]),
        plan_json=dict(raw_json),
        plan_hash=str(row["plan_hash"]),
        parent_plan_id=str(row["parent_plan_id"]) if row["parent_plan_id"] else None,
        created_by_attempt_id=(
            str(row["created_by_attempt_id"]) if row["created_by_attempt_id"] else None
        ),
        change_reason=cast(
            Literal["initial", "repair", "replan", "manual_edit"],
            str(row["change_reason"]),
        ),
        created_at=str(created_at),
    )


class ExecutionPlanRepository:
    """INSERT-only persistence with database-enforced idempotency."""

    def __init__(self, pool: PgPool) -> None:
        self.pool = pool

    async def get(
        self,
        production_id: str | uuid.UUID,
        revision_id: str | uuid.UUID,
        plan_version: int,
    ) -> ExecutionPlan | None:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, production_id, revision_id, plan_version, plan_json,
                       plan_hash, parent_plan_id, created_by_attempt_id,
                       change_reason, created_at
                FROM execution_plans
                WHERE production_id = $1 AND revision_id = $2 AND plan_version = $3
                """,
                _uuid(production_id),
                _uuid(revision_id),
                plan_version,
            )
        return _plan_from_row(row) if row is not None else None

    async def save(self, plan: ExecutionPlan) -> ExecutionPlan:
        """Insert a plan or return the existing identical version.

        The unique key is locked by PostgreSQL.  A conflicting different hash
        is an immutable-plan violation; no existing row is updated.
        """

        production_id = _uuid(plan.production_id)
        revision_id = _uuid(plan.revision_id)
        if production_id is None or revision_id is None:
            raise ValueError("execution plan requires production_id and revision_id")
        parent_plan_id = _uuid(plan.parent_plan_id)
        created_by_attempt_id = _uuid(plan.created_by_attempt_id)
        async with self.pool.acquire() as conn, conn.transaction():
            inserted = await conn.fetchrow(
                """
                INSERT INTO execution_plans
                    (id, production_id, revision_id, plan_version, plan_json,
                     plan_hash, parent_plan_id, created_by_attempt_id,
                     change_reason, created_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                ON CONFLICT (production_id, revision_id, plan_version) DO NOTHING
                RETURNING id, production_id, revision_id, plan_version, plan_json,
                          plan_hash, parent_plan_id, created_by_attempt_id,
                          change_reason, created_at
                """,
                _uuid(plan.id) or uuid.uuid4(),
                production_id,
                revision_id,
                plan.plan_version,
                plan.plan_json,
                plan.plan_hash,
                parent_plan_id,
                created_by_attempt_id,
                plan.change_reason,
                datetime.fromisoformat(plan.created_at)
                if plan.created_at
                else datetime.utcnow(),
            )
            if inserted is not None:
                return _plan_from_row(inserted)
            existing = await conn.fetchrow(
                """
                SELECT id, production_id, revision_id, plan_version, plan_json,
                       plan_hash, parent_plan_id, created_by_attempt_id,
                       change_reason, created_at
                FROM execution_plans
                WHERE production_id = $1 AND revision_id = $2 AND plan_version = $3
                FOR SHARE
                """,
                production_id,
                revision_id,
                plan.plan_version,
            )
            if existing is None:
                # A concurrent transaction can only make the row visible after
                # its insert commits.  Retrying the same operation is safe and
                # keeps this repository's public contract deterministic.
                raise RuntimeError("execution plan conflict row was not readable")
            if str(existing["plan_hash"]) != plan.plan_hash:
                raise ImmutablePlanViolation(
                    "execution plan version already exists with a different canonical hash"
                )
            return _plan_from_row(existing)

    async def create(self, plan: ExecutionPlan) -> ExecutionPlan:
        return await self.save(plan)


__all__ = ["ExecutionPlanRepository"]
