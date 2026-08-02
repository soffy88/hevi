"""Project adapter runs into the shared ``video_tasks`` status surface.

Adapters keep their rich planning state in ``automation_runs`` but expose one
small execution record so the task list can show progress and final media for
every production mode.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from hevi.tasks.repository import TaskRepository


async def create_projection(
    repo: TaskRepository,
    *,
    user_id: str,
    topic: str,
    source: str,
    duration_archetype: str = "1-5min",
    video_provider: str = "adapter",
    audio_provider: str = "adapter",
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = datetime.now(UTC).replace(tzinfo=None)
    return await repo.create_task(
        {
            "id": uuid.uuid4(),
            "topic": topic,
            "duration_archetype": duration_archetype,
            "video_provider": video_provider,
            "audio_provider": audio_provider,
            "status": "pending",
            "progress_pct": 0.0,
            "total_shots": 0,
            "completed_shots": 0,
            "result_video_path": None,
            "error": None,
            "config_json": {"production_source": source, **(config or {})},
            "created_at": now,
            "updated_at": now,
            "user_id": user_id,
        }
    )


async def update_projection(
    repo: TaskRepository,
    task_id: str | uuid.UUID,
    *,
    status: str,
    progress_pct: float | None = None,
    result_video_path: str | None = None,
    error: str | None = None,
) -> None:
    values: dict[str, Any] = {
        "status": status,
        "updated_at": datetime.now(UTC).replace(tzinfo=None),
    }
    if progress_pct is not None:
        values["progress_pct"] = progress_pct
    if result_video_path is not None:
        values["result_video_path"] = result_video_path
    if error is not None:
        values["error"] = error
    await repo.update_task(uuid.UUID(str(task_id)), values)
