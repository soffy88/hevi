"""Freezone 无限画布 API — 节点图 CRUD + 执行 + 候选提升。

All endpoints require authentication (get_current_user). Graphs and
candidates are tenant-scoped by user_id (cross-user access → 404).
State is persisted via FreezoneStateStore for FREEZONE_RESTART_RECOVERY.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from hevi.auth.dependencies import get_current_user
from hevi.freezone import FreezoneGraph, FreezoneService, NodeSpec
from hevi.freezone.store import FreezoneStateStore

router = APIRouter(prefix="/freezone", tags=["freezone"])

# 单例服务(装配层:可注入真实生成器);store 提供 FREEZONE_RESTART_RECOVERY
_freezone = FreezoneService(store=FreezoneStateStore.from_env())


class NodeIn(BaseModel):
    id: str
    kind: str
    params: dict[str, Any] = Field(default_factory=dict)
    inputs: list[str] = Field(default_factory=list)


class GraphIn(BaseModel):
    nodes: list[NodeIn]


class PromoteIn(BaseModel):
    target: str


def _uid(user: dict[str, Any]) -> str:
    return str(user.get("id") or "")


def _owned_graph(graph_id: str, user: dict[str, Any]) -> FreezoneGraph:
    graph = _freezone.get_owned_graph(graph_id, user_id=_uid(user))
    if graph is None:
        raise HTTPException(404, "graph 不存在")
    return graph


def _owned_candidate(candidate_id: str, user: dict[str, Any]) -> None:
    if not _freezone.pool.owned_by(candidate_id, _uid(user)):
        raise HTTPException(404, "候选不存在")


@router.post("/graphs")
async def create_graph(
    body: GraphIn,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    graph = FreezoneGraph(
        [NodeSpec(id=n.id, kind=n.kind, params=n.params, inputs=n.inputs) for n in body.nodes]
    )
    gid = _freezone.create_graph(graph, user_id=_uid(user))
    return {"graph_id": gid, "nodes": graph.to_dict()["nodes"]}


@router.post("/graphs/{graph_id}/run")
async def run_graph(
    graph_id: str,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    graph = _owned_graph(graph_id, user)
    run = await _freezone.run_graph(graph, user_id=_uid(user), graph_id=graph_id)
    return run.to_dict()


@router.get("/graphs/{graph_id}")
async def get_graph(
    graph_id: str,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    return _owned_graph(graph_id, user).to_dict()


@router.get("/candidates")
async def list_candidates(
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    status: str | None = None,
) -> list[dict[str, Any]]:
    return _freezone.list_candidates(status=status, user_id=_uid(user))


@router.post("/candidates/{candidate_id}/promote")
async def promote_candidate(
    candidate_id: str,
    body: PromoteIn,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    _owned_candidate(candidate_id, user)
    ok = _freezone.promote(candidate_id, body.target, user_id=_uid(user))
    if not ok:
        raise HTTPException(409, "候选不存在或已处理")
    return {"ok": True, "candidate_id": candidate_id, "target": body.target}


@router.post("/candidates/{candidate_id}/reject")
async def reject_candidate(
    candidate_id: str,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    _owned_candidate(candidate_id, user)
    ok = _freezone.reject(candidate_id, user_id=_uid(user))
    if not ok:
        raise HTTPException(409, "候选不存在或已处理")
    return {"ok": True, "candidate_id": candidate_id}
