"""Generic production revision invariant (BLENDER_PRODUCTION_REVISION_FK_CLOSURE).

No Blender-specific DB hacks: the invariant lives in TaskService +
ProductionGraphRepository and applies to every adapter.  All PG-backed tests
are skipped when PostgreSQL is unreachable.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from hevi.production.adapters import ProductionAdapterRegistry
from hevi.production.artifacts import ArtifactManifest
from hevi.tasks.task_service import TaskService

pytestmark = pytest.mark.asyncio


async def _pg_pool():
    try:
        from hevi.db.pg_pool import get_hevi_pg_pool

        pool = await get_hevi_pg_pool()
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        return pool
    except Exception:
        pytest.skip("PostgreSQL unreachable")


async def _make_pg_task(repo, production_id: str, revision_id: str, source: str):
    task_id = uuid.uuid4()
    return await repo.create_task(
        {
            "id": task_id,
            "topic": "revision_invariant",
            "user_id": "invariant_test",
            "idempotency_key": str(uuid.uuid4()),
            "duration_archetype": "rendering",
            "video_provider": source,
            "audio_provider": "none",
            "status": "pending",
            "progress_pct": 0.0,
            "total_shots": 0,
            "completed_shots": 0,
            "priority": 0,
            "deadline_at": None,
            "resource_class": "any",
            "required_vram_mb": 0,
            "expected_cost_usd": 0.0,
            "tenant_weight": 1.0,
            "warm_provider": "false",
            "created_at": __import__("datetime").datetime.now(__import__("datetime").UTC).replace(tzinfo=None),
            "updated_at": __import__("datetime").datetime.now(__import__("datetime").UTC).replace(tzinfo=None),
            "config_json": {
                "production_id": production_id,
                "revision_id": revision_id,
                "production_source": source,
            },
        }
    )


async def test_ensure_creates_graph_and_revision_when_missing():
    pool = await _pg_pool()
    from hevi.production_graph.repository import ProductionGraphRepository

    repo = ProductionGraphRepository(pool)
    work_id = str(uuid.uuid4())
    ctx = await repo.ensure_execution_context(
        {"work_id": work_id, "user_id": "t", "type": "task", "status": "draft"},
        reason="task_execution",
    )
    assert ctx["production_id"] == work_id
    assert await repo.revision_exists(ctx["revision_id"])
    assert ctx["reused"] is False


async def test_ensure_reuses_existing_revision():
    pool = await _pg_pool()
    from hevi.production_graph.repository import ProductionGraphRepository

    repo = ProductionGraphRepository(pool)
    work_id = str(uuid.uuid4())
    first = await repo.ensure_execution_context(
        {"work_id": work_id, "user_id": "t", "type": "task", "status": "draft"},
        reason="task_execution",
    )
    second = await repo.ensure_execution_context(
        {"work_id": work_id, "user_id": "t", "type": "task", "status": "draft"},
        reason="task_execution",
    )
    assert second["revision_id"] == first["revision_id"]
    assert second["reused"] is True


async def test_ensure_repairs_missing_revision_for_existing_graph():
    pool = await _pg_pool()
    from hevi.production_graph.repository import ProductionGraphRepository

    repo = ProductionGraphRepository(pool)
    work_id = str(uuid.uuid4())
    ctx = await repo.ensure_execution_context(
        {"work_id": work_id, "user_id": "t", "type": "task", "status": "draft"},
        reason="task_execution",
    )
    # Orphan the graph: drop the revision row so get() finds no active revision.
    orphan = ctx["revision_id"]
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE productions SET active_revision_id = NULL WHERE id = $1",
            uuid.UUID(work_id),
        )
        await conn.execute("DELETE FROM production_revisions WHERE id = $1", uuid.UUID(orphan))
    assert not await repo.revision_exists(orphan)
    repaired = await repo.ensure_execution_context(
        {"work_id": work_id, "user_id": "t", "type": "task", "status": "draft"},
        reason="task_execution",
    )
    assert repaired["revision_id"] != orphan
    assert await repo.revision_exists(repaired["revision_id"])


async def test_stale_config_revision_not_trusted(tmp_path):
    pool = await _pg_pool()
    from hevi.tasks.repository import TaskRepository

    repo = TaskRepository(pool)
    production_id = str(uuid.uuid4())
    stale_revision = str(uuid.uuid4())  # never inserted anywhere
    task = await _make_pg_task(repo, production_id, stale_revision, "mpt")
    service = TaskService(repo)
    ctx = await service._ensure_production_graph(task)
    assert ctx["revision_id"] != stale_revision
    assert task["config_json"]["revision_id"] == ctx["revision_id"]
    assert task["_canonical_revision_id"] == ctx["revision_id"]
    from hevi.production_graph.repository import ProductionGraphRepository

    assert await ProductionGraphRepository(pool).revision_exists(ctx["revision_id"])


async def test_record_quality_repair_rejects_stale_revision_explicitly():
    pool = await _pg_pool()
    from hevi.tasks.repository import TaskRepository

    repo = TaskRepository(pool)
    production_id = str(uuid.uuid4())
    task = await _make_pg_task(repo, production_id, str(uuid.uuid4()), "mpt")
    service = TaskService(repo)
    # Deliberately skip _ensure_production_graph: stale id must fail closed
    # with an explicit error, never an asyncpg FK IntegrityError.
    with pytest.raises(RuntimeError, match="PRODUCTION_REVISION_MISSING"):
        await service._record_quality_repair(task, None)


async def test_non_blender_adapter_regression_pg(tmp_path):
    """Generic regression: a non-Blender adapter persists quality repair (FK=0)."""
    pool = await _pg_pool()
    from hevi.tasks.repository import TaskRepository

    out = tmp_path / "nb.png"
    out.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 100)
    repo = TaskRepository(pool)
    adapters = ProductionAdapterRegistry()

    async def fake_nb(task, pool):
        return {
            **task,
            "status": "completed",
            "result_video_path": str(out),
            "config_json": {
                **task["config_json"],
                "artifact_manifest": ArtifactManifest(
                    artifacts=[{"kind": "image", "path": str(out), "primary": True}]
                ).model_dump(mode="json"),
            },
            "review_pending": False,
            "artifacts": [],
            "report": {"legacy_result": {"result_video_path": str(out)}},
        }

    adapters.register("mpt", fake_nb, replace=True)
    from hevi.core.config import settings as _settings

    _prev_local = _settings.local_mode
    _settings.local_mode = True
    service = TaskService(repo, production_adapters=adapters)
    production_id = str(uuid.uuid4())
    task = await _make_pg_task(repo, production_id, production_id, "mpt")
    try:
        result = await service._run_adapter_task(task)
    finally:
        _settings.local_mode = _prev_local
    assert result["status"] == "completed"
    assert result["config_json"]["repair_decision"]


async def test_blender_dispatch_still_bypasses_provider_policy():
    repo = MagicMock()
    repo.pool = MagicMock()
    repo.update_task = AsyncMock()
    adapters = ProductionAdapterRegistry()

    async def fake_blender(task, pool):
        return {**task, "status": "completed"}

    adapters.register("blender_previz", fake_blender)
    service = TaskService(repo, production_adapters=adapters)
    from unittest.mock import patch

    with patch(
        "hevi.tasks.task_service.TaskService._apply_provider_policy",
        new_callable=AsyncMock,
    ) as policy:
        await service._run_adapter_task(
            {"id": uuid.uuid4(), "config_json": {"production_source": "blender_previz"}}
        )
    policy.assert_not_called()
