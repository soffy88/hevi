"""Scheduler service/repository behavior against the production PostgreSQL path."""

from __future__ import annotations

import uuid

import pytest
from obase.persistence import PgPool

from hevi.execution import ResourceSnapshot
from hevi.scheduler.repository import SchedulerRepository
from hevi.scheduler.service import SchedulerService


@pytest.mark.asyncio
async def test_scheduler_leases_and_dispatches_queued_task(pool: PgPool) -> None:
    task_id = uuid.uuid4()
    lease_name = f"coverage-scheduler-{uuid.uuid4().hex}"
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO video_tasks
                (id, topic, duration_archetype, video_provider, audio_provider, status,
                 config_json, created_at, updated_at, queued_at, priority,
                 resource_class, required_vram_mb, expected_cost_usd,
                 progress_pct, total_shots, completed_shots, queue_position)
            VALUES ($1, 'coverage task', '1-5min', 'wan_local', 'edge_tts', 'queued',
                    '{}', NOW(), NOW(), NOW(), 10, 'any', 0, 0, 0, 0, 0, 0)
            """,
            task_id,
        )
    try:
        repository = SchedulerRepository(pool)
        assert await repository.acquire_leader(lease_name, "owner-a", lease_seconds=30)
        assert not await repository.acquire_leader(lease_name, "owner-b", lease_seconds=30)
        service = SchedulerService(repository, owner_id="owner-a", poll_interval=0.001)
        scheduled = await service.run_once()
        assert scheduled == 1
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT scheduled_at, scheduler_score, scheduler_policy_version, scheduler_decision_json "
                "FROM video_tasks WHERE id = $1",
                task_id,
            )
            dispatch = await conn.fetchrow(
                "SELECT task_id, worker_id, policy_version FROM scheduler_dispatches WHERE task_id = $1",
                task_id,
            )
        assert row is not None and row["scheduled_at"] is not None
        assert row["scheduler_score"] is not None
        assert row["scheduler_policy_version"] == 1
        assert row["scheduler_decision_json"]
        assert dispatch is not None and dispatch["task_id"] == task_id
        assert dispatch["worker_id"]
        assert await service.run_once() == 0
        service.stop()
        resources = ResourceSnapshot(
            worker_id="coverage-worker",
            resource_class="any",
            available_vram_mb=0,
            capacity_slots=1,
        )
        assert await repository.schedule_once(resources, candidate_limit=1) == 0
    finally:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM scheduler_dispatches WHERE task_id = $1", task_id)
            await conn.execute("DELETE FROM video_tasks WHERE id = $1", task_id)
            await conn.execute("DELETE FROM scheduler_leases WHERE name = $1", lease_name)
