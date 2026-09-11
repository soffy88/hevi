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
from hevi.production_graph.domain import (
    ProductionGraphSnapshot,
    ProductionProject,
    ProductionRevision,
)


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

    def __init__(self, pool: PgPool | None = None) -> None:
        self.pool = pool
        self._memory_records: dict[str, ProductionGraphSnapshot] = {}
        self._memory_revisions: dict[tuple[str, str], ProductionGraphSnapshot] = {}
        self._memory_runs: dict[str, dict[str, Any]] = {}
        self._memory_workbench: dict[tuple[str, str, str], dict[str, Any]] = {}

    async def save_workbench_record(
        self, project_id: str, entity_type: str, record: dict[str, Any]
    ) -> dict[str, Any]:
        """Persist a P1 control record in the existing graph entity store."""

        entity_id = str(record["id"])
        stored = _json_snapshot(record)
        self._memory_workbench[(project_id, entity_type, entity_id)] = stored
        if self.pool is None:
            return _json_snapshot(stored)
        snapshot = await self.get_snapshot(project_id)
        if snapshot is None:
            raise ValueError("unknown production project")
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO production_graph_entities
                    (project_id, revision_id, entity_type, entity_id, payload)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (revision_id, entity_type, entity_id)
                DO UPDATE SET payload = EXCLUDED.payload
                """,
                _uuid(project_id),
                _uuid(snapshot.revision.id),
                entity_type,
                entity_id,
                stored,
            )
        return _json_snapshot(stored)

    async def list_workbench_records(
        self, project_id: str, entity_type: str
    ) -> list[dict[str, Any]]:
        if self.pool is None:
            return [
                _json_snapshot(record)
                for (stored_project, stored_type, _), record in self._memory_workbench.items()
                if stored_project == project_id and stored_type == entity_type
            ]
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT DISTINCT ON (entity_id) payload
                FROM production_graph_entities
                WHERE project_id = $1 AND entity_type = $2
                ORDER BY entity_id, revision_id DESC
                """,
                _uuid(project_id),
                entity_type,
            )
        return [_json_snapshot(dict(row["payload"])) for row in rows]

    async def create_project(self, project: ProductionProject) -> ProductionGraphSnapshot:
        """Create a project and its first immutable revision.

        ``pool=None`` is an intentional deterministic repository for unit and
        local architecture tests.  Production callers pass the existing
        PostgreSQL pool and use the same ``productions``/
        ``production_revisions`` tables as the RC6 graph repository.
        """

        revision = ProductionRevision(project_id=project.id, revision_no=1, reason="created")
        project_with_revision = project.model_copy(update={"current_revision_id": revision.id})
        snapshot = ProductionGraphSnapshot(project=project_with_revision, revision=revision)
        snapshot.validate_referential_integrity()
        await self.save_snapshot(snapshot)
        return snapshot

    async def save_snapshot(self, snapshot: ProductionGraphSnapshot) -> ProductionGraphSnapshot:
        """Persist an immutable canonical snapshot without changing its IDs."""

        snapshot.validate_referential_integrity()
        project_id = snapshot.project.id
        previous = self._memory_records.get(project_id)
        if previous is not None and previous.revision.id == snapshot.revision.id:
            return previous
        if previous is not None:
            if previous.project.current_revision_id != snapshot.revision.parent_revision_id:
                raise ValueError("canonical revision parent is not the active revision")
            if snapshot.revision.revision_no <= previous.revision.revision_no:
                raise ValueError("canonical revision number must increase")
        stored = snapshot.model_copy(deep=True)
        self._memory_records[project_id] = stored
        self._memory_revisions[(project_id, snapshot.revision.id)] = stored
        if self.pool is None:
            return snapshot

        record = snapshot.model_dump(mode="json")
        now = datetime.now(UTC).replace(tzinfo=None)
        production_id = _uuid(project_id)
        revision_id = _uuid(snapshot.revision.id)
        parent_id = (
            _uuid(snapshot.revision.parent_revision_id)
            if snapshot.revision.parent_revision_id
            else None
        )
        async with self.pool.acquire() as conn, conn.transaction():
            await conn.execute(
                """
                INSERT INTO productions
                    (id, user_id, type, status, quality_profile, budget,
                     active_revision_id, created_at, updated_at)
                VALUES ($1, $2, 'canonical_production', $3, 'standard', $4, NULL, $5, $5)
                ON CONFLICT (id) DO UPDATE SET
                    user_id = EXCLUDED.user_id,
                    status = EXCLUDED.status,
                    budget = EXCLUDED.budget,
                    updated_at = EXCLUDED.updated_at
                """,
                production_id,
                snapshot.project.user_id,
                snapshot.project.status.value,
                snapshot.project.budget_policy,
                now,
            )
            await conn.execute(
                """
                INSERT INTO production_revisions
                    (id, production_id, parent_id, revision_no, status,
                     reason, created_by, snapshot_json, created_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                ON CONFLICT (id) DO NOTHING
                """,
                revision_id,
                production_id,
                parent_id,
                snapshot.revision.revision_no,
                snapshot.project.status.value,
                snapshot.revision.reason,
                snapshot.revision.actor,
                {"canonical_graph": record},
                now,
            )
            await _persist_canonical_indexes(conn, snapshot, production_id, revision_id)
            await conn.execute(
                """
                INSERT INTO domain_events
                    (id, aggregate_type, aggregate_id, event_type,
                     schema_version, payload, created_at)
                VALUES ($1, 'production', $2, 'production.canonical_revision.created', 1, $3, $4)
                ON CONFLICT DO NOTHING
                """,
                uuid.uuid4(),
                production_id,
                {"revision_id": str(revision_id), "revision_no": snapshot.revision.revision_no},
                now,
            )
            await conn.execute(
                "UPDATE productions SET active_revision_id = $2, updated_at = $3 WHERE id = $1",
                production_id,
                revision_id,
                now,
            )
        return snapshot

    async def get_snapshot(
        self, project_id: str, *, revision_id: str | None = None
    ) -> ProductionGraphSnapshot | None:
        """Load a canonical revision, preserving exact immutable JSON."""

        current = self._memory_records.get(project_id)
        if self.pool is None:
            selected = (
                self._memory_revisions.get((project_id, revision_id))
                if revision_id is not None
                else current
            )
            return selected.model_copy(deep=True) if selected else None
        async with self.pool.acquire() as conn:
            if revision_id is None:
                row = await conn.fetchrow(
                    """
                    SELECT r.snapshot_json
                    FROM productions p
                    JOIN production_revisions r ON r.id = p.active_revision_id
                    WHERE p.id = $1
                    """,
                    _uuid(project_id),
                )
            else:
                row = await conn.fetchrow(
                    """
                    SELECT snapshot_json FROM production_revisions
                    WHERE production_id = $1 AND id = $2
                    """,
                    _uuid(project_id),
                    _uuid(revision_id),
                )
        if row is None:
            return None
        raw = row["snapshot_json"]
        payload = json.loads(raw) if isinstance(raw, str) else dict(raw)
        graph = payload.get("canonical_graph")
        return ProductionGraphSnapshot.model_validate(graph) if graph else None

    async def project_ids_for_user(self, user_id: str) -> list[str]:
        """List only projects owned by one user for scoped domain reads."""

        if self.pool is None:
            return sorted(
                project_id
                for project_id, snapshot in self._memory_records.items()
                if snapshot.project.user_id == user_id
            )
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT id FROM productions WHERE user_id = $1 ORDER BY created_at, id",
                user_id,
            )
        return [str(row["id"]) for row in rows]

    async def list_revisions(self, project_id: str) -> list[ProductionRevision]:
        """Return immutable revision metadata in ascending revision order."""

        if self.pool is None:
            items = [
                snapshot.revision
                for (stored_project_id, _), snapshot in self._memory_revisions.items()
                if stored_project_id == project_id
            ]
            return sorted(items, key=lambda item: item.revision_no)
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, production_id, parent_id, revision_no, reason,
                       created_by, created_at
                FROM production_revisions
                WHERE production_id = $1
                ORDER BY revision_no, created_at, id
                """,
                _uuid(project_id),
            )
        return [
            ProductionRevision(
                id=str(row["id"]),
                project_id=str(row["production_id"]),
                parent_revision_id=str(row["parent_id"]) if row["parent_id"] else None,
                revision_no=int(row["revision_no"]),
                reason=str(row["reason"] or ""),
                actor=str(row["created_by"] or "system"),
                created_at=(
                    row["created_at"].replace(tzinfo=UTC)
                    if row["created_at"].tzinfo is None
                    else row["created_at"]
                ),
            )
            for row in rows
        ]

    async def save_run(self, run: dict[str, Any]) -> dict[str, Any]:
        """Persist a Slate run projection without process-local API state."""

        run_id = str(run["run_id"])
        stored = _json_snapshot(run)
        self._memory_runs[run_id] = stored
        if self.pool is None:
            return _json_snapshot(stored)
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO production_graph_entities
                    (project_id, revision_id, entity_type, entity_id, payload)
                VALUES ($1, $2, 'production_run', $3, $4)
                ON CONFLICT (revision_id, entity_type, entity_id)
                DO UPDATE SET payload = EXCLUDED.payload
                """,
                _uuid(str(run["project_id"])),
                _uuid(str(run["revision_id"])),
                run_id,
                stored,
            )
        return stored

    async def get_run(self, run_id: str, *, user_id: str) -> dict[str, Any] | None:
        if self.pool is None:
            run = self._memory_runs.get(run_id)
            return _json_snapshot(run) if run and run.get("user_id") == user_id else None
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT payload FROM production_graph_entities
                WHERE entity_type = 'production_run' AND entity_id = $1
                  AND payload->>'user_id' = $2
                LIMIT 1
                """,
                run_id,
                user_id,
            )
        return _json_snapshot(dict(row["payload"])) if row else None

    async def list_runs(self, *, user_id: str) -> list[dict[str, Any]]:
        if self.pool is None:
            return [
                _json_snapshot(run)
                for run in self._memory_runs.values()
                if run.get("user_id") == user_id
            ]
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT payload FROM production_graph_entities
                WHERE entity_type = 'production_run' AND payload->>'user_id' = $1
                ORDER BY entity_id
                """,
                user_id,
            )
        return [_json_snapshot(dict(row["payload"])) for row in rows]

    async def append_revision(
        self,
        snapshot: ProductionGraphSnapshot,
        *,
        actor: str,
        reason: str,
    ) -> ProductionGraphSnapshot:
        """Create a child revision while leaving the parent snapshot intact."""

        current = await self.get_snapshot(snapshot.project.id)
        if current is None:
            raise ValueError("cannot append a revision for an unknown project")
        revision = ProductionRevision(
            project_id=current.project.id,
            parent_revision_id=current.revision.id,
            revision_no=current.revision.revision_no + 1,
            actor=actor,
            reason=reason,
        )
        project = snapshot.project.model_copy(
            update={"current_revision_id": revision.id, "updated_at": datetime.now(UTC)}
        )
        child = snapshot.model_copy(update={"project": project, "revision": revision}, deep=True)
        from hevi.production_graph.revisions import _rebind_revision_ids

        _rebind_revision_ids(child, revision.id)
        child.validate_referential_integrity()
        return await self.save_snapshot(child)

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


async def _persist_canonical_indexes(
    conn: Any,
    snapshot: ProductionGraphSnapshot,
    production_id: uuid.UUID,
    revision_id: uuid.UUID,
) -> None:
    """Index canonical entities without creating a second snapshot authority."""

    fields = (
        "sources",
        "source_chunks",
        "characters",
        "character_states",
        "look_variants",
        "worlds",
        "world_rules",
        "locations",
        "location_states",
        "props",
        "prop_states",
        "seasons",
        "episodes",
        "scenes",
        "beats",
        "shots",
        "keyframes",
        "reference_bundles",
        "continuity_constraints",
        "readiness_results",
        "director_sessions",
        "director_decisions",
        "revision_patches",
        "production_plans",
        "execution_plans",
        "execution_attempts",
        "provenance_links",
        "adaptation_plans",
        "adaptation_decisions",
    )
    for field_name in fields:
        for item in getattr(snapshot, field_name):
            # Readiness is an evaluation record keyed by its shot/revision,
            # not an Entity with its own ``id``.  Keep its persisted identity
            # stable so product orchestration can save a complete snapshot.
            entity_id = item.shot_id if field_name == "readiness_results" else item.id
            await conn.execute(
                """
                INSERT INTO production_graph_entities
                    (project_id, revision_id, entity_type, entity_id, payload)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (revision_id, entity_type, entity_id)
                DO UPDATE SET payload = EXCLUDED.payload
                """,
                production_id,
                revision_id,
                field_name,
                str(entity_id),
                item.model_dump(mode="json"),
            )
    if snapshot.narrative is not None:
        for event in snapshot.narrative.events:
            await conn.execute(
                """
                INSERT INTO production_graph_entities
                    (project_id, revision_id, entity_type, entity_id, payload)
                VALUES ($1, $2, 'narrative_event', $3, $4)
                ON CONFLICT (revision_id, entity_type, entity_id)
                DO UPDATE SET payload = EXCLUDED.payload
                """,
                production_id,
                revision_id,
                event.id,
                event.model_dump(mode="json"),
            )
        for edge in snapshot.narrative.edges:
            await conn.execute(
                """
                INSERT INTO production_graph_edges
                    (project_id, revision_id, edge_id, edge_type, source_id, target_id, payload)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                ON CONFLICT (revision_id, edge_id)
                DO UPDATE SET payload = EXCLUDED.payload
                """,
                production_id,
                revision_id,
                edge.id,
                edge.type.value,
                edge.source_event_id,
                edge.target_event_id,
                edge.model_dump(mode="json"),
            )
    for result in snapshot.readiness_results:
        await conn.execute(
            """
            INSERT INTO production_graph_readiness
                (project_id, revision_id, shot_id, state, passed, blockers, warnings, checks, evaluated_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            ON CONFLICT (revision_id, shot_id)
            DO UPDATE SET state = EXCLUDED.state, passed = EXCLUDED.passed,
                          blockers = EXCLUDED.blockers, warnings = EXCLUDED.warnings,
                          checks = EXCLUDED.checks, evaluated_at = EXCLUDED.evaluated_at
            """,
            production_id,
            revision_id,
            result.shot_id,
            result.state.value,
            result.passed,
            result.blockers,
            result.warnings,
            result.checks,
            result.evaluated_at,
        )


__all__ = ["ProductionGraphRepository"]
