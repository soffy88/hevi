"""Disposable live load check for the production closure boundary.

This intentionally exercises queue claim serialization and the event-to-WS
fan-out path without invoking billable providers. It requires
``HEVI_LIVE_LOAD=1`` and must run inside the production Compose network.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import time
import uuid
from contextlib import suppress
from datetime import UTC, datetime

import websockets.asyncio.client


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tasks", type=int, default=1000)
    parser.add_argument("--ws", type=int, default=100)
    parser.add_argument("--ws-samples", type=int, default=5)
    return parser.parse_args()


async def _subscribe(
    socket: websockets.asyncio.client.ClientConnection, aggregate_id: uuid.UUID
) -> None:
    import json

    await socket.send(
        json.dumps({"type": "subscribe", "resource_ids": [str(aggregate_id)]})
    )
    message = json.loads(await asyncio.wait_for(socket.recv(), timeout=5))
    if message.get("type") != "subscribed":
        raise RuntimeError(f"WS subscription failed: {message!r}")


async def _main() -> None:
    if os.getenv("HEVI_LIVE_LOAD") != "1":
        raise SystemExit("set HEVI_LIVE_LOAD=1 to run the disposable load check")

    args = _args()
    if args.tasks < 1 or args.ws < 1 or args.ws_samples < 1:
        raise SystemExit("tasks, ws and ws-samples must be positive")

    from hevi.db.pg_pool import get_hevi_pg_pool
    from hevi.events.outbox import DomainEvent
    from hevi.tasks.repository import TaskRepository

    pool = await get_hevi_pg_pool()
    task_ids = [uuid.uuid4() for _ in range(args.tasks)]
    event_ids: list[uuid.UUID] = []
    sockets: list[websockets.asyncio.client.ClientConnection] = []
    ws_url_a = os.getenv("HEVI_LIVE_WS_URL_A", "ws://hevi-live-api-a:8000/api/ws/tasks")
    ws_url_b = os.getenv("HEVI_LIVE_WS_URL_B", "ws://hevi-live-api-b:8000/api/ws/tasks")
    try:
        now = datetime.now(UTC).replace(tzinfo=None)
        rows = [
            (
                task_id,
                f"live-load-{index}",
                {"production_source": "live-load"},
                now,
            )
            for index, task_id in enumerate(task_ids)
        ]
        async with pool.acquire() as conn:
            await conn.executemany(
                """
                INSERT INTO video_tasks
                    (id, topic, duration_archetype, video_provider, audio_provider,
                     status, progress_pct, total_shots, completed_shots, config_json,
                     created_at, updated_at, queued_at, available_at, priority,
                     resource_class, required_vram_mb, expected_cost_usd, tenant_weight)
                VALUES ($1, $2, '1-5min', 'wan_local', 'edge_tts', 'queued',
                        0, 1, 0, $3, $4, $4, $4, $4, 0, 'any', 0, 0, 1)
                """,
                rows,
            )

        repository = TaskRepository(pool)
        claimed: list[uuid.UUID] = []
        claim_lock = asyncio.Lock()

        async def drain(worker_id: str) -> None:
            while True:
                item = await repository.claim_next_queued_task(
                    worker_id=worker_id, scheduled_only=False
                )
                if item is None:
                    return
                async with claim_lock:
                    claimed.append(uuid.UUID(str(item["id"])))

        await asyncio.gather(drain("load-worker-a"), drain("load-worker-b"))
        if len(claimed) != args.tasks or len(set(claimed)) != args.tasks:
            raise AssertionError(
                f"claim mismatch expected={args.tasks} actual={len(claimed)} "
                f"unique={len(set(claimed))}"
            )
        print(f"queue claim passed tasks={args.tasks} unique={len(set(claimed))}")

        urls = [ws_url_a if index % 2 == 0 else ws_url_b for index in range(args.ws)]
        sockets = list(
            await asyncio.gather(
                *(websockets.asyncio.client.connect(url, open_timeout=10) for url in urls)
            )
        )
        aggregate_id = uuid.uuid4()
        await asyncio.gather(*(_subscribe(socket, aggregate_id) for socket in sockets))

        latencies: list[float] = []
        import json

        for sample in range(args.ws_samples):
            event = DomainEvent(
                event_type="live.load.ws",
                aggregate_id=aggregate_id,
                payload={"sample": sample, "clients": args.ws},
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
            messages = await asyncio.gather(
                *(asyncio.wait_for(socket.recv(), timeout=5) for socket in sockets)
            )
            if any(json.loads(message).get("event_id") != str(event.id) for message in messages):
                raise AssertionError("at least one WS client received the wrong event")
            latencies.append(time.perf_counter() - started)

        p95 = sorted(latencies)[max(0, (len(latencies) * 95 + 99) // 100 - 1)]
        if p95 >= 2.0:
            raise AssertionError(f"WS p95={p95:.3f}s >= 2s; samples={latencies!r}")
        print(f"WS load passed clients={args.ws} samples={args.ws_samples} p95={p95:.3f}s")
    finally:
        for socket in sockets:
            with suppress(Exception):
                await socket.close()
        async with pool.acquire() as conn:
            if task_ids:
                await conn.execute(
                    "DELETE FROM video_tasks WHERE id = ANY($1::uuid[])", task_ids
                )
            if event_ids:
                await conn.execute(
                    "DELETE FROM domain_events WHERE id = ANY($1::uuid[])", event_ids
                )
        underlying = getattr(pool, "_pool", None)
        if underlying is not None:
            await underlying.close()
        from obase.persistence import PgPool

        for name, registered in tuple(PgPool._registry.items()):
            if registered is pool:
                PgPool._registry.pop(name, None)


if __name__ == "__main__":
    asyncio.run(_main())
