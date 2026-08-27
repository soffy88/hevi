"""Relational reads and coverage updates for the constraint graph.

P0-A: Added constraint_consumption_receipts table operations
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal, cast

from obase.persistence import PgPool

from .models import (
    Constraint,
    ConstraintConsumptionReceipt,
    ConstraintGraph,
    ConsumptionStage,
    CoverageReport,
)


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

    async def record_consumption_receipt(
        self,
        *,
        production_id: uuid.UUID,
        revision_id: uuid.UUID,
        attempt_id: uuid.UUID,
        constraint_id: str,
        provider_id: str,
        adapter_id: str,
        stage: ConsumptionStage,
        mapping_type: str,
        mapping_path: str,
        payload_hash: str,
        provider_request_id: str | None = None,
    ) -> ConstraintConsumptionReceipt:
        """Insert a new immutable consumption receipt.  UNIQUE(attempt_id, constraint_id, stage, mapping_path)
        guarantees no duplicate consumption records for the same attempt/constraint/stage."""
        receipt_id = str(uuid.uuid4())
        async with self.pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO constraint_consumption_receipts
                   (id, production_id, revision_id, attempt_id, constraint_id,
                    provider_id, adapter_id, stage, mapping_type, mapping_path,
                    payload_hash, provider_request_id, created_at)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, NOW())
                ON CONFLICT (attempt_id, constraint_id, stage, mapping_path)
                DO NOTHING
                RETURNING *""",
                receipt_id,
                production_id,
                revision_id,
                attempt_id,
                constraint_id,
                provider_id,
                adapter_id,
                stage.value,
                mapping_type,
                mapping_path,
                payload_hash,
                provider_request_id,
            )
        return ConstraintConsumptionReceipt(
            id=receipt_id,
            production_id=str(production_id),
            revision_id=str(revision_id),
            attempt_id=str(attempt_id),
            constraint_id=constraint_id,
            provider_id=provider_id,
            adapter_id=adapter_id,
            stage=stage,
            mapping_type=mapping_type,
            mapping_path=mapping_path,
            payload_hash=payload_hash,
            provider_request_id=provider_request_id,
            created_at=datetime.now(UTC).isoformat(),
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
        from hevi.monitoring.metrics import constraint_coverage_ratio

        derived = await conn.fetchval(
            "SELECT derived_constraints FROM constraint_coverage WHERE revision_id = $1",
            uuid.UUID(revision_id),
        )
        required = int(derived or 0)
        constraint_coverage_ratio.labels(stage="verify").set(
            1.0 if required == 0 else verified / required
        )

    async def get_consumption_coverage(
        self,
        production_id: str,
        revision_id: str | None = None,
        attempt_id: str | None = None,
    ) -> dict[str, Any]:
        """Query granular consumption coverage across attempts.

        Returns dict with:
        - compiled_constraints / derived_constraints
        - adapter_consumed_constraints / compiled_constraints
        - provider_submitted_constraints / adapter_consumed_constraints
        - verified_constraints / provider_submitted_constraints
        - silent_drop_rate
        - breakdown by stage
        """
        async with self.pool.acquire() as conn:
            sql = """
                SELECT COUNT(DISTINCT constraint_id) FILTER (WHERE stage = 'compiled') as compiled,
                       COUNT(DISTINCT constraint_id) FILTER (WHERE stage = 'adapter_consumed') as adapter_consumed,
                       COUNT(DISTINCT constraint_id) FILTER (WHERE stage = 'provider_submitted') as provider_submitted,
                       COUNT(DISTINCT constraint_id) FILTER (WHERE stage = 'provider_acked') as provider_acked,
                       COUNT(DISTINCT constraint_id) as total_constraints
                FROM constraint_consumption_receipts
                WHERE production_id = $1
            """
            params = [uuid.UUID(production_id)]
            param_idx = 2
            if revision_id:
                sql += f" AND revision_id = ${param_idx}"
                params.append(uuid.UUID(revision_id))
                param_idx += 1
            if attempt_id:
                sql += f" AND attempt_id = ${param_idx}"
                params.append(uuid.UUID(attempt_id))
            row = await conn.fetchrow(sql, *params)
            if not row:
                return {
                    "compiled": 0,
                    "adapter_consumed": 0,
                    "provider_submitted": 0,
                    "provider_acked": 0,
                    "total_constraints": 0,
                    "provider_submission_rate": 0.0,
                    "silent_drop_rate": 0.0,
                }
            result = dict(row)
            compiled = int(result.get("compiled") or 0)
            submitted = int(result.get("provider_submitted") or 0)
            result["provider_submission_rate"] = submitted / compiled if compiled else 1.0
            result["silent_drop_rate"] = (
                max(0, compiled - int(result.get("adapter_consumed") or 0)) / compiled
                if compiled
                else 0.0
            )
            return result

    async def record_derived_constraints(self, revision_id: str, expected: int, derived: int) -> None:
        """Set expected_fields and derived_constraints on coverage."""
        async with self.pool.acquire() as conn:
            await conn.execute(
                """UPDATE constraint_coverage
                   SET expected_fields = $2, derived_constraints = $3, updated_at = NOW()
                   WHERE revision_id = $1""",
                uuid.UUID(revision_id),
                expected,
                derived,
            )


__all__ = ["ConstraintRepository"]
