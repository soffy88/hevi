from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from obase.persistence import PgPool
from pydantic import BaseModel

from hevi.canvas.executor_service import ExecutorService
from hevi.canvas.graph_repository import GraphRepository
from hevi.canvas.graph_service import GraphService
from hevi.db.pg_pool import get_hevi_pg_pool

router = APIRouter(prefix="/canvas", tags=["canvas"])


def _serialize_graph(g: dict) -> dict:
    return {**g, "nodes": g.get("nodes_json", []), "edges": g.get("edges_json", [])}


# ── Request schemas ───────────────────────────────────────────────────────────


class SaveGraphRequest(BaseModel):
    name: str = "Untitled"
    description: str = ""
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    user_id: str | None = None


class UpdateGraphRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    nodes: list[dict[str, Any]] | None = None
    edges: list[dict[str, Any]] | None = None


class ExecuteGraphRequest(BaseModel):
    on_error: str = "rollback"


# ── Dependencies ──────────────────────────────────────────────────────────────


async def get_pg_pool() -> PgPool:
    return await get_hevi_pg_pool()


async def get_graph_service(
    pool: Annotated[PgPool, Depends(get_pg_pool)],
) -> GraphService:
    return GraphService(GraphRepository(pool))


async def get_executor_service(
    graph_svc: Annotated[GraphService, Depends(get_graph_service)],
) -> ExecutorService:
    return ExecutorService(graph_svc)


# ── Routes ────────────────────────────────────────────────────────────────────


async def _do_save_graph(body: SaveGraphRequest, svc: GraphService) -> dict[str, Any]:
    return _serialize_graph(await svc.save_graph(
        name=body.name, description=body.description,
        nodes=body.nodes, edges=body.edges, user_id=body.user_id,
    ))


async def _do_list_graphs(svc: GraphService, user_id: str | None) -> list[dict[str, Any]]:
    return [_serialize_graph(g) for g in await svc.list_graphs(user_id=user_id)]


async def _do_get_graph(graph_id: str, svc: GraphService) -> dict[str, Any]:
    graph = await svc.load_graph(graph_id)
    if graph is None:
        raise HTTPException(status_code=404, detail="Graph not found")
    return _serialize_graph(graph)


async def _do_update_graph(graph_id: str, body: UpdateGraphRequest, svc: GraphService) -> dict[str, Any]:
    result = await svc.update_graph(
        graph_id, name=body.name, description=body.description,
        nodes=body.nodes, edges=body.edges,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Graph not found")
    return _serialize_graph(result)


async def _do_delete_graph(graph_id: str, svc: GraphService) -> dict[str, str]:
    deleted = await svc.delete_graph(graph_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Graph not found")
    return {"status": "deleted", "graph_id": graph_id}


async def _do_execute_graph(graph_id: str, body: ExecuteGraphRequest, exe: ExecutorService) -> dict[str, Any]:
    try:
        return await exe.execute_graph(graph_id, on_error=body.on_error)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# ── Primary routes (frontend-compatible paths) ────────────────────────────────


@router.post("", status_code=201)
async def save_graph(
    body: SaveGraphRequest,
    svc: Annotated[GraphService, Depends(get_graph_service)],
) -> dict[str, Any]:
    return await _do_save_graph(body, svc)


@router.get("")
async def list_graphs(
    svc: Annotated[GraphService, Depends(get_graph_service)],
    user_id: str | None = None,
) -> list[dict[str, Any]]:
    return await _do_list_graphs(svc, user_id)


# ── Legacy /graphs/* aliases (must come before /{graph_id}) ──────────────────


@router.post("/graphs", status_code=201)
async def save_graph_legacy(
    body: SaveGraphRequest,
    svc: Annotated[GraphService, Depends(get_graph_service)],
) -> dict[str, Any]:
    return await _do_save_graph(body, svc)


@router.get("/graphs")
async def list_graphs_legacy(
    svc: Annotated[GraphService, Depends(get_graph_service)],
    user_id: str | None = None,
) -> list[dict[str, Any]]:
    return await _do_list_graphs(svc, user_id)


@router.get("/graphs/{graph_id}")
async def get_graph_legacy(
    graph_id: str,
    svc: Annotated[GraphService, Depends(get_graph_service)],
) -> dict[str, Any]:
    return await _do_get_graph(graph_id, svc)


@router.patch("/graphs/{graph_id}")
async def update_graph_legacy(
    graph_id: str,
    body: UpdateGraphRequest,
    svc: Annotated[GraphService, Depends(get_graph_service)],
) -> dict[str, Any]:
    return await _do_update_graph(graph_id, body, svc)


@router.delete("/graphs/{graph_id}", status_code=200)
async def delete_graph_legacy(
    graph_id: str,
    svc: Annotated[GraphService, Depends(get_graph_service)],
) -> dict[str, str]:
    return await _do_delete_graph(graph_id, svc)


@router.post("/graphs/{graph_id}/execute")
async def execute_graph_legacy(
    graph_id: str,
    body: ExecuteGraphRequest,
    exe: Annotated[ExecutorService, Depends(get_executor_service)],
) -> dict[str, Any]:
    return await _do_execute_graph(graph_id, body, exe)


# ── Parameterised routes (after fixed-path aliases) ───────────────────────────


@router.get("/{graph_id}")
async def get_graph(
    graph_id: str,
    svc: Annotated[GraphService, Depends(get_graph_service)],
) -> dict[str, Any]:
    return await _do_get_graph(graph_id, svc)


@router.patch("/{graph_id}")
async def update_graph(
    graph_id: str,
    body: UpdateGraphRequest,
    svc: Annotated[GraphService, Depends(get_graph_service)],
) -> dict[str, Any]:
    return await _do_update_graph(graph_id, body, svc)


@router.delete("/{graph_id}", status_code=200)
async def delete_graph(
    graph_id: str,
    svc: Annotated[GraphService, Depends(get_graph_service)],
) -> dict[str, str]:
    return await _do_delete_graph(graph_id, svc)


@router.post("/{graph_id}/execute")
async def execute_graph(
    graph_id: str,
    body: ExecuteGraphRequest,
    exe: Annotated[ExecutorService, Depends(get_executor_service)],
) -> dict[str, Any]:
    return await _do_execute_graph(graph_id, body, exe)
