"""Opt-in live checks for the production closure boundary.

Run inside the production Compose network with ``HEVI_LIVE_TESTS=1``.  The
default test suite skips these checks because they require PostgreSQL, MinIO,
Redis and an explicit disposable environment.
"""

from __future__ import annotations

import asyncio
import json
import math
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
    """Close the process-global pool so the disposable smoke run can exit."""

    underlying = getattr(pool, "_pool", None)
    if underlying is not None:
        await underlying.close()
    from obase.persistence import PgPool

    for name, registered in tuple(PgPool._registry.items()):
        if registered is pool:
            PgPool._registry.pop(name, None)


@pytest.mark.asyncio
async def test_live_attempt_recovery_requeues_expired_worker() -> None:
    from hevi.db.pg_pool import get_hevi_pg_pool
    from hevi.tasks.attempt_repository import AttemptRepository

    pool = await get_hevi_pg_pool()
    task_id = uuid.uuid4()
    attempt_id = uuid.uuid4()
    now = datetime.now(UTC)
    legacy_now = now.replace(tzinfo=None)
    lease_token = f"live-{uuid.uuid4()}"
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO video_tasks
                    (id, topic, duration_archetype, video_provider, audio_provider,
                     status, progress_pct, total_shots, completed_shots, config_json,
                     created_at, updated_at, worker_id, lease_token, lease_until,
                     heartbeat_at)
                VALUES ($1, 'live-recovery', '1-5min', 'wan_local', 'edge_tts',
                        'running', 42, 4, 1, $2, $3, $3, 'worker-a', $4, $5, $5)
                """,
                task_id,
                {"production_source": "live-test"},
                legacy_now,
                lease_token,
                legacy_now - timedelta(seconds=90),
            )
            await conn.execute(
                """
                INSERT INTO task_attempts
                    (id, task_id, attempt_no, status, worker_id, lease_token,
                     lease_until, heartbeat_at, started_at, created_at, metadata)
                VALUES ($1, $2, 1, 'running', 'worker-a', $3, $4, $4, $5, $5, $6)
                """,
                attempt_id,
                task_id,
                lease_token,
                now - timedelta(seconds=90),
                now - timedelta(minutes=2),
                {"live": True},
            )
            await conn.execute(
                "UPDATE video_tasks SET current_attempt_id = $1 WHERE id = $2",
                attempt_id,
                task_id,
            )

        attempts = AttemptRepository(pool)
        checkpoint = await attempts.checkpoint(
            attempt_id=attempt_id,
            task_id=task_id,
            stage="render",
            progress_pct=42,
            completed_shots=1,
            total_shots=4,
            state={"live": "checkpoint"},
        )
        assert checkpoint["stage"] == "render"
        latest = await attempts.latest(task_id)
        assert latest is not None
        assert latest["state_json"] == {"live": "checkpoint"}
        recovered = await attempts.recover_expired(limit=10)
        assert any(str(item.get("task_id")) == str(task_id) for item in recovered)
        async with pool.acquire() as conn:
            task = await conn.fetchrow(
                "SELECT status, lease_token FROM video_tasks WHERE id = $1", task_id
            )
            attempt = await conn.fetchrow(
                "SELECT status FROM task_attempts WHERE id = $1", attempt_id
            )
        assert task["status"] == "queued"
        assert task["lease_token"] is None
        assert attempt["status"] == "interrupted"
        async with pool.acquire() as conn:
            event = await conn.fetchrow(
                """
                SELECT event_type, payload
                FROM domain_events
                WHERE aggregate_type = 'task' AND aggregate_id = $1
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """,
                task_id,
            )
        assert event["event_type"] == "task.status.queued"
        assert event["payload"]["reason"] == "attempt_lease_expired"
    finally:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM domain_events WHERE aggregate_id = $1", task_id)
            await conn.execute("DELETE FROM video_tasks WHERE id = $1", task_id)
        await _close_live_pool(pool)


@pytest.mark.asyncio
async def test_live_two_workers_claim_one_task_and_same_attempt_is_idempotent() -> None:
    """The queue must have one durable owner, even when workers race."""

    from hevi.db.pg_pool import get_hevi_pg_pool
    from hevi.tasks.attempt_repository import AttemptRepository
    from hevi.tasks.repository import TaskRepository

    pool = await get_hevi_pg_pool()
    task_id = uuid.uuid4()
    now = datetime.now(UTC).replace(tzinfo=None)
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO video_tasks
                    (id, topic, duration_archetype, video_provider, audio_provider,
                     status, progress_pct, total_shots, completed_shots, config_json,
                     created_at, updated_at, queued_at, available_at, priority,
                     resource_class, required_vram_mb, expected_cost_usd, tenant_weight)
                VALUES ($1, 'live-claim', '1-5min', 'wan_local', 'edge_tts',
                        'queued', 0, 1, 0, $2, $3, $3, $3, $3, 1,
                        'gpu-video', 0, 0, 1)
                """,
                task_id,
                {"production_source": "live-claim"},
                now,
            )

        repository = TaskRepository(pool)
        claimed = await asyncio.gather(
            repository.claim_next_queued_task(
                worker_id="live-worker-a", scheduled_only=False,
                resource_class="gpu-video",
            ),
            repository.claim_next_queued_task(
                worker_id="live-worker-b", scheduled_only=False,
                resource_class="gpu-video",
            ),
        )
        owners = [item for item in claimed if item is not None]
        target_owners = [item for item in owners if str(item["id"]) == str(task_id)]
        assert len(target_owners) == 1
        owner = target_owners[0]
        assert str(owner["id"]) == str(task_id)

        attempts = AttemptRepository(pool)
        lease_token = str(owner["lease_token"])
        first = await attempts.start(
            task_id,
            worker_id=str(owner["worker_id"]),
            lease_token=lease_token,
            lease_until=owner["lease_until"],
        )
        second = await attempts.start(
            task_id,
            worker_id=str(owner["worker_id"]),
            lease_token=lease_token,
            lease_until=owner["lease_until"],
        )
        assert first["id"] == second["id"]
        assert first["attempt_no"] == second["attempt_no"]
        async with pool.acquire() as conn:
            event = await conn.fetchrow(
                """
                SELECT event_type, payload
                FROM domain_events
                WHERE aggregate_type = 'task' AND aggregate_id = $1
                  AND event_type = 'task.status.claimed'
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """,
                task_id,
            )
        assert event["payload"]["to_status"] == "claimed"
    finally:
        async with pool.acquire() as conn:
            # This shared acceptance database may contain unrelated queued
            # work. Restore only rows claimed by this test's worker ids.
            await conn.execute(
                """
                UPDATE video_tasks
                SET status = 'queued', worker_id = NULL, lease_token = NULL,
                    lease_until = NULL, heartbeat_at = NULL, scheduled_at = NULL,
                    updated_at = NOW()
                WHERE worker_id = ANY($1::text[]) AND status = 'claimed'
                """,
                ["live-worker-a", "live-worker-b"],
            )
            await conn.execute("DELETE FROM domain_events WHERE aggregate_id = $1", task_id)
            await conn.execute("DELETE FROM video_tasks WHERE id = $1", task_id)
        await _close_live_pool(pool)


@pytest.mark.asyncio
async def test_live_provider_state_is_persistent_and_policy_reacts() -> None:
    from hevi.db.pg_pool import get_hevi_pg_pool
    from hevi.provider_policy import (
        ProviderPolicy,
        ProviderStateRepository,
        evaluate_provider_policy,
    )

    pool = await get_hevi_pg_pool()
    provider = f"live-provider-{uuid.uuid4()}"
    try:
        repository = ProviderStateRepository(pool)
        # Use a real registered provider for capability/quality checks, while
        # storing the live state under a disposable provider id is not useful.
        provider = "veo3"
        await repository.upsert(provider, health=0.1, quota_remaining=0, source="live-test")
        blocked = await evaluate_provider_policy(
            ProviderPolicy(candidates=[provider], quality_floor=9),
            state_repository=repository,
        )
        assert blocked.selected_provider is None
        assert any(
            reason.startswith("health_below_floor")
            for reason in blocked.rejected[0].reasons
        )

        await repository.upsert(provider, health=1.0, quota_remaining=3, source="live-test")
        selected = await evaluate_provider_policy(
            ProviderPolicy(candidates=[provider], quality_floor=9),
            state_repository=repository,
        )
        assert selected.selected_provider == provider
        outcome_id = await repository.record_outcome(
            provider,
            task_class="live",
            status="success",
            latency_ms=12.5,
            quality_score=0.95,
        )
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT provider_id, status FROM provider_outcomes WHERE id = $1", outcome_id
            )
        assert row["provider_id"] == provider
        assert row["status"] == "success"
    finally:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM provider_outcomes WHERE provider_id = $1", provider)
            await conn.execute(
                "DELETE FROM provider_runtime_state WHERE provider_id = $1", provider
            )
        await _close_live_pool(pool)


@pytest.mark.asyncio
async def test_live_quality_evidence_and_repair_plan_are_queryable() -> None:
    from hevi.db.pg_pool import get_hevi_pg_pool
    from hevi.quality import (
        FailureCode,
        GatePolicy,
        QualityEvaluation,
        QualityEvidence,
        RepairBudget,
        RepairController,
        RepairRepository,
    )

    pool = await get_hevi_pg_pool()
    production_id = uuid.uuid4()
    task_id = uuid.uuid4()
    now = datetime.now(UTC).replace(tzinfo=None)
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO productions (id, user_id, type, status) VALUES ($1, $2, $3, $4)",
                production_id,
                "live-quality-user",
                "live-test",
                "draft",
            )
            await conn.execute(
                """
                INSERT INTO video_tasks
                    (id, topic, duration_archetype, video_provider, audio_provider,
                     status, progress_pct, total_shots, completed_shots, config_json,
                     created_at, updated_at)
                VALUES ($1, 'live-quality', '1-5min', 'wan_local', 'edge_tts',
                        'pending', 0, 1, 0, $2, $3, $3)
                """,
                task_id,
                {"production_id": str(production_id)},
                now,
            )
        policy = GatePolicy.for_profile("standard")
        evaluation = QualityEvaluation.from_evidence(
            [
                QualityEvidence(
                    code=FailureCode.IDENTITY_MISMATCH,
                    scope="shot:0",
                    passed=False,
                    evidence={"message": "identity mismatch"},
                )
            ],
            policy,
        )
        controller = RepairController(RepairBudget(max_attempts=1, max_cost_usd=2.0))
        controller.observe(evaluation)
        decision = controller.decide(evaluation)
        run_id = await RepairRepository(pool).save_run(
            task_id=task_id,
            production_id=production_id,
            policy=policy,
            controller=controller,
            decision=decision,
            evaluation=evaluation,
        )
        async with pool.acquire() as conn:
            stored = await conn.fetchrow(
                "SELECT id, passed, residual_count FROM evaluations WHERE task_id = $1",
                task_id,
            )
            violation = await conn.fetchrow(
                "SELECT taxonomy, repairable FROM violations WHERE evaluation_id = $1",
                stored["id"],
            )
            plan = await conn.fetchrow(
                "SELECT action, status FROM repair_plans WHERE task_id = $1",
                task_id,
            )
        assert str(run_id)
        assert stored["passed"] is False
        assert stored["residual_count"] == 1
        assert violation["taxonomy"] == "IDENTITY_MISMATCH"
        assert violation["repairable"] is True
        assert plan["action"] == "replace_reference"
        assert plan["status"] == "planned"
    finally:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM video_tasks WHERE id = $1", task_id)
            await conn.execute("DELETE FROM productions WHERE id = $1", production_id)
        await _close_live_pool(pool)


@pytest.mark.asyncio
async def test_live_budget_reservation_is_idempotent_under_race() -> None:
    from hevi.budget import BudgetRepository
    from hevi.db.pg_pool import get_hevi_pg_pool

    pool = await get_hevi_pg_pool()
    production_id = uuid.uuid4()
    attempt_key = f"live-budget-{uuid.uuid4()}"
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO productions (id, user_id, type, status) VALUES ($1, $2, $3, $4)",
                production_id,
                "live-budget-user",
                "live-test",
                "draft",
            )
        repository = BudgetRepository(pool)
        await repository.ensure_envelope(
            production_id=production_id,
            hard_limit_usd=10,
            soft_limit_usd=9,
            retake_pool_usd=1,
            stage_allocations={"rendering": 9},
        )
        reservations = await asyncio.gather(
            repository.reserve_attempt(
                production_id=production_id,
                attempt_key=attempt_key,
                estimated_cost_usd=2,
            ),
            repository.reserve_attempt(
                production_id=production_id,
                attempt_key=attempt_key,
                estimated_cost_usd=2,
            ),
        )
        assert reservations[0].attempt_id == reservations[1].attempt_id
        async with pool.acquire() as conn:
            count = await conn.fetchval(
                """
                SELECT count(*) FROM budget_ledger bl
                JOIN production_budgets pb ON pb.id = bl.production_budget_id
                WHERE pb.production_id = $1 AND bl.entry_type = 'reserve'
                """,
                production_id,
            )
        assert count == 1
        await repository.release_attempt(reservations[0].attempt_id)
    finally:
        async with pool.acquire() as conn:
            budget_id = await conn.fetchval(
                "SELECT id FROM production_budgets WHERE production_id = $1", production_id
            )
            if budget_id is not None:
                # Ledger immutability is a production invariant. This toggle is
                # scoped to disposable live-test rows only, so the test leaves
                # no financial history in the shared acceptance database.
                await conn.execute(
                    "ALTER TABLE budget_ledger DISABLE TRIGGER budget_ledger_append_only"
                )
                await conn.execute(
                    "DELETE FROM budget_ledger WHERE production_budget_id = $1", budget_id
                )
                await conn.execute(
                    "ALTER TABLE budget_ledger ENABLE TRIGGER budget_ledger_append_only"
                )
                await conn.execute(
                    "DELETE FROM budget_attempts WHERE production_budget_id = $1", budget_id
                )
                await conn.execute(
                    "DELETE FROM stage_budgets WHERE production_budget_id = $1", budget_id
                )
                await conn.execute("DELETE FROM production_budgets WHERE id = $1", budget_id)
            await conn.execute("DELETE FROM productions WHERE id = $1", production_id)
        await _close_live_pool(pool)


@pytest.mark.asyncio
async def test_live_outbox_publish_and_minio_roundtrip(tmp_path: Path) -> None:
    from minio import Minio

    from hevi.artifact_store.object_store import MinioObjectStore
    from hevi.core.config import settings
    from hevi.db.pg_pool import get_hevi_pg_pool
    from hevi.events.outbox import DomainEvent, OutboxRepository
    from hevi.events.publisher import OutboxPublisher

    pool = await get_hevi_pg_pool()
    event = DomainEvent(event_type="live.test", aggregate_id=uuid.uuid4(), payload={"ok": True})
    source = tmp_path / "live.bin"
    source.write_bytes(os.urandom(32))
    client = Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
    )
    store = MinioObjectStore(client, bucket="hevi-assets")
    stored = await store.put_file(source, media_type="application/octet-stream")
    assert await store.get_bytes(stored.uri) == source.read_bytes()
    client.remove_object("hevi-assets", stored.uri.rsplit("/", 1)[-1])

    repo = OutboxRepository(pool)
    await repo.append(event)
    published: list[str] = []

    async def handler(item: DomainEvent) -> None:
        published.append(str(item.id))

    publisher = OutboxPublisher(repo, handler)
    # A used live database may already have unpublished recovery events.
    # Drain batches until this test's event is claimed or the outbox is empty.
    published_count = 0
    deadline = time.time() + 5
    while str(event.id) not in published and time.time() < deadline:
        n = await publisher.publish_once()
        published_count += n
        if n == 0:
            break
    assert published_count >= 1
    assert str(event.id) in published
    consumer_name = f"live-test-consumer-{uuid.uuid4()}"
    batch = await repo.read_consumer_batch(consumer_name, aggregate_id=event.aggregate_id)
    matching = next(item for item in batch if item.id == event.id)
    await repo.advance_consumer(consumer_name, matching)
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM domain_events WHERE id = $1", event.id)
        await conn.execute(
            "DELETE FROM event_consumer_offsets WHERE consumer_name = $1", consumer_name
        )
    await _close_live_pool(pool)


@pytest.mark.asyncio
async def test_live_event_consumer_retries_then_dead_letters() -> None:
    from hevi.db.pg_pool import get_hevi_pg_pool
    from hevi.events import EventConsumer
    from hevi.events.outbox import DomainEvent

    pool = await get_hevi_pg_pool()
    event = DomainEvent(event_type="live.retry", aggregate_id=uuid.uuid4())
    consumer_name = f"live-retry-{uuid.uuid4()}"
    try:
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

        async def fail_handler(_: DomainEvent) -> None:
            raise RuntimeError("live broker unavailable")

        consumer = EventConsumer(
            pool,
            fail_handler,
            consumer_name=consumer_name,
            max_attempts=2,
            aggregate_id=event.aggregate_id,
        )
        with pytest.raises(RuntimeError, match="live broker unavailable"):
            await consumer.consume_once()
        async with pool.acquire() as conn:
            first = await conn.fetchrow(
                "SELECT attempts, dead_lettered_at FROM event_dead_letters WHERE event_id = $1",
                event.id,
            )
        assert first["attempts"] == 1
        assert first["dead_lettered_at"] is None

        assert await consumer.consume_once() == 1
        async with pool.acquire() as conn:
            dead = await conn.fetchrow(
                "SELECT attempts, dead_lettered_at FROM event_dead_letters WHERE event_id = $1",
                event.id,
            )
            offset = await conn.fetchrow(
                "SELECT last_event_id FROM event_consumer_offsets WHERE consumer_name = $1",
                consumer_name,
            )
        assert dead["attempts"] == 2
        assert dead["dead_lettered_at"] is not None
        assert offset["last_event_id"] == event.id
    finally:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM domain_events WHERE id = $1", event.id)
            await conn.execute(
                "DELETE FROM event_consumer_offsets WHERE consumer_name = $1", consumer_name
            )
        await _close_live_pool(pool)


@pytest.mark.asyncio
async def test_live_minio_integrity_rejects_tamper(tmp_path: Path) -> None:
    from io import BytesIO

    from fastapi import HTTPException
    from minio import Minio

    from hevi.artifact_store.http import materialize_artifact
    from hevi.artifact_store.object_store import MinioObjectStore
    from hevi.core.config import settings
    from hevi.production.artifacts import Artifact, ArtifactManifest

    source = tmp_path / "integrity.mp4"
    source.write_bytes(b"integrity-source")
    client = Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
    )
    store = MinioObjectStore(client, bucket=settings.minio_bucket)
    stored = await store.put_file(source, media_type="video/mp4")
    manifest = ArtifactManifest(
        artifacts=[
            Artifact(
                kind="video",
                path=str(source),
                primary=True,
                uri=stored.uri,
                sha256=stored.sha256,
                byte_size=stored.byte_size,
            )
        ]
    )
    key = stored.uri.rsplit("/", 1)[-1]
    try:
        materialized = await materialize_artifact(manifest, kind="video")
        assert materialized.read_bytes() == source.read_bytes()
        client.put_object(
            settings.minio_bucket,
            key,
            BytesIO(b"tampered-content"),
            length=len(b"tampered-content"),
            content_type="video/mp4",
        )
        with pytest.raises(HTTPException) as tampered:
            await materialize_artifact(manifest, kind="video")
        assert tampered.value.status_code == 409
    finally:
        client.remove_object(settings.minio_bucket, key)


@pytest.mark.asyncio
async def test_live_scheduler_leader_lease() -> None:
    from hevi.db.pg_pool import get_hevi_pg_pool
    from hevi.scheduler.repository import SchedulerRepository

    pool = await get_hevi_pg_pool()
    name = f"live-{uuid.uuid4()}"
    repository = SchedulerRepository(pool)
    assert await repository.acquire_leader(name, "scheduler-a", lease_seconds=30)
    assert not await repository.acquire_leader(name, "scheduler-b", lease_seconds=30)
    assert await repository.acquire_leader(name, "scheduler-a", lease_seconds=30)
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM scheduler_leases WHERE name = $1", name)
    await _close_live_pool(pool)


@pytest.mark.skipif(
    os.getenv("HEVI_LIVE_WS") != "1", reason="two-instance WS check is opt-in"
)
@pytest.mark.asyncio
async def test_live_cross_instance_ws_fanout_latency() -> None:
    import websockets.asyncio.client

    from hevi.db.pg_pool import get_hevi_pg_pool
    from hevi.events.outbox import DomainEvent

    pool = await get_hevi_pg_pool()
    url_a = os.getenv("HEVI_LIVE_WS_URL_A", "ws://hevi-live-api-a:8000/api/ws/tasks")
    url_b = os.getenv("HEVI_LIVE_WS_URL_B", os.getenv("HEVI_LIVE_WS_URL", "ws://hevi-live-api-b:8000/api/ws/tasks"))
    sample_count = max(5, int(os.getenv("HEVI_LIVE_WS_SAMPLES", "20")))
    event_ids: list[uuid.UUID] = []
    try:
        async with websockets.asyncio.client.connect(url_a, open_timeout=5) as socket_a:
            async with websockets.asyncio.client.connect(url_b, open_timeout=5) as socket_b:
                aggregate_id = uuid.uuid4()
                for socket in (socket_a, socket_b):
                    await socket.send(
                        json.dumps(
                            {"type": "subscribe", "resource_ids": [str(aggregate_id)]}
                        )
                    )
                    subscribed = json.loads(await asyncio.wait_for(socket.recv(), timeout=2))
                    assert subscribed["type"] == "subscribed"

                latencies: list[float] = []
                for sample in range(sample_count):
                    event = DomainEvent(
                        event_type="live.ws_latency",
                        aggregate_id=aggregate_id,
                        payload={"source": "live-two-instance", "sample": sample},
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
                    received_a, received_b = await asyncio.gather(
                        asyncio.wait_for(socket_a.recv(), timeout=2),
                        asyncio.wait_for(socket_b.recv(), timeout=2),
                    )
                    latency = time.perf_counter() - started
                    latencies.append(latency)
                    assert json.loads(received_a)["event_id"] == str(event.id)
                    assert json.loads(received_b)["event_id"] == str(event.id)

                p95_index = max(0, math.ceil(len(latencies) * 0.95) - 1)
                p95 = sorted(latencies)[p95_index]
                assert p95 < 2.0, f"WS p95={p95:.3f}s samples={latencies!r}"
    finally:
        async with pool.acquire() as conn:
            if event_ids:
                await conn.execute(
                    "DELETE FROM domain_events WHERE id = ANY($1::uuid[])", event_ids
                )
        await _close_live_pool(pool)


@pytest.mark.asyncio
async def test_live_stale_worker_cannot_finish_after_recovery() -> None:
    """A worker that lost its lease cannot write the terminal attempt state."""

    from hevi.db.pg_pool import get_hevi_pg_pool
    from hevi.tasks.attempt_repository import AttemptRepository
    from hevi.tasks.repository import TaskRepository

    pool = await get_hevi_pg_pool()
    task_id = uuid.uuid4()
    attempt_id = uuid.uuid4()
    now = datetime.now(UTC)
    legacy_now = now.replace(tzinfo=None)
    stale_token = f"stale-{uuid.uuid4()}"
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO video_tasks
                    (id, topic, duration_archetype, video_provider, audio_provider,
                     status, progress_pct, total_shots, completed_shots, config_json,
                     created_at, updated_at, worker_id, lease_token, lease_until,
                     heartbeat_at, queued_at, available_at)
                VALUES ($1, 'live-stale', '1-5min', 'wan_local', 'edge_tts',
                        'running', 40, 2, 1, $2, $3, $3, 'worker-stale', $4, $5, $5,
                        $3, $3)
                """,
                task_id,
                {"production_source": "live-stale"},
                legacy_now,
                stale_token,
                legacy_now - timedelta(seconds=90),
            )
            await conn.execute(
                """
                INSERT INTO task_attempts
                    (id, task_id, attempt_no, status, worker_id, lease_token,
                     lease_until, heartbeat_at, started_at, created_at, metadata)
                VALUES ($1, $2, 1, 'running', 'worker-stale', $3, $4, $4, $5, $5, $6)
                """,
                attempt_id,
                task_id,
                stale_token,
                now - timedelta(seconds=90),
                now - timedelta(minutes=2),
                {"live": "stale"},
            )
            await conn.execute(
                "UPDATE video_tasks SET current_attempt_id = $1 WHERE id = $2",
                attempt_id,
                task_id,
            )
        attempts = AttemptRepository(pool)
        recovered = await attempts.recover_expired(limit=10)
        assert any(str(item.get("task_id")) == str(task_id) for item in recovered)
        assert not await attempts.finish(
            attempt_id, lease_token=stale_token, status="succeeded"
        )

        repository = TaskRepository(pool)
        claimed = await repository.claim_next_queued_task(
            worker_id="worker-fresh", scheduled_only=False
        )
        assert claimed is not None
        assert str(claimed["id"]) == str(task_id)
        fresh = await attempts.start(
            task_id,
            worker_id="worker-fresh",
            lease_token=str(claimed["lease_token"]),
            lease_until=claimed["lease_until"],
        )
        assert str(fresh["id"]) != str(attempt_id)
        assert await attempts.finish(
            fresh["id"], lease_token=str(claimed["lease_token"]), status="succeeded"
        )
        assert not await attempts.finish(
            attempt_id, lease_token=stale_token, status="succeeded"
        )
    finally:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM domain_events WHERE aggregate_id = $1", task_id)
            await conn.execute("DELETE FROM video_tasks WHERE id = $1", task_id)
        await _close_live_pool(pool)


@pytest.mark.asyncio
async def test_live_checkpoint_is_visible_to_the_next_worker() -> None:
    from hevi.db.pg_pool import get_hevi_pg_pool
    from hevi.tasks.attempt_repository import AttemptRepository

    pool = await get_hevi_pg_pool()
    task_id = uuid.uuid4()
    now = datetime.now(UTC)
    legacy_now = now.replace(tzinfo=None)
    lease_token = f"ckpt-{uuid.uuid4()}"
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO video_tasks
                    (id, topic, duration_archetype, video_provider, audio_provider,
                     status, progress_pct, total_shots, completed_shots, config_json,
                     created_at, updated_at, worker_id, lease_token, lease_until,
                     heartbeat_at)
                VALUES ($1, 'live-ckpt', '1-5min', 'wan_local', 'edge_tts',
                        'running', 55, 4, 2, $2, $3, $3, 'worker-a', $4, $5, $5)
                """,
                task_id,
                {"production_source": "live-ckpt"},
                legacy_now,
                lease_token,
                legacy_now - timedelta(seconds=90),
            )
        attempts = AttemptRepository(pool)
        attempt = await attempts.start(
            task_id,
            worker_id="worker-a",
            lease_token=lease_token,
            lease_until=now - timedelta(seconds=90),
        )
        await attempts.checkpoint(
            attempt_id=attempt["id"],
            task_id=task_id,
            stage="render",
            progress_pct=55,
            completed_shots=2,
            total_shots=4,
            state={"boundary": "after-shot-2"},
        )
        await attempts.recover_expired(limit=10)
        latest = await attempts.latest(task_id)
        assert latest is not None
        assert latest["state_json"] == {"boundary": "after-shot-2"}
        assert latest["stage"] == "render"
        assert latest["completed_shots"] == 2
    finally:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM domain_events WHERE aggregate_id = $1", task_id)
            await conn.execute("DELETE FROM video_tasks WHERE id = $1", task_id)
        await _close_live_pool(pool)


@pytest.mark.asyncio
async def test_live_production_graph_reread_is_identical() -> None:
    from hevi.db.pg_pool import get_hevi_pg_pool
    from hevi.production_graph import ProductionGraphRepository

    pool = await get_hevi_pg_pool()
    work_id = str(uuid.uuid4())
    record = {
        "work_id": work_id,
        "user_id": "live-graph-user",
        "status": "shot_list_locked",
        "type": "director",
        "material_text": "live persistence",
        "locked_through": 4,
        "concept": {"theme": "lease-safety"},
        "shot_list": {"shots": [{"id": "S01"}]},
    }
    try:
        repository = ProductionGraphRepository(pool)
        saved = await repository.save(record, reason="locked", locked_stage="shot_list")
        first = await repository.get(work_id)
        second = await repository.get(work_id)
        assert first is not None and second is not None
        assert first["revision_id"] == saved["revision_id"] == second["revision_id"]
        assert first["concept"]["theme"] == "lease-safety"
        updated = await repository.save({**first, "status": "producing"}, reason="produce")
        assert updated["revision_id"] != first["revision_id"]
        reread = await repository.get(work_id)
        assert reread is not None
        assert reread["revision_id"] == updated["revision_id"]
        assert reread["status"] == "producing"
    finally:
        async with pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM domain_events WHERE aggregate_id = $1", uuid.UUID(work_id)
            )
            await conn.execute("DELETE FROM productions WHERE id = $1", uuid.UUID(work_id))
        await _close_live_pool(pool)


@pytest.mark.asyncio
async def test_live_two_consumer_cursors_fan_out_p95() -> None:
    from hevi.db.pg_pool import get_hevi_pg_pool
    from hevi.events import EventConsumer
    from hevi.events.outbox import DomainEvent

    pool = await get_hevi_pg_pool()
    aggregate_id = uuid.uuid4()
    received_a: list[str] = []
    received_b: list[str] = []
    async def _capture_a(event: DomainEvent) -> None:
        received_a.append(str(event.id))

    async def _capture_b(event: DomainEvent) -> None:
        received_b.append(str(event.id))

    consumer_a = EventConsumer(
        pool,
        _capture_a,
        consumer_name=f"live-p95-a-{uuid.uuid4()}",
        aggregate_id=aggregate_id,
    )
    consumer_b = EventConsumer(
        pool,
        _capture_b,
        consumer_name=f"live-p95-b-{uuid.uuid4()}",
        aggregate_id=aggregate_id,
    )
    event_ids: list[uuid.UUID] = []
    latencies: list[float] = []
    try:
        for sample in range(20):
            event = DomainEvent(
                event_type="live.consumer_p95",
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
            while str(event.id) not in received_a or str(event.id) not in received_b:
                await asyncio.gather(consumer_a.consume_once(), consumer_b.consume_once())
                if time.perf_counter() - started > 2.0:
                    break
            latencies.append(time.perf_counter() - started)
            assert str(event.id) in received_a
            assert str(event.id) in received_b
        p95 = sorted(latencies)[max(0, math.ceil(len(latencies) * 0.95) - 1)]
        assert p95 < 2.0, f"consumer fan-out p95={p95:.3f}s samples={latencies!r}"
    finally:
        async with pool.acquire() as conn:
            if event_ids:
                await conn.execute(
                    "DELETE FROM domain_events WHERE id = ANY($1::uuid[])", event_ids
                )
            await conn.execute(
                "DELETE FROM event_consumer_offsets WHERE consumer_name LIKE $1",
                "live-p95-%",
            )
        await _close_live_pool(pool)
