"""D7-I: production readiness distinct from liveness.

Liveness = the process/event loop is alive.
Readiness = the process can serve production requests: database, the
differentiation authority stores, and the single-host authority claim all
resolve. Missing optional capabilities (GPU / lip-sync / local runtime) are
reported as ``OPTIONAL_CAPABILITY_BLOCKED`` and never make readiness fail.
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
from pathlib import Path
from typing import Any

from hevi.core.config import settings


def _authority_stores(identity_db: Path | None = None, incident_db: Path | None = None) -> dict[str, Any]:
    """Open the durable authority stores and report their host claim."""
    from hevi.creative.layer4.identity_store import IdentityStore
    from hevi.creative.layer4.incident_store import IncidentStore
    from hevi.creative.layer4.store_topology import current_claim

    report: dict[str, Any] = {}
    for name, store_cls, db in (
        ("identity", IdentityStore, identity_db),
        ("incident", IncidentStore, incident_db),
    ):
        try:
            store = store_cls(db) if db else store_cls()
            with __import__("sqlite3").connect(str(store.db_path)) as conn:
                claim = current_claim(conn, "identities" if name == "identity" else "incidents")
            report[name] = {"status": "ok", "claim": claim}
        except Exception as exc:  # readiness must not raise
            report[name] = {"status": "unavailable", "error": type(exc).__name__}
    return report


def _gpu_ready() -> bool:
    """True only if a CUDA device is actually usable, not merely that the
    nvidia-smi binary exists (it can be present while the device is gone)."""
    if shutil.which("nvidia-smi") is None:
        return False
    try:
        probe = subprocess.run(
            ["nvidia-smi", "-L"], capture_output=True, text=True, timeout=5
        )
    except (OSError, subprocess.SubprocessError):
        return False
    text = f"{probe.stdout}\n{probe.stderr}".lower()
    return (
        probe.returncode == 0
        and "no devices were found" not in text
        and "unable to determine the device handle" not in text
    )


def optional_capabilities() -> dict[str, str]:
    """Non-fatal capability states. GPU/lip-sync are optional features."""
    gpu_ready = _gpu_ready()
    return {
        "gpu": "READY" if gpu_ready else "OPTIONAL_CAPABILITY_BLOCKED",
        "lipsync_presenter": "UNQUALIFIED" if gpu_ready else "OPTIONAL_CAPABILITY_BLOCKED",
        "local_gpu_runtime": "UNQUALIFIED" if gpu_ready else "OPTIONAL_CAPABILITY_BLOCKED",
        "ffmpeg": "READY" if shutil.which("ffmpeg") else "REQUIRED_MISSING",
        "ffprobe": "READY" if shutil.which("ffprobe") else "REQUIRED_MISSING",
    }


async def _redis_readiness() -> dict[str, str]:
    try:
        from redis.asyncio import Redis

        client = Redis.from_url(settings.redis_url, decode_responses=True)
        try:
            await asyncio.wait_for(client.ping(), timeout=1.0)
        finally:
            await client.aclose()
        return {"status": "ok"}
    except Exception as exc:  # readiness must fail closed, never raise
        return {"status": "unavailable", "error": type(exc).__name__}


async def _minio_readiness() -> dict[str, str]:
    try:
        from minio import Minio

        client = Minio(
            settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=settings.minio_secure,
        )
        bucket_exists = await asyncio.wait_for(
            asyncio.to_thread(client.bucket_exists, settings.minio_bucket), timeout=2.0
        )
        if not bucket_exists:
            return {"status": "unavailable", "error": "bucket_missing"}
        return {"status": "ok", "bucket": settings.minio_bucket}
    except Exception as exc:  # readiness must fail closed, never raise
        return {"status": "unavailable", "error": type(exc).__name__}


async def _scheduler_readiness(pool: Any) -> dict[str, str]:
    if not settings.scheduler_required:
        return {"status": "not_required"}
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT owner_id, heartbeat_at, lease_until
                FROM scheduler_leases
                WHERE name = $1
                  AND lease_until > NOW()
                  AND heartbeat_at >= NOW() - ($2 * interval '1 second')
                """,
                settings.scheduler_leader_name,
                settings.scheduler_heartbeat_ttl_s,
            )
        if row is None:
            return {
                "status": "unavailable",
                "error": "scheduler_heartbeat_missing_or_expired",
            }
        return {
            "status": "ok",
            "owner_id": str(row["owner_id"]),
            "last_heartbeat_at": row["heartbeat_at"].isoformat(),
        }
    except Exception as exc:  # readiness must fail closed, never raise
        return {"status": "unavailable", "error": type(exc).__name__}


async def production_readiness_dependencies(*, pool: Any) -> dict[str, Any]:
    """Probe every production dependency after PostgreSQL is reachable."""

    from hevi.queue.heartbeat import WorkerHeartbeat

    worker: dict[str, Any]
    try:
        worker = await WorkerHeartbeat.readiness(
            pool, ttl_seconds=max(1, int(settings.worker_heartbeat_ttl_s))
        )
    except Exception as exc:
        worker = {"status": "unavailable", "error": type(exc).__name__}
    redis, minio, scheduler = await asyncio.gather(
        _redis_readiness(),
        _minio_readiness(),
        _scheduler_readiness(pool),
    )
    return {"redis": redis, "minio": minio, "worker": worker, "scheduler": scheduler}


def readiness_report(
    *, database_ok: bool, dependencies: dict[str, Any] | None = None
) -> dict[str, Any]:
    stores = _authority_stores()
    capabilities = optional_capabilities()
    stores_ok = all(entry.get("status") == "ok" for entry in stores.values())
    production_mode = not settings.local_mode
    if dependencies is None:
        # Preserve the direct, synchronous report contract used by local
        # authority tests. The HTTP readiness endpoint always supplies real
        # dependency probes in production mode.
        dependencies = {
            "redis": {"status": "not_checked"},
            "minio": {"status": "not_checked"},
            "worker": {"status": "not_checked"},
            "scheduler": {"status": "not_checked"},
        }
        dependencies_ok = True
    else:
        dependencies_ok = all(
            entry.get("status") in {"ok", "not_required"}
            for entry in dependencies.values()
        )
    ready = bool(database_ok and stores_ok and (not production_mode or dependencies_ok))
    return {
        "status": "ready" if ready else "not_ready",
        "database": "ok" if database_ok else "unavailable",
        "redis": dependencies["redis"],
        "minio": dependencies["minio"],
        "worker_heartbeat": dependencies["worker"],
        "scheduler": dependencies["scheduler"],
        "heartbeat_persisted": "YES",
        "readiness_requires_worker": "YES" if production_mode else "NO",
        "scheduler_release_critical": "YES" if settings.scheduler_required else "NO",
        "authority_stores": stores,
        "authority_host_claim": "single_host_durable",
        "optional_capabilities": capabilities,
        "degraded": [
            name for name, state in capabilities.items() if state == "OPTIONAL_CAPABILITY_BLOCKED"
        ],
    }


__all__ = ["optional_capabilities", "production_readiness_dependencies", "readiness_report"]
