"""Freezone 无限画布 API — 节点图 CRUD + 执行 + 候选提升。

内存态(tongjian _RUNS 模式),后续可持久化。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from hevi.freezone import FreezoneGraph, FreezoneService, NodeSpec

router = APIRouter(prefix="/freezone", tags=["freezone"])

# 单例服务(装配层:可注入真实生成器)
_freezone = FreezoneService()
# 内存图库: graph_id -> FreezoneGraph
_GRAPHS: dict[str, FreezoneGraph] = {}


class NodeIn(BaseModel):
    id: str
    kind: str
    params: dict[str, Any] = Field(default_factory=dict)
    inputs: list[str] = Field(default_factory=list)


class GraphIn(BaseModel):
    nodes: list[NodeIn]


class PromoteIn(BaseModel):
    target: str


@router.post("/graphs")
async def create_graph(body: GraphIn) -> dict[str, Any]:
    graph = FreezoneGraph(
        [NodeSpec(id=n.id, kind=n.kind, params=n.params, inputs=n.inputs)
         for n in body.nodes])
    gid = f"fzg_{len(_GRAPHS) + 1}"
    _GRAPHS[gid] = graph
    return {"graph_id": gid, "nodes": graph.to_dict()["nodes"]}


@router.post("/graphs/{graph_id}/run")
async def run_graph(graph_id: str) -> dict[str, Any]:
    graph = _GRAPHS.get(graph_id)
    if graph is None:
        raise HTTPException(404, "graph 不存在")
    run = await _freezone.run_graph(graph)
    return run.to_dict()


@router.get("/graphs/{graph_id}")
async def get_graph(graph_id: str) -> dict[str, Any]:
    graph = _GRAPHS.get(graph_id)
    if graph is None:
        raise HTTPException(404, "graph 不存在")
    return graph.to_dict()


@router.get("/candidates")
async def list_candidates(status: str | None = None) -> list[dict[str, Any]]:
    return [c.to_dict() for c in _freezone.pool.list(status=status)]


@router.post("/candidates/{candidate_id}/promote")
async def promote_candidate(candidate_id: str, body: PromoteIn) -> dict[str, Any]:
    ok = _freezone.promote(candidate_id, body.target)
    if not ok:
        raise HTTPException(409, "候选不存在或已处理")
    return {"ok": True, "candidate_id": candidate_id, "target": body.target}


@router.post("/candidates/{candidate_id}/reject")
async def reject_candidate(candidate_id: str) -> dict[str, Any]:
    ok = _freezone.reject(candidate_id)
    if not ok:
        raise HTTPException(409, "候选不存在或已处理")
    return {"ok": True, "candidate_id": candidate_id}
