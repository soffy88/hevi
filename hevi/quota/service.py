"""Durable public-beta quota enforcement.

Policy (operator-approved, S10):

* public beta is free and has no payment flow;
* a new account gets a signup credit grant (see ``AuthService``);
* each account may finish at most 5 films per day (Asia/Shanghai);
* one film may be at most 60 seconds;
* at most one production may run at a time per account.

``film_jobs`` rows are reservations.  ``reserve`` serialises per user with a
transaction-scoped advisory lock, so two concurrent API requests cannot both
pass the daily/concurrency checks.  A reservation that never terminates (API
crash, killed worker) is expired after ``STALE_AFTER`` and stops blocking the
user.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from obase.persistence import PgPool, transaction

# Whole seconds, kept module-level so tests and docs can assert the policy.
BETA_DAILY_FILMS = 5
BETA_MAX_DURATION_S = 60
BETA_MAX_CONCURRENT = 1

# A reservation older than this is treated as abandoned.  A beta film is capped
# at 60 s, so two hours is generous even for a slow local render.
STALE_AFTER = timedelta(hours=2)

_DAY_SQL = "(created_at AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Shanghai')::date"

# Used to reject long requests before any work is queued.  Values are the
# minimum runtime of each archetype; anything above 60 s is out of beta scope.
_DURATION_ARCHETYPE_SECONDS = {
    "short": 10,
    "1-5min": 180,
    "5-15min": 300,
    "15-45min": 900,
    "45min+": 2700,
    "60s": 60,
}


def beta_free_enabled() -> bool:
    return os.getenv("HEVI_BETA_FREE", "1").strip().lower() not in ("0", "false", "no", "off")


def _daily_limit() -> int:
    try:
        return max(1, int(os.getenv("HEVI_BETA_DAILY_FILMS", str(BETA_DAILY_FILMS))))
    except ValueError:
        return BETA_DAILY_FILMS


def _max_duration() -> int:
    try:
        return max(1, int(os.getenv("HEVI_BETA_MAX_DURATION_S", str(BETA_MAX_DURATION_S))))
    except ValueError:
        return BETA_MAX_DURATION_S


def resolve_max_duration_s() -> int:
    return _max_duration()


def _max_concurrent() -> int:
    try:
        return max(1, int(os.getenv("HEVI_BETA_MAX_CONCURRENT", str(BETA_MAX_CONCURRENT))))
    except ValueError:
        return BETA_MAX_CONCURRENT


class QuotaError(Exception):
    """A user-facing refusal; ``status_code`` is the HTTP status to return."""

    def __init__(self, message: str, *, code: str, status_code: int = 429) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code

    def detail(self) -> dict[str, Any]:
        return {
            "error": self.code,
            "message": self.message,
            "daily_limit": _daily_limit(),
            "max_duration_s": _max_duration(),
            "max_concurrent": _max_concurrent(),
        }


def requested_duration_seconds(
    *, duration_s: float | None = None, duration_archetype: str | None = None
) -> float | None:
    if duration_s is not None:
        try:
            return float(duration_s)
        except (TypeError, ValueError):
            return None
    if duration_archetype:
        return float(_DURATION_ARCHETYPE_SECONDS.get(str(duration_archetype), 0) or 0)
    return None


class QuotaService:
    def __init__(self, pool: PgPool) -> None:
        self._pool = pool

    async def _expire_stale(self, user_id: str) -> None:
        cutoff = datetime.now(UTC).replace(tzinfo=None) - STALE_AFTER
        async with transaction(self._pool) as tx:
            await tx.execute(
                "UPDATE film_jobs SET status='failed', finished_at=now(), "
                "failure_reason='stale reservation expired' "
                "WHERE user_id=$1 AND status='running' AND created_at < $2",
                user_id,
                cutoff,
            )

    async def _sync_finished_tasks(self, user_id: str) -> None:
        """Close reservations whose background task already reached a terminal state."""
        async with transaction(self._pool) as tx:
            await tx.execute(
                "UPDATE film_jobs j SET status = "
                "CASE WHEN t.status='completed' THEN 'completed' ELSE 'failed' END, "
                "finished_at = now(), failure_reason = CASE WHEN t.status='completed' THEN NULL "
                "ELSE COALESCE(t.error,'task ' || t.status) END "
                "FROM video_tasks t "
                "WHERE j.user_id=$1 AND j.status='running' AND j.task_id IS NOT NULL "
                "AND t.id::text = j.task_id AND t.status IN ('completed','failed','cancelled','blocked')",
                user_id,
            )

    async def status(self, user_id: str) -> dict[str, Any]:
        if not isinstance(self._pool, PgPool):
            return self._empty_status()
        await self._sync_finished_tasks(user_id)
        rows = await self._query(
            "SELECT count(*) FILTER (WHERE status='completed' AND "
            f"{_DAY_SQL} = (now() AT TIME ZONE 'Asia/Shanghai')::date) AS used, "
            "count(*) FILTER (WHERE status='running') AS running "
            "FROM film_jobs WHERE user_id=$1",
            [user_id],
        )
        row = rows[0] if rows else {}
        used = int(row.get("used") or 0)
        running = int(row.get("running") or 0)
        limit = _daily_limit()
        return {
            "beta_free": beta_free_enabled(),
            "daily_limit": limit,
            "used_today": used,
            "remaining": max(0, limit - used),
            "max_duration_s": _max_duration(),
            "max_concurrent": _max_concurrent(),
            "active_jobs": running,
        }

    def _empty_status(self) -> dict[str, Any]:
        return {
            "beta_free": beta_free_enabled(),
            "daily_limit": _daily_limit(),
            "used_today": 0,
            "remaining": _daily_limit(),
            "max_duration_s": _max_duration(),
            "max_concurrent": _max_concurrent(),
            "active_jobs": 0,
        }

    async def _query(self, sql: str, params: list[Any]) -> list[dict[str, Any]]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
        return [dict(r) for r in rows]

    async def reserve(
        self,
        user_id: str,
        *,
        kind: str,
        counts_as_film: bool = True,
        task_id: str | None = None,
        duration_s: float | None = None,
        duration_archetype: str | None = None,
        job_id: str | None = None,
    ) -> str:
        """Check the beta policy and write a running reservation.

        Raises ``QuotaError`` (HTTP 422/429/409) with a friendly Chinese message
        when the request would exceed the duration, concurrency or daily limit.
        """
        if not beta_free_enabled() or not isinstance(self._pool, PgPool):
            # Local/test pools or an explicitly disabled beta keep the legacy
            # behaviour; production always has a real PostgreSQL pool.
            return job_id or uuid.uuid4().hex

        duration = requested_duration_seconds(
            duration_s=duration_s, duration_archetype=duration_archetype
        )
        if duration is not None and duration > _max_duration():
            raise QuotaError(
                f"公测期每条成片最长 {_max_duration()} 秒，当前请求约 {int(duration)} 秒。"
                "请缩短时长后再试。",
                code="duration_limit_exceeded",
                status_code=422,
            )

        await self._expire_stale(user_id)
        await self._sync_finished_tasks(user_id)
        job = job_id or uuid.uuid4().hex
        async with transaction(self._pool) as tx:
            # Serialise reservations for one user across API processes.
            await tx.execute("SELECT pg_advisory_xact_lock(hashtext($1))", f"quota:{user_id}")
            running = await tx.fetchval(
                "SELECT count(*) FROM film_jobs WHERE user_id=$1 AND status='running'",
                user_id,
            )
            if int(running or 0) >= _max_concurrent():
                raise QuotaError(
                    "你还有一个任务正在进行，公测期每个账号同时只能运行 1 个任务。"
                    "请等它完成后再提交。",
                    code="concurrent_limit",
                    status_code=429,
                )
            used = await tx.fetchval(
                "SELECT count(*) FROM film_jobs WHERE user_id=$1 AND status='completed' "
                f"AND {_DAY_SQL} = (now() AT TIME ZONE 'Asia/Shanghai')::date",
                user_id,
            )
            if counts_as_film and int(used or 0) >= _daily_limit():
                raise QuotaError(
                    f"今天已生成 {_daily_limit()} 条成片，达到公测期每日上限。"
                    "明天再来，或先编辑已有作品。",
                    code="daily_limit_reached",
                    status_code=429,
                )
            await tx.execute(
                "INSERT INTO film_jobs (id, user_id, kind, status, counts_as_film, task_id, "
                "duration_s, created_at) VALUES ($1,$2,$3,'running',$4,$5,$6,now())",
                job,
                user_id,
                kind,
                counts_as_film,
                task_id,
                duration,
            )
        return job

    async def attach_task(self, job_id: str, task_id: str) -> None:
        """Link a reservation to the background task that will finish it."""
        if not job_id or not isinstance(self._pool, PgPool):
            return
        async with transaction(self._pool) as tx:
            await tx.execute(
                "UPDATE film_jobs SET task_id=$2 WHERE id=$1 AND status='running'",
                job_id,
                task_id,
            )

    async def complete(self, job_id: str, *, reason: str | None = None) -> None:
        if not job_id or not isinstance(self._pool, PgPool):
            return
        async with transaction(self._pool) as tx:
            await tx.execute(
                "UPDATE film_jobs SET status='completed', finished_at=now(), "
                "failure_reason=$2 WHERE id=$1 AND status='running'",
                job_id,
                reason,
            )

    async def release(self, job_id: str, *, reason: str | None = None) -> None:
        if not job_id or not isinstance(self._pool, PgPool):
            return
        async with transaction(self._pool) as tx:
            await tx.execute(
                "UPDATE film_jobs SET status='failed', finished_at=now(), "
                "failure_reason=$2 WHERE id=$1 AND status='running'",
                job_id,
                (reason or "released")[:500],
            )


_service_singleton: dict[int, QuotaService] = {}


def get_quota_service(pool: PgPool) -> QuotaService:
    key = id(pool)
    svc = _service_singleton.get(key)
    if svc is None or svc._pool is not pool:
        svc = QuotaService(pool)
        _service_singleton[key] = svc
    return svc
