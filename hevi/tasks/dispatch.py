"""Execution dispatch boundary used by API compatibility routes.

PostgreSQL tasks are already durable queue entries and must never execute in
the API process.  Non-PostgreSQL repositories are deliberately limited to
local/test compatibility, where an in-process runner is still useful.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from obase.persistence import PgPool

from hevi.core.config import settings


class TaskServiceLike(Protocol):
    repository: Any

    async def run_task(self, task_id: uuid.UUID) -> dict[str, Any]: ...


class BackgroundTaskSink(Protocol):
    def add_task(self, func: Callable[..., Awaitable[Any]], *args: Any, **kwargs: Any) -> None: ...


async def run_local_compat(service: TaskServiceLike, task_id: uuid.UUID) -> dict[str, Any]:
    """Run only a non-PostgreSQL compatibility task in-process."""

    if isinstance(service.repository.pool, PgPool) and not settings.debug:
        raise RuntimeError("PostgreSQL tasks must run in hevi-worker")
    return await service.run_task(task_id)


def schedule_local_compat(
    sink: BackgroundTaskSink, service: TaskServiceLike, task_id: uuid.UUID
) -> bool:
    """Schedule a local compatibility task; return whether it was scheduled."""

    if isinstance(service.repository.pool, PgPool) and not settings.debug:
        return False
    sink.add_task(run_local_compat, service, task_id)
    return True


__all__ = ["run_local_compat", "schedule_local_compat"]
