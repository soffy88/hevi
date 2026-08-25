"""Relational reads and coverage updates for the constraint graph."""

from __future__ import annotations

import uuid
from typing import Literal, cast

from obase.persistence import PgPool

from .models import Constraint, ConstraintGraph, CoverageReport


class ConstraintRepository:
    def __init__(self, pool: PgPool) -> None:
        self.pool = pool

    async def get_for_production(self, production_id: str) -> ConstraintGraph | None:
        production_uuid = uuid.UUID(production_id)
        async with self.pool.acquire() as conn:
            revision = await conn.fetchrow(
                "SELECT active_revision_id FROM productions WHERE id = $1",
                production_uuid,
            )
            if revision is None or revision["active_revision_id"] is None:
                return None
            revision_id = revision["active_revision_id"]
            rows = await conn.fetch(
                """SELECT id, type, severity, scope, source_path, payload,
                          compile_required, verification_required, fallback_policy
                   FROM production_constraints
                   WHERE revision_id = $1
                   ORDER BY id""",
                revision_id,
            )
            dependency_rows = await conn.fetch(
                """SELECT constraint_id, depends_on_id
                   FROM constraint_dependencies
                   WHERE revision_id = $1""",
                revision_id,
            )
            coverage = await conn.fetchrow(
                """SELECT expected_fields, derived_constraints,
                          compiled_constraints, consumed_constraints,
                          verified_constraints, unsupported_constraints, silent_drops
                   FROM constraint_coverage WHERE revision_id = $1""",
                revision_id,
            )
        return ConstraintGraph(
            revision_id=str(revision_id),
            constraints=[
                Constraint(
                    id=str(row["id"]),
                    type=str(row["type"]),
                    severity=cast(
                        Literal["critical", "required", "advisory"], str(row["severity"])
                    ),
                    scope=str(row["scope"]),
                    source_revision_id=str(revision_id),
                    source_path=str(row["source_path"] or ""),
                    payload=dict(row["payload"] or {}),
                    compile_required=bool(row["compile_required"]),
                    verification_required=bool(row["verification_required"]),
                    fallback_policy=cast(
                        Literal["fail", "degrade", "warn"], str(row["fallback_policy"])
                    ),
                    depends_on_ids=[
                        str(item["depends_on_id"])
                        for item in dependency_rows
                        if str(item["constraint_id"]) == str(row["id"])
                    ],
                )
                for row in rows
            ],
            coverage=CoverageReport(
                **(
                    dict(coverage)
                    if coverage is not None
                    else {
                        "derived_constraints": len(rows),
                    }
                )
            ),
        )

    async def record_compilation(
        self,
        revision_id: str,
        *,
        compiled: int,
        consumed: int,
        unsupported: int,
        silent_drops: int,
    ) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE constraint_coverage
                SET compiled_constraints = $2,
                    consumed_constraints = $3,
                    unsupported_constraints = $4,
                    silent_drops = $5,
                    updated_at = NOW()
                WHERE revision_id = $1
                """,
                uuid.UUID(revision_id),
                compiled,
                consumed,
                unsupported,
                silent_drops,
            )
        from hevi.monitoring.metrics import constraint_coverage_ratio

        constraint_coverage_ratio.labels(stage="compile").set(
            0.0 if compiled == 0 else consumed / compiled
        )

    async def record_verification(self, revision_id: str, *, verified: int) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE constraint_coverage
                SET verified_constraints = $2, updated_at = NOW()
                WHERE revision_id = $1
                """,
                uuid.UUID(revision_id),
                verified,
            )
            derived = await conn.fetchval(
                "SELECT derived_constraints FROM constraint_coverage WHERE revision_id = $1",
                uuid.UUID(revision_id),
            )
        from hevi.monitoring.metrics import constraint_coverage_ratio

        required = int(derived or 0)
        constraint_coverage_ratio.labels(stage="verify").set(
            1.0 if required == 0 else verified / required
        )


__all__ = ["ConstraintRepository"]
