"""P0-E: immutable execution-plan versions against PostgreSQL."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from typing import Any

import pytest
from obase.persistence import PgPool

from hevi.execution.plan import ExecutionPlan, ImmutablePlanViolation
from hevi.execution.repository import ExecutionPlanRepository
from hevi.production_graph.repository import ProductionGraphRepository


@dataclass
class _PlanContext:
    production_id: uuid.UUID
    revision_id: uuid.UUID


@pytest.fixture
async def plan_context(pool: PgPool) -> _PlanContext:
    production_id = uuid.uuid4()
    record = await ProductionGraphRepository(pool).create(
        {
            "work_id": str(production_id),
            "user_id": "p0e-integration",
            "type": "p0e",
            "status": "draft",
        }
    )
    context = _PlanContext(production_id, uuid.UUID(str(record["revision_id"])))
    yield context
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM execution_plans WHERE production_id = $1", production_id)
        await conn.execute("DELETE FROM productions WHERE id = $1", production_id)


def _plan(context: _PlanContext, plan_json: dict[str, Any], version: int = 1) -> ExecutionPlan:
    return ExecutionPlan.create(
        str(context.production_id),
        str(context.revision_id),
        plan_json,
        plan_version=version,
    )


@pytest.mark.asyncio
async def test_p0e_e1_insert_version_one(pool: PgPool, plan_context: _PlanContext) -> None:
    plan = _plan(plan_context, {"version": 1, "plan": "A"})
    saved = await ExecutionPlanRepository(pool).save(plan)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, production_id, revision_id, plan_version, plan_json, plan_hash,
                   parent_plan_id, created_by_attempt_id, change_reason
            FROM execution_plans
            WHERE production_id = $1 AND revision_id = $2 AND plan_version = 1
            """,
            plan_context.production_id,
            plan_context.revision_id,
        )
    assert row is not None
    assert str(row["id"]) == saved.id == plan.id
    assert row["plan_json"] == plan.plan_json
    assert row["plan_hash"] == plan.plan_hash
    assert row["parent_plan_id"] is None
    assert row["change_reason"] == "initial"


@pytest.mark.asyncio
async def test_p0e_e2_same_key_same_plan_is_idempotent(
    pool: PgPool, plan_context: _PlanContext
) -> None:
    repository = ExecutionPlanRepository(pool)
    plan = _plan(plan_context, {"version": 1, "plan": "A"})
    first = await repository.save(plan)
    async with pool.acquire() as conn:
        before = await conn.fetchrow(
            """
            SELECT COUNT(*) AS count,
                   MIN(created_at) AS created_at,
                   MIN(plan_json::text)::jsonb AS plan_json,
                   MIN(plan_hash) AS plan_hash
            FROM execution_plans WHERE production_id = $1
            """,
            plan_context.production_id,
        )
    second = await repository.save(_plan(plan_context, plan.plan_json))
    async with pool.acquire() as conn:
        after = await conn.fetchrow(
            """
            SELECT COUNT(*) AS count,
                   MIN(created_at) AS created_at,
                   MIN(plan_json::text)::jsonb AS plan_json,
                   MIN(plan_hash) AS plan_hash
            FROM execution_plans WHERE production_id = $1
            """,
            plan_context.production_id,
        )
    assert first.id == second.id
    assert after == before


@pytest.mark.asyncio
async def test_p0e_e3_same_key_different_plan_raises_immutable_violation(
    pool: PgPool, plan_context: _PlanContext
) -> None:
    repository = ExecutionPlanRepository(pool)
    await repository.save(_plan(plan_context, {"version": 1, "plan": "A"}))
    with pytest.raises(ImmutablePlanViolation):
        await repository.save(_plan(plan_context, {"version": 1, "plan": "B"}))
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT plan_json, plan_hash FROM execution_plans WHERE production_id = $1",
            plan_context.production_id,
        )
    assert len(rows) == 1
    assert rows[0]["plan_json"] == {"version": 1, "plan": "A"}
    assert rows[0]["plan_hash"] == _plan(
        plan_context, {"version": 1, "plan": "A"}
    ).plan_hash


def test_p0e_e4_canonical_hash_is_key_order_independent() -> None:
    production_id = str(uuid.uuid4())
    revision_id = str(uuid.uuid4())
    left = ExecutionPlan.create(
        production_id, revision_id, {"a": 1, "b": {"x": 2, "y": 3}}
    )
    right = ExecutionPlan.create(
        production_id, revision_id, {"b": {"y": 3, "x": 2}, "a": 1}
    )
    assert left.plan_hash == right.plan_hash


def test_p0e_e5_from_existing_creates_v2_without_mutating_v1() -> None:
    production_id = str(uuid.uuid4())
    revision_id = str(uuid.uuid4())
    v1 = ExecutionPlan.create(production_id, revision_id, {"plan": "A"})
    original = v1.model_copy(deep=True)
    v2 = ExecutionPlan.from_existing(v1, {"plan": "B"}, change_reason="repair")
    assert v2.plan_version == 2
    assert v2.parent_plan_id == v1.id
    assert v2.change_reason == "repair"
    assert v1 == original


@pytest.mark.asyncio
async def test_p0e_e6_concurrent_v2_creation_has_one_row(
    pool: PgPool, plan_context: _PlanContext
) -> None:
    repository = ExecutionPlanRepository(pool)
    v1 = await repository.save(_plan(plan_context, {"plan": "A"}))
    plans = [ExecutionPlan.from_existing(v1, {"plan": "B"}) for _ in range(2)]

    async def create_v2(plan: ExecutionPlan) -> str:
        saved = await repository.save(plan)
        return "created" if saved.id == plan.id else "existing"

    results = await asyncio.gather(*(create_v2(plan) for plan in plans))
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, parent_plan_id, plan_hash
            FROM execution_plans
            WHERE production_id = $1 AND revision_id = $2 AND plan_version = 2
            """,
            plan_context.production_id,
            plan_context.revision_id,
        )
    assert len(rows) == 1
    assert rows[0]["parent_plan_id"] == uuid.UUID(v1.id)
    assert sum(item == "created" for item in results) == 1
    assert sum(item == "existing" for item in results) == 1
