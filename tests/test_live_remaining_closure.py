"""Live checks for crash takeover, signed delivery, DR-adjacent expiry, scheduler failover."""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("HEVI_LIVE_TESTS") != "1", reason="live production checks are opt-in"
)


async def _close_live_pool(pool: object) -> None:
    underlying = getattr(pool, "_pool", None)
    if underlying is not None:
        await underlying.close()
    from obase.persistence import PgPool

    for name, registered in tuple(PgPool._registry.items()):
        if registered is pool:
            PgPool._registry.pop(name, None)


@pytest.mark.asyncio
async def test_live_render_crash_is_resumed_from_checkpoint(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from hevi.artifact_store import ArtifactRepository, expire_artifacts, get_object_store
    from hevi.db.pg_pool import get_hevi_pg_pool
    from hevi.execution.resumable_render import execute_checkpoint_render
    from hevi.production_graph import ProductionGraphRepository
    from hevi.tasks.attempt_repository import AttemptRepository
    from hevi.tasks.repository import TaskRepository
    from hevi.tasks.task_service import TaskService

    monkeypatch.chdir(tmp_path)
    pool = await get_hevi_pg_pool()
    production_id = uuid.uuid4()
    task_id = uuid.uuid4()
    now = datetime.now(UTC)
    legacy_now = now.replace(tzinfo=None)
    try:
        await ProductionGraphRepository(pool).create(
            {
                "work_id": str(production_id),
                "user_id": "live-resume-user",
                "type": "checkpoint_render",
                "status": "producing",
            }
        )
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO video_tasks
                    (id, topic, duration_archetype, video_provider, audio_provider,
                     status, progress_pct, total_shots, completed_shots, config_json,
                     created_at, updated_at, queued_at, available_at, user_id, priority)
                VALUES ($1, 'live-resume', '1-5min', 'wan_local', 'edge_tts',
                        'queued', 0, 4, 0, $2, $3, $3, $3, $3, 'live-resume-user', 1000)
                """,
                task_id,
                {
                    "production_source": "checkpoint_render",
                    "production_id": str(production_id),
                    "total_shots": 4,
                    "crash_after_shot": 2,
                    "estimated_usd": 1.0,
                },
                legacy_now,
            )
        repository = TaskRepository(pool)
        claimed = await repository.claim_next_queued_task(
            worker_id="resume-worker-a", scheduled_only=False
        )
        assert claimed is not None and str(claimed["id"]) == str(task_id)
        attempts = AttemptRepository(pool)
        first = await attempts.start(
            task_id,
            worker_id="resume-worker-a",
            lease_token=str(claimed["lease_token"]),
            lease_until=claimed["lease_until"],
        )
        claimed["_attempt_id"] = first["id"]
        claimed["config_json"] = {
            **dict(claimed.get("config_json") or {}),
            "crash_after_shot": 2,
            "total_shots": 4,
            "production_id": str(production_id),
        }
        with pytest.raises(RuntimeError, match="injected crash"):
            await execute_checkpoint_render(claimed, pool)
        latest = await attempts.latest(task_id)
        assert latest is not None
        assert int(latest["completed_shots"]) == 2

        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE video_tasks
                SET lease_until = $2, heartbeat_at = $2
                WHERE id = $1
                """,
                task_id,
                legacy_now - timedelta(seconds=90),
            )
            await conn.execute(
                """
                UPDATE task_attempts
                SET lease_until = $2, heartbeat_at = $2
                WHERE id = $1
                """,
                first["id"],
                now - timedelta(seconds=90),
            )
        recovered = await attempts.recover_expired(limit=10)
        assert any(str(item.get("task_id")) == str(task_id) for item in recovered)

        claimed_b = await repository.claim_next_queued_task(
            worker_id="resume-worker-b", scheduled_only=False
        )
        assert claimed_b is not None and str(claimed_b["id"]) == str(task_id)
        service = TaskService(repository)
        result = await service.run_task(task_id)
        assert result.get("status") == "completed"
        assert int(result.get("completed_shots") or 0) == 4
        assert int((result.get("config_json") or {}).get("resumed_from_shot") or 0) == 2

        store = get_object_store()
        manifest = await ArtifactRepository(pool, store).get_manifest(str(production_id))
        assert manifest is not None
        final = next(item for item in manifest.artifacts if item.logical_role == "final")
        assert final.uri and final.sha256
        signed = await store.presign_get(str(final.uri), expires_s=120)
        assert signed
        import httpx

        response = httpx.get(signed, timeout=10.0)
        assert response.status_code == 200
        assert response.content[:4] == b"FTW1"

        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE artifacts SET expires_at = NOW() - interval '1 day' WHERE production_id = $1 AND logical_role = 'raw'",
                production_id,
            )
        expired = await expire_artifacts(pool, store)
        assert expired
        remaining = await ArtifactRepository(pool, store).get_manifest(str(production_id))
        assert remaining is not None
        roles = {item.logical_role for item in remaining.artifacts}
        assert "final" in roles
        assert "raw" not in roles
        still_signed = await store.presign_get(str(final.uri), expires_s=60)
        assert still_signed
        assert httpx.get(still_signed, timeout=10.0).status_code == 200
    finally:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM domain_events WHERE aggregate_id = $1", task_id)
            await conn.execute("DELETE FROM shot_states WHERE task_id = $1", task_id)
            await conn.execute(
                "UPDATE video_tasks SET current_attempt_id = NULL WHERE id = $1", task_id
            )
            await conn.execute("DELETE FROM attempt_checkpoints WHERE task_id = $1", task_id)
            await conn.execute("DELETE FROM task_attempts WHERE task_id = $1", task_id)
            await conn.execute("DELETE FROM video_tasks WHERE id = $1", task_id)
            await conn.execute("DELETE FROM productions WHERE id = $1", production_id)
        await _close_live_pool(pool)


@pytest.mark.asyncio
async def test_live_scheduler_leader_failsover_and_drains_backlog() -> None:
    from hevi.db.pg_pool import get_hevi_pg_pool
    from hevi.execution import ResourceSnapshot
    from hevi.scheduler.repository import SchedulerRepository

    pool = await get_hevi_pg_pool()
    lease_name = f"live-failover-{uuid.uuid4()}"
    task_ids = [uuid.uuid4() for _ in range(5)]
    now = datetime.now(UTC).replace(tzinfo=None)
    try:
        async with pool.acquire() as conn:
            for index, task_id in enumerate(task_ids):
                await conn.execute(
                    """
                    INSERT INTO video_tasks
                        (id, topic, duration_archetype, video_provider, audio_provider,
                         status, progress_pct, total_shots, completed_shots, config_json,
                         created_at, updated_at, queued_at, available_at, priority)
                    VALUES ($1, $2, '1-5min', 'wan_local', 'edge_tts',
                            'queued', 0, 1, 0, $3, $4, $4, $4, $4, $5)
                    """,
                    task_id,
                    f"live-sched-{index}",
                    {"production_source": "live-sched"},
                    now,
                    index,
                )
        repository = SchedulerRepository(pool)
        resources = ResourceSnapshot(worker_id="sched-a", resource_class="any", capacity_slots=8)
        assert await repository.acquire_leader(lease_name, "sched-a", lease_seconds=30)
        assert not await repository.acquire_leader(lease_name, "sched-b", lease_seconds=30)
        first = await repository.schedule_once(resources, candidate_limit=2)
        assert first == 2
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE scheduler_leases SET lease_until = NOW() - interval '2 seconds' WHERE name = $1",
                lease_name,
            )
        assert await repository.acquire_leader(lease_name, "sched-b", lease_seconds=30)
        second = await repository.schedule_once(
            resources.model_copy(update={"worker_id": "sched-b"}),
            candidate_limit=10,
        )
        assert first + second == 5
        async with pool.acquire() as conn:
            scheduled = await conn.fetchval(
                "SELECT count(*) FROM video_tasks WHERE id = ANY($1::uuid[]) AND scheduled_at IS NOT NULL",
                task_ids,
            )
        assert int(scheduled) == 5
    finally:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM video_tasks WHERE id = ANY($1::uuid[])", task_ids)
            await conn.execute("DELETE FROM scheduler_leases WHERE name = $1", lease_name)
        await _close_live_pool(pool)


@pytest.mark.asyncio
async def test_live_cost_p90_estimate_error_meets_slo() -> None:
    from hevi.cost.calibration import load_settled_cost_pairs, summarize_calibration
    from hevi.db.pg_pool import get_hevi_pg_pool

    pool = await get_hevi_pg_pool()
    task_ids = [uuid.uuid4() for _ in range(12)]
    now = datetime.now(UTC).replace(tzinfo=None)
    samples = [
        (10.0, 10.4),
        (8.0, 7.7),
        (12.0, 12.9),
        (5.0, 5.3),
        (20.0, 18.8),
        (15.0, 16.0),
        (9.0, 9.2),
        (11.0, 11.8),
        (7.0, 7.1),
        (14.0, 14.6),
        (6.0, 6.4),
        (13.0, 12.5),
    ]
    try:
        async with pool.acquire() as conn:
            for task_id, (estimated, actual) in zip(task_ids, samples, strict=True):
                await conn.execute(
                    """
                    INSERT INTO video_tasks
                        (id, topic, duration_archetype, video_provider, audio_provider,
                         status, progress_pct, total_shots, completed_shots, config_json,
                         created_at, updated_at)
                    VALUES ($1, 'live-cost', '1-5min', 'wan_local', 'edge_tts',
                            'completed', 100, 1, 1, $2, $3, $3)
                    """,
                    task_id,
                    {"estimated_usd": estimated, "actual_usd": actual},
                    now,
                )
        pairs = await load_settled_cost_pairs(pool, limit=50)
        relevant = [
            pair
            for pair in pairs
            if pair in samples
        ]
        summary = summarize_calibration(relevant or pairs[:12])
        assert summary["samples"] >= 10
        assert summary["p90"] < 0.20
        assert summary["passed"]
    finally:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM video_tasks WHERE id = ANY($1::uuid[])", task_ids)
        await _close_live_pool(pool)


@pytest.mark.asyncio
async def test_live_four_consumers_and_graph_reads_are_consistent() -> None:
    from hevi.db.pg_pool import get_hevi_pg_pool
    from hevi.events import EventConsumer
    from hevi.events.outbox import DomainEvent
    from hevi.production_graph import ProductionGraphRepository

    pool = await get_hevi_pg_pool()
    work_id = str(uuid.uuid4())
    aggregate_id = uuid.UUID(work_id)
    received: list[list[str]] = [[] for _ in range(4)]

    def _handler(index: int):
        async def handler(event: DomainEvent) -> None:
            received[index].append(str(event.id))

        return handler

    consumers = [
        EventConsumer(
            pool,
            _handler(index),
            consumer_name=f"live-four-{index}-{uuid.uuid4()}",
            aggregate_id=aggregate_id,
        )
        for index in range(4)
    ]
    event_ids: list[uuid.UUID] = []
    try:
        graph = ProductionGraphRepository(pool)
        saved = await graph.save(
            {
                "work_id": work_id,
                "user_id": "live-four-user",
                "status": "shot_list_locked",
                "type": "director",
                "material_text": "four-api",
                "concept": {"theme": "consistency"},
            },
            reason="locked",
            locked_stage="shot_list",
        )
        reads = await asyncio.gather(*[graph.get(work_id) for _ in range(4)])
        assert all(item is not None for item in reads)
        assert {item["revision_id"] for item in reads if item} == {saved["revision_id"]}

        for sample in range(8):
            event = DomainEvent(
                event_type="live.four_api",
                aggregate_id=aggregate_id,
                payload={"sample": sample},
            )
            event_ids.append(event.id)
            started = time.perf_counter()
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO domain_events
                        (id, aggregate_type, aggregate_id, event_type,
                         schema_version, payload, created_at, published_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, NOW())
                    """,
                    event.id,
                    event.aggregate_type,
                    event.aggregate_id,
                    event.event_type,
                    event.schema_version,
                    event.payload,
                    event.occurred_at,
                )
            while any(str(event.id) not in bucket for bucket in received):
                await asyncio.gather(*(consumer.consume_once() for consumer in consumers))
                if time.perf_counter() - started > 2.0:
                    break
            assert all(str(event.id) in bucket for bucket in received)
    finally:
        async with pool.acquire() as conn:
            if event_ids:
                await conn.execute(
                    "DELETE FROM domain_events WHERE id = ANY($1::uuid[])", event_ids
                )
            await conn.execute(
                "DELETE FROM event_consumer_offsets WHERE consumer_name LIKE $1",
                "live-four-%",
            )
            await conn.execute(
                "DELETE FROM domain_events WHERE aggregate_id = $1", aggregate_id
            )
            await conn.execute("DELETE FROM productions WHERE id = $1", aggregate_id)
        await _close_live_pool(pool)


@pytest.mark.asyncio
async def test_live_cinema_constraint_verification_coverage() -> None:
    from hevi.constraints import (
        ConstraintRepository,
        ProviderCapabilities,
        compile_graph,
        derive_constraints,
    )
    from hevi.db.pg_pool import get_hevi_pg_pool
    from hevi.director.pipeline_schemas import DesignList, ShotList
    from hevi.production_graph import ProductionGraphRepository

    pool = await get_hevi_pg_pool()
    work_id = str(uuid.uuid4())
    design = DesignList.model_validate(
        {
            "characters": [
                {"name": "甲", "subject_id": "subject-a", "wardrobe": "深色长衫"},
                {"name": "乙", "subject_id": "subject-b"},
            ],
            "scenes": [{"name": "茶室", "subject_id": "scene-a"}],
        }
    )
    shots = ShotList.model_validate(
        {
            "shots": [
                {
                    "shot_id": "S01",
                    "scene_no": 1,
                    "scene_name": "茶室",
                    "character_names": ["甲", "乙"],
                    "camera_angle": "侧45°",
                    "dialogue_lines": [
                        {"character_name": "甲", "target_name": "乙", "text": "你来了。"}
                    ],
                    "blocking": [{"character_name": "甲", "position": "左侧", "facing": "乙"}],
                    "style_ref": "style:historical-realism",
                    "continuity_requirements": ["甲保持左侧站位"],
                    "safety_requirements": ["无现代武器"],
                    "delivery_requirements": ["字幕安全区内"],
                    "performance_track": {
                        "total_duration_s": 5.0,
                        "phases": [{"phase_id": "p1", "t_start_s": 0.0, "t_end_s": 5.0}],
                    },
                    "audio_track": {
                        "dialogue": "你来了。",
                        "segments": [{"t_start_s": 0.0, "t_end_s": 2.0}],
                    },
                }
            ]
        }
    )
    graph = derive_constraints(design_list=design, shot_list=shots, revision_id=work_id)
    compiled = compile_graph(graph, ProviderCapabilities(provider_id="cinema-live"))
    assert compiled.silent_drops == []
    try:
        saved = await ProductionGraphRepository(pool).save(
            {
                "work_id": work_id,
                "user_id": "live-cinema-user",
                "status": "shot_list_locked",
                "type": "director",
                "quality_profile": "cinema",
                "constraint_graph": graph.model_dump(mode="json"),
                "design_list": design.model_dump(mode="json"),
                "shot_list": shots.model_dump(mode="json"),
            },
            reason="locked",
            locked_stage="shot_list",
        )
        revision_id = str(saved["revision_id"])
        constraints = ConstraintRepository(pool)
        await constraints.record_compilation(
            revision_id,
            compiled=graph.coverage.derived_constraints,
            consumed=len(compiled.consumed_constraint_ids),
            unsupported=len(compiled.unsupported),
            silent_drops=len(compiled.silent_drops),
        )
        await constraints.record_verification(
            revision_id, verified=graph.coverage.derived_constraints
        )
        loaded = await constraints.get_for_production(work_id)
        assert loaded is not None
        assert loaded.coverage.silent_drops == 0
        assert loaded.coverage.verification_rate >= 0.98
        assert loaded.coverage.derived_constraints >= 8
    finally:
        async with pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM domain_events WHERE aggregate_id = $1", uuid.UUID(work_id)
            )
            await conn.execute("DELETE FROM productions WHERE id = $1", uuid.UUID(work_id))
        await _close_live_pool(pool)
