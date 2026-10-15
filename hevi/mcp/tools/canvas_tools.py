"""MCP tool: hevi.agent.ops — Agent 画布操作桥（只读 + 写 + 付费 propose 闸）。

经 MCP 暴露单元 C 的 8 个操作描述符与执行入口。复用 ``hevi/operations`` 真实
存储层（``SqliteOperationsStore``，离线、无 mock），并同时保留既有
``hevi.execute_canvas``（P11.D 图执行）。
"""

from __future__ import annotations

import os
from typing import Any

from obase.mcp_server import SkillDef

from hevi.mcp.schemas import EXECUTE_CANVAS_INPUT, EXECUTE_CANVAS_OUTPUT
from hevi.operations.bridge import OperationBridge, SqliteOperationsStore
from hevi.operations.registry import list_operations


def _store() -> SqliteOperationsStore:
    return SqliteOperationsStore(os.getenv("HEVI_AGENT_OPS_DB", "data/agent_ops.db"))


def _ops_input_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "enum": [d.name for d in list_operations()],
                "description": "操作名（见 /api/ops 描述符列表）",
            },
            "params": {"type": "object", "description": "操作入参（JSON Schema 见描述符.params）"},
            "opId": {
                "type": "string",
                "description": "幂等键：同 opId+同参数重放返回首次回执；同 opId 不同参数会被拒绝",
            },
            "expectedRevision": {
                "type": "integer",
                "description": "写操作 CAS：与画布当前 revision 不一致返回 409",
            },
            "mode": {
                "type": "string",
                "enum": ["read-write", "read-only"],
                "default": "read-write",
                "description": "会话模式；read-only 拒绝一切写操作",
            },
        },
        "required": ["name", "params"],
    }


def _ops_output_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "operation": {"type": "string"},
            "revision": {"type": "integer"},
            "replayed": {"type": "boolean", "description": "幂等重放命中时为 true"},
            "proposalId": {"type": "string", "description": "仅 propose 返回"},
            "error": {"type": "string"},
        },
    }


def _list_output_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "count": {"type": "integer"},
            "read_only_operations": {"type": "array", "items": {"type": "string"}},
            "operations": {"type": "array"},
        },
    }


def build_canvas_skills(executor_svc: Any = None) -> list[SkillDef]:
    """既有画布工作流执行能力（单技能保持向后兼容）。"""

    async def _get_svc():
        from hevi.canvas.executor_service import ExecutorService
        from hevi.canvas.graph_repository import GraphRepository
        from hevi.canvas.graph_service import GraphService
        from hevi.core.config import settings
        from obase.persistence import PgPool

        if executor_svc is not None:
            return executor_svc
        pool = await PgPool.get_or_create(dsn=settings.database_url)
        return ExecutorService(GraphService(GraphRepository(pool)))

    async def _execute_canvas(args: dict[str, Any]) -> dict[str, Any]:
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
            handler=_execute_canvas,
        ),
    ]


def build_canvas_ops_skills() -> list[SkillDef]:
    """单元 C：Agent 画布操作桥 MCP 技能（list + execute）。"""

    async def _list_ops(args: dict[str, Any]) -> dict[str, Any]:
        return {
            "count": len(list_operations()),
            "read_only_operations": sorted(d.name for d in list_operations() if d.read_only),
            "operations": [d.to_dict() for d in list_operations()],
        }

    async def _run_op(args: dict[str, Any]) -> dict[str, Any]:
        from hevi.operations.bridge import OperationError

        bridge = OperationBridge(
            _store(), read_only=(args.get("mode", "read-write") == "read-only")
        )
        params = dict(args.get("params", {}))
        if args.get("expectedRevision") is not None:
            params.setdefault("expectedRevision", args["expectedRevision"])
        try:
            result = await bridge.execute(
                args["name"], params, op_id=args.get("opId")
            )
        except OperationError as exc:
            return {"operation": args["name"], "error": exc.code, "detail": exc.detail}
        return result

    return [
        SkillDef(
            name="hevi.agent.ops.list",
            description="列出 Agent 画布操作桥的全部操作描述符（readOnly/scope/params/replay）",
            input_schema={"type": "object", "properties": {}},
            output_schema=_list_output_schema(),
            handler=_list_ops,
        ),
        SkillDef(
            name="hevi.agent.ops.execute",
            description=(
                "执行一个 Agent 画布操作（canvas.get / script.rows.* / node.bind_asset / "
                "generation.propose / asset.list / task.get）。写操作带 CAS(expectedRevision) "
                "与幂等(opId)；generation.propose 只返回 proposalId 不触发生成。"
            ),
            input_schema=_ops_input_schema(),
            output_schema=_ops_output_schema(),
            handler=_run_op,
        ),
    ]


__all__ = ["build_canvas_skills", "build_canvas_ops_skills"]
