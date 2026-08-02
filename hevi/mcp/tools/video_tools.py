"""MCP tool: generate_longvideo — creates a durable automatic production task."""

from __future__ import annotations

import asyncio
from typing import Any

from obase.mcp_server import SkillDef
from obase.persistence import PgPool

from hevi.core.config import settings
from hevi.credits.account_service import AccountService
from hevi.credits.billing_service import BillingService
from hevi.credits.repository import CreditRepository
from hevi.mcp.auth_context import require_mcp_actor
from hevi.mcp.schemas import GENERATE_LONGVIDEO_INPUT, GENERATE_LONGVIDEO_OUTPUT
from hevi.production.contracts import ProductionRequest
from hevi.tasks.repository import TaskRepository
from hevi.tasks.task_service import TaskService

_DURATION_ALIASES = {
    "short": "short",
    "medium": "5-15min",
    "long": "15-45min",
}
_VIDEO_PROVIDER_ALIASES = {"wan": "wan_local", "ltx": "ltx2_local"}
_AUDIO_PROVIDER_ALIASES = {"tts": "edge_tts"}
_BACKGROUND_RUNS: set[asyncio.Task[Any]] = set()


def build_video_skills(task_svc: TaskService | None = None) -> list[SkillDef]:
    async def _get_task_service() -> TaskService:
        if task_svc is not None:
            return task_svc
        pool = await PgPool.get_or_create(dsn=settings.database_url)
        return TaskService(
            TaskRepository(pool),
            BillingService(AccountService(CreditRepository(pool))),
        )

    async def _handler(args: dict[str, Any]) -> dict[str, Any]:
        svc = await _get_task_service()
        user_id = require_mcp_actor()
        request = ProductionRequest(
            source="automatic",
            topic=args["topic"],
            duration_archetype=_DURATION_ALIASES.get(
                args["duration_archetype"], args["duration_archetype"]
            ),
            video_provider=_VIDEO_PROVIDER_ALIASES.get(
                args["video_provider"], args["video_provider"]
            ),
            audio_provider=_AUDIO_PROVIDER_ALIASES.get(
                args["audio_provider"], args["audio_provider"]
            ),
            options={
                "style": args.get("style", "cinematic"),
                "language": args.get("language", "zh"),
            },
        )
        task = await svc.create_production(request, user_id=user_id)
        task = await svc.submit_task(task["id"])
        if task.get("status") != "queued":
            background_run = asyncio.create_task(svc.run_task_background(task["id"]))
            _BACKGROUND_RUNS.add(background_run)
            background_run.add_done_callback(_BACKGROUND_RUNS.discard)
        task_id = str(task["id"])
        return {
            "task_id": task_id,
            "status": task.get("status", "pending"),
            "progress_pct": task.get("progress_pct", 0),
            "production_source": "automatic",
            "status_url": f"/api/tasks/{task_id}",
        }

    return [
        SkillDef(
            name="hevi.generate_longvideo",
            description="创建可查询、可下载的长视频生产任务",
            input_schema=GENERATE_LONGVIDEO_INPUT,
            output_schema=GENERATE_LONGVIDEO_OUTPUT,
            handler=_handler,
        )
    ]
