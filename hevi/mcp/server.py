"""hevi MCP server — registers all hevi skills via obase.mcp_server."""

from __future__ import annotations

from typing import Any

from obase.mcp_server import MCPServer, SkillDef

from hevi.canvas.executor_service import ExecutorService
from hevi.creative.assist_registry import ASSIST_REGISTRY
from hevi.creative.assist_service import AssistService
from hevi.creative.workflow_service import WorkflowService
from hevi.mcp.schemas import LIST_CAPABILITIES_INPUT, LIST_CAPABILITIES_OUTPUT
from hevi.mcp.tools.canvas_tools import build_canvas_skills
from hevi.mcp.tools.creative_tools import build_creative_skills
from hevi.mcp.tools.subject_tools import build_subject_skills
from hevi.mcp.tools.video_tools import build_video_skills
from hevi.subjects.subject_service import SubjectService


def build_hevi_mcp_server(
    *,
    subject_svc: SubjectService | None = None,
    executor_svc: ExecutorService | None = None,
    assist_svc: AssistService | None = None,
    workflow_svc: WorkflowService | None = None,
) -> MCPServer:
    """Build and return a fully registered hevi MCPServer.

    All service arguments are optional. When None, production services are
    created lazily on first call (using PgPool.get_or_create).  Pass mock
    services in tests to avoid real DB/LLM connections.
    """
    server = MCPServer(name="hevi", version="6.0.0")

    async def _list_capabilities(args: dict[str, Any]) -> dict[str, Any]:
        return {"capabilities": ASSIST_REGISTRY, "count": len(ASSIST_REGISTRY)}

    server.register_skill(
        SkillDef(
            name="hevi.list_capabilities",
            description="发现 hevi 可用的 AI 创意辅助能力清单",
            input_schema=LIST_CAPABILITIES_INPUT,
            output_schema=LIST_CAPABILITIES_OUTPUT,
            handler=_list_capabilities,
        )
    )

    for skill in build_video_skills():
        server.register_skill(skill)

    for skill in build_creative_skills(
        assist_svc=assist_svc, workflow_svc=workflow_svc
    ):
        server.register_skill(skill)

    for skill in build_subject_skills(subject_svc=subject_svc):
        server.register_skill(skill)

    for skill in build_canvas_skills(executor_svc=executor_svc):
        server.register_skill(skill)

    return server
