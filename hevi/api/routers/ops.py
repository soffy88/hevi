"""Agent 画布操作桥 HTTP 端点（单元 C）。

  - ``GET  /api/ops``            列出全部 8 个操作描述符（字段齐全）。
  - ``POST /api/ops/{name}``     执行单个操作（CAS + 幂等 + read-only 闸 + 付费 propose 闸）。

存储层用真实 SQLite（``SqliteOperationsStore``，离线、无 mock、无网络出站）。
会话模式由查询参数 ``mode=read-only|read-write`` 决定（默认 read-write）。
"""

from __future__ import annotations

import os
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from hevi.auth.dependencies import get_current_user
from hevi.operations.bridge import OperationBridge, OperationError, SqliteOperationsStore
from hevi.operations.registry import get_operation, list_operations

router = APIRouter(prefix="/api/ops", tags=["agent-ops"])


def _db_path() -> str:
    return os.getenv("HEVI_AGENT_OPS_DB", "data/agent_ops.db")


def _get_store() -> SqliteOperationsStore:
    # 真实存储层（sqlite/WAL）；每次请求一个轻量连接——单写者串行化，安全。
    return SqliteOperationsStore(_db_path())


def _get_bridge(mode: str) -> OperationBridge:
    read_only = mode == "read-only"
    return OperationBridge(_get_store(), read_only=read_only)


class ExecuteRequest(BaseModel):
    """操作执行请求体。写操作需 ``expectedRevision``(CAS) + ``opId``(幂等)。"""

    params: dict[str, Any] = Field(default_factory=dict)
    opId: str | None = None
    expectedRevision: int | None = None


@router.get("")
async def list_ops() -> dict[str, Any]:
    """验收 1：返回 8 个描述符且字段齐全。"""
    ops = [d.to_dict() for d in list_operations()]
    read_only_names = sorted(o["name"] for o in ops if o["readOnly"])
    return {
        "count": len(ops),
        "read_only_operations": read_only_names,
        "operations": ops,
    }


@router.post("/{name}")
async def execute_op(
    name: str,
    body: ExecuteRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    mode: Annotated[str, Query(description="会话模式: read-only | read-write")] = "read-write",
) -> dict[str, Any]:
    desc = get_operation(name)
    if desc is None:
        raise HTTPException(status_code=404, detail={"error": "unknown_operation", "name": name})
    bridge = _get_bridge(mode)

    # 写操作的 expectedRevision 通过 params 传入（CAS 检查在 bridge 内）。
    params = dict(body.params)
    if body.expectedRevision is not None:
        params.setdefault("expectedRevision", body.expectedRevision)

    try:
        result = await bridge.execute(name, params, op_id=body.opId)
    except OperationError as exc:
        # 幂等/冲突/CAS/校验失败 → 对应状态码。
        status = exc.status
        detail = exc.detail
        if isinstance(detail, dict):
            detail = {**detail, "error": exc.code}
        else:
            detail = {"error": exc.code, "detail": detail}
        raise HTTPException(status_code=status, detail=detail) from exc

    # read-only 会话写操作被拒 → scope_denied（验收 4）。
    if result.get("error") == "scope_denied":
        raise HTTPException(status_code=403, detail=result)

    # 幂等重放命中：回执与首次相同，replayed: true（验收 2）。
    status = 200
    if result.get("replayed"):
        status = 200
    return result


@router.post("/{name}/confirm", deprecated=True)
async def confirm_proposal(
    name: str,
    body: ExecuteRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    """确认 propose 的本地 stub 提交（零费用、不调云 provider）。

    仅 ``canvas.generation.propose`` 的确认路径：把 proposalId 交给既有任务接口
    （``SqliteOperationsStore.create_task`` 即本地 stub provider 落库），验证可提交。
    """
    if name != "canvas.generation.propose":
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_confirm_target", "name": name},
        )
    store = _get_store()
    proposal_id = body.params.get("proposalId")
    if not proposal_id:
        raise HTTPException(status_code=400, detail={"error": "proposalId_required"})
    proposal = await store.get_proposal(proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail={"error": "proposal_not_found"})
    # 既有任务接口（本地 stub provider，零费用）→ 新建任务行。
    task_id = str(UUID(int=0)) if False else __import__("uuid").uuid4().hex
    await store.create_task(
        task_id,
        {
            "source": "agent.propose.confirm",
            "proposal_id": proposal_id,
            "prompt": proposal["payload"].get("prompt"),
            "rows": proposal["payload"].get("rows"),
            "provider": "local_stub",
            "cost_usd": 0.0,
        },
    )
    return {"task_id": task_id, "status": "submitted", "provider": "local_stub", "cost_usd": 0.0}


__all__ = ["router"]
