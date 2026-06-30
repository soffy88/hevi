"""MCP tool: execute_canvas — wraps P11.D ExecutorService."""

from __future__ import annotations

from typing import Any

from obase.mcp_server import SkillDef
from obase.persistence import PgPool

from hevi.canvas.executor_service import ExecutorService
from hevi.canvas.graph_repository import GraphRepository
from hevi.canvas.graph_service import GraphService
from hevi.core.config import settings
from hevi.mcp.schemas import EXECUTE_CANVAS_INPUT, EXECUTE_CANVAS_OUTPUT


def build_canvas_skills(executor_svc: ExecutorService | None = None) -> list[SkillDef]:
    async def _get_svc() -> ExecutorService:
        if executor_svc is not None:
            return executor_svc
        pool = await PgPool.get_or_create(dsn=settings.database_url)
        return ExecutorService(GraphService(GraphRepository(pool)))

    async def _handler(args: dict[str, Any]) -> dict[str, Any]:
        svc = await _get_svc()
        return await svc.execute_graph(
            args["graph_id"],
            on_error=args.get("on_error", "rollback"),
        )

    return [
        SkillDef(
            name="hevi.execute_canvas",
            description="AI执行画布工作流，运行有向图节点管线并返回每节点结果",
            input_schema=EXECUTE_CANVAS_INPUT,
            output_schema=EXECUTE_CANVAS_OUTPUT,
            handler=_handler,
        )
    ]
