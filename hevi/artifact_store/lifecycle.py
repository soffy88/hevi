"""Expire raw attempt artifacts while keeping selected/final objects."""

from __future__ import annotations

from contextlib import suppress
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from obase.persistence import PgPool

from hevi.core.config import settings

from .object_store import ObjectStore


def expiry_for_role(logical_role: str | None, *, now: datetime | None = None) -> datetime | None:
    """Raw attempts expire; selected/final artifacts are retained."""

    role = (logical_role or "").strip().lower()
    if role in {"raw", "attempt", "scratch"}:
        days = max(1, int(settings.artifact_raw_retention_days))
        current = now or datetime.now(UTC)
        if current.tzinfo is None:
            current = current.replace(tzinfo=UTC)
        return current + timedelta(days=days)
    return None


async def expire_artifacts(
    pool: PgPool,
    object_store: ObjectStore | None,
    *,
    now: datetime | None = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    """Delete expired objects and their provenance rows.

    Selected/final artifacts have ``expires_at IS NULL`` and are never swept.
    """

    current = now or datetime.now(UTC)
    expired: list[dict[str, Any]] = []
    async with pool.acquire() as conn, conn.transaction():
        rows = await conn.fetch(
            """
            SELECT id, uri, logical_role, sha256
            FROM artifacts
            WHERE expires_at IS NOT NULL AND expires_at < $1
            ORDER BY expires_at ASC
            FOR UPDATE SKIP LOCKED
            LIMIT $2
            """,
            current,
            limit,
        )
        for row in rows:
            uri = str(row["uri"])
            if object_store is not None:
                with suppress(FileNotFoundError):
                    await object_store.delete(uri)
            await conn.execute("DELETE FROM artifacts WHERE id = $1", row["id"])
            expired.append(
                {
                    "id": str(row["id"]),
                    "uri": uri,
                    "logical_role": row["logical_role"],
                    "sha256": row["sha256"],
                }
            )
    return expired


async def get_artifact(pool: PgPool, artifact_id: UUID) -> dict[str, Any] | None:
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM artifacts WHERE id = $1", artifact_id)
    return dict(row) if row is not None else None


__all__ = ["expire_artifacts", "expiry_for_role", "get_artifact"]
