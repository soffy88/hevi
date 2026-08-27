"""PostgreSQL repository for the canonical director Production Graph.

This is intentionally implemented against the project's async ``PgPool``
boundary rather than SQLAlchemy sessions.  The production API and task
repository already use this pool, so writes can share one transaction with the
outbox/queue work as the migration progresses.
"""

from __future__ import annotations

import json
import uuid
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any, cast

from obase.persistence import PgPool

from hevi.constraints.models import ConstraintGraph
from hevi.execution.plan import ExecutionPlan as ImmutableExecutionPlan
from hevi.execution.repository import ExecutionPlanRepository
from hevi.production_graph.contracts import ExecutionPlan as LegacyExecutionPlan


def _uuid(value: str | uuid.UUID) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def _json_snapshot(record: dict[str, Any]) -> dict[str, Any]:
    """Return JSON-safe data without mutating the API's live projection."""

    return cast(
        dict[str, Any],
        json.loads(json.dumps(record, ensure_ascii=False, default=str)),
    )


def _restore_datetime(record: dict[str, Any]) -> dict[str, Any]:
    value = record.get("created_at")
    if isinstance(value, str):
        with suppress(ValueError):
            record["created_at"] = datetime.fromisoformat(value)
    return record


class ProductionGraphRepository:
    """Durable CRUD for Production, immutable Revision and Stage Lock."""

    def __init__(self, pool: PgPool) -> None:
        self.pool = pool

    async def create(self, record: dict[str, Any]) -> dict[str, Any]:
        """Create the first revision, or append one if the id already exists."""

        return await self.save(record, reason="created")

    async def get(self, work_id: str) -> dict[str, Any] | None:
        production_id = _uuid(work_id)
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT r.snapshot_json
                FROM productions p
                JOIN production_revisions r ON r.id = p.active_revision_id
                WHERE p.id = $1
                """,
                production_id,
            )
        if row is None:
            return None
        raw = row["snapshot_json"]
        snapshot = json.loads(raw) if isinstance(raw, str) else dict(raw)
        return _restore_datetime(snapshot)

    async def list_for_user(self, user_id: str) -> list[dict[str, Any]]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT r.snapshot_json
                FROM productions p
                JOIN production_revisions r ON r.id = p.active_revision_id
                WHERE p.user_id = $1
                ORDER BY p.created_at DESC
                """,
                user_id,
            )
        records: list[dict[str, Any]] = []
        for row in rows:
            raw = row["snapshot_json"]
            snapshot = json.loads(raw) if isinstance(raw, str) else dict(raw)
            records.append(_restore_datetime(snapshot))
        return records

    async def save_execution_plan(
        self, plan: ImmutableExecutionPlan | LegacyExecutionPlan
    ) -> ImmutableExecutionPlan:
        """Persist the canonical immutable plan through the production path.

        The legacy DAG contract is accepted at this boundary for old API
        callers, but it is converted once and never written with the removed
        mutable ``status``/``execution_nodes`` schema.
        """

        if isinstance(plan, ImmutableExecutionPlan):
            canonical = plan
        else:
            plan.validate_dag()
            canonical = ImmutableExecutionPlan.create(
                str(plan.production_id),
                str(plan.revision_id),
                plan.model_dump(mode="json"),
                plan_version=plan.plan_version,
            )
        return await ExecutionPlanRepository(self.pool).save(canonical)

    async def save(
        self,
        record: dict[str, Any],
        *,
        reason: str = "state_changed",
        locked_stage: str | None = None,
        locked_by: str | None = None,
    ) -> dict[str, Any]:
        """Append an immutable revision and advance the active pointer."""

        production_id = _uuid(str(record["work_id"]))
        snapshot = _json_snapshot(record)
        now = datetime.now(UTC).replace(tzinfo=None)
        revision_id = uuid.uuid4()
        snapshot["revision_id"] = str(revision_id)
        if isinstance(snapshot.get("constraint_graph"), dict):
            snapshot["constraint_graph"]["revision_id"] = str(revision_id)
        config = snapshot.get("production_config") or {}
        budget = {
            "season_budget_usd": config.get("season_budget_usd"),
            "estimated_cost_usd": snapshot.get("estimated_cost_usd", 0.0),
        }
        async with self.pool.acquire() as conn, conn.transaction():
            current = await conn.fetchrow(
                """
                    SELECT active_revision_id,
                           COALESCE((SELECT MAX(revision_no)
                                     FROM production_revisions
                                     WHERE production_id = $1), 0) AS revision_no
                    FROM productions
                    WHERE id = $1
                    FOR UPDATE
                    """,
                production_id,
            )
            if current is None:
                await conn.execute(
                    """
                        INSERT INTO productions
                            (id, user_id, type, status, quality_profile, budget,
                             active_revision_id, created_at, updated_at)
                        VALUES ($1, $2, $3, $4, $5, $6, NULL, $7, $7)
                        """,
                    production_id,
                    str(snapshot.get("user_id") or ""),
                    str(snapshot.get("type") or snapshot.get("production_source") or "production"),
                    str(snapshot.get("status") or "draft"),
                    str(config.get("quality_profile") or "standard"),
                    budget,
                    now,
                )
                revision_no = 0
                parent_id = None
            else:
                revision_no = int(current["revision_no"])
                parent_id = current["active_revision_id"]
            revision_no += 1
            await conn.execute(
                """
                    INSERT INTO production_revisions
                        (id, production_id, parent_id, revision_no, status,
                         reason, created_by, snapshot_json, created_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                    """,
                revision_id,
                production_id,
                parent_id,
                revision_no,
                str(snapshot.get("status") or "draft"),
                reason,
                str(snapshot.get("user_id") or ""),
                snapshot,
                now,
            )
            await self._upsert_documents(conn, revision_id, snapshot)
            await self._upsert_constraint_graph(
                conn,
                production_id=production_id,
                revision_id=revision_id,
                raw_graph=snapshot.get("constraint_graph"),
            )
            await conn.execute(
                """
                    UPDATE productions
                    SET status = $2, budget = $3, active_revision_id = $4, updated_at = $5
                    WHERE id = $1
                    """,
                production_id,
                str(snapshot.get("status") or "draft"),
                budget,
                revision_id,
                now,
            )
            if locked_stage is not None:
                await conn.execute(
                    """
                        INSERT INTO stage_locks
                            (production_id, stage, revision_id, locked_by, locked_at)
                        VALUES ($1, $2, $3, $4, $5)
                        ON CONFLICT (production_id, stage) DO UPDATE SET
                            revision_id = EXCLUDED.revision_id,
                            locked_by = EXCLUDED.locked_by,
                            locked_at = EXCLUDED.locked_at
                        """,
                    production_id,
                    locked_stage,
                    revision_id,
                    locked_by or str(snapshot.get("user_id") or ""),
                    now,
                )
            # The event is part of the same transaction as the immutable
            # revision and active pointer.  A publisher may fail or restart,
            # but it cannot observe a state transition without its event.
            event_type = reason if "." in reason else f"production.{reason}"
            await conn.execute(
                """
                INSERT INTO domain_events
                    (id, aggregate_type, aggregate_id, event_type,
                     schema_version, payload, created_at)
                VALUES ($1, 'production', $2, $3, 1, $4, $5)
                """,
                uuid.uuid4(),
                production_id,
                event_type,
                {
                    "revision_id": str(revision_id),
                    "revision_no": revision_no,
                    "reason": reason,
                    "status": snapshot.get("status"),
                    "locked_stage": locked_stage,
                },
                now,
            )
        record["revision_id"] = str(revision_id)
        if isinstance(record.get("constraint_graph"), dict):
            record["constraint_graph"]["revision_id"] = str(revision_id)
        return record

    @staticmethod
    async def _upsert_documents(
        conn: Any, revision_id: uuid.UUID, snapshot: dict[str, Any]
    ) -> None:
        for kind in ("concept", "screenplay", "design_list", "scene_stage", "shot_list"):
            content = snapshot.get(kind)
            if content is None:
                continue
            digest = (
                __import__("hashlib")
                .sha256(
                    json.dumps(content, sort_keys=True, ensure_ascii=False, default=str).encode()
                )
                .hexdigest()
            )
            await conn.execute(
                """
                INSERT INTO director_documents
                    (revision_id, kind, schema_version, content_json, content_hash)
                VALUES ($1, $2, 1, $3, $4)
                ON CONFLICT (revision_id, kind) DO UPDATE SET
                    content_json = EXCLUDED.content_json,
                    content_hash = EXCLUDED.content_hash
                """,
                revision_id,
                kind,
                content,
                digest,
            )

    @staticmethod
    async def _upsert_constraint_graph(
        conn: Any,
        *,
        production_id: uuid.UUID,
        revision_id: uuid.UUID,
        raw_graph: Any,
    ) -> None:
        """Persist the graph as queryable rows alongside the revision.

        The JSON snapshot remains useful for exact replay, but dashboards and
        provider audits query these rows instead of parsing arbitrary JSON.
        """

        if not raw_graph:
            return
        graph = ConstraintGraph.model_validate(raw_graph)
        constraint_ids = [constraint.id for constraint in graph.constraints]
        await conn.execute(
            "DELETE FROM production_constraints "
            "WHERE revision_id = $1 AND NOT (id = ANY($2::text[]))",
            revision_id,
            constraint_ids,
        )
        await conn.execute(
            "DELETE FROM constraint_dependencies WHERE revision_id = $1",
            revision_id,
        )
        for constraint in graph.constraints:
            await conn.execute(
                """
                INSERT INTO production_constraints
                    (id, production_id, revision_id, type, severity, scope,
                     source_path, payload, compile_required, verification_required,
                     fallback_policy, created_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, NOW())
                ON CONFLICT (revision_id, id) DO UPDATE SET
                    type = EXCLUDED.type,
                    severity = EXCLUDED.severity,
                    scope = EXCLUDED.scope,
                    source_path = EXCLUDED.source_path,
                    payload = EXCLUDED.payload,
                    compile_required = EXCLUDED.compile_required,
                    verification_required = EXCLUDED.verification_required,
                    fallback_policy = EXCLUDED.fallback_policy
                """,
                constraint.id,
                production_id,
                revision_id,
                constraint.type,
                constraint.severity,
                constraint.scope,
                constraint.source_path,
                constraint.payload,
                constraint.compile_required,
                constraint.verification_required,
                constraint.fallback_policy,
            )
            for depends_on_id in constraint.depends_on_ids:
                await conn.execute(
                    """
                    INSERT INTO constraint_dependencies
                        (revision_id, constraint_id, depends_on_revision_id, depends_on_id)
                    VALUES ($1, $2, $1, $3)
                    ON CONFLICT DO NOTHING
                    """,
                    revision_id,
                    constraint.id,
                    depends_on_id,
                )
        coverage = graph.coverage
        await conn.execute(
            """
            INSERT INTO constraint_coverage
                (revision_id, expected_fields, derived_constraints,
                 compiled_constraints, consumed_constraints, verified_constraints,
                 unsupported_constraints, silent_drops, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW())
            ON CONFLICT (revision_id) DO UPDATE SET
                expected_fields = EXCLUDED.expected_fields,
                derived_constraints = EXCLUDED.derived_constraints,
                compiled_constraints = EXCLUDED.compiled_constraints,
                consumed_constraints = EXCLUDED.consumed_constraints,
                verified_constraints = EXCLUDED.verified_constraints,
                unsupported_constraints = EXCLUDED.unsupported_constraints,
                silent_drops = EXCLUDED.silent_drops,
                updated_at = NOW()
            """,
            revision_id,
            coverage.expected_fields,
            coverage.derived_constraints,
            coverage.compiled_constraints,
            coverage.adapter_consumed_constraints,
            coverage.verified_constraints,
            coverage.unsupported_constraints,
            coverage.silent_drops,
        )


__all__ = ["ProductionGraphRepository"]
