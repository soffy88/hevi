from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from obase.persistence import PgPool
from pydantic import BaseModel

from hevi.auth.dependencies import get_current_user
from hevi.canvas.executor_service import ExecutorService
from hevi.canvas.graph_repository import GraphRepository
from hevi.canvas.graph_service import GraphService
from hevi.db.pg_pool import get_hevi_pg_pool

router = APIRouter(prefix="/canvas", tags=["canvas"])


async def _load_owned_graph(
    graph_id: str, svc: GraphService, user: dict[str, Any]
) -> dict[str, Any]:
    """Load a graph and 404 if it doesn't exist or belongs to another user
    (legacy rows with no owner stay accessible)."""
    graph = await svc.load_graph(graph_id)
    if graph is None:
        raise HTTPException(status_code=404, detail="Graph not found")
    if graph.get("user_id") and graph["user_id"] != str(user["id"]):
        raise HTTPException(status_code=404, detail="Graph not found")
    return graph


def _serialize_graph(g: dict[str, Any]) -> dict[str, Any]:
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


async def _do_save_graph(
    body: SaveGraphRequest, svc: GraphService, user: dict[str, Any]
) -> dict[str, Any]:
    return _serialize_graph(await svc.save_graph(
        name=body.name, description=body.description,
        nodes=body.nodes, edges=body.edges,
        user_id=str(user["id"]),  # owner is the authenticated user
    ))


async def _do_list_graphs(svc: GraphService, user: dict[str, Any]) -> list[dict[str, Any]]:
    return [_serialize_graph(g) for g in await svc.list_graphs(user_id=str(user["id"]))]


async def _do_get_graph(
    graph_id: str, svc: GraphService, user: dict[str, Any]
) -> dict[str, Any]:
    return _serialize_graph(await _load_owned_graph(graph_id, svc, user))


async def _do_update_graph(
    graph_id: str, body: UpdateGraphRequest, svc: GraphService, user: dict[str, Any]
) -> dict[str, Any]:
    await _load_owned_graph(graph_id, svc, user)
    result = await svc.update_graph(
        graph_id, name=body.name, description=body.description,
        nodes=body.nodes, edges=body.edges,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Graph not found")
    return _serialize_graph(result)


async def _do_delete_graph(
    graph_id: str, svc: GraphService, user: dict[str, Any]
) -> dict[str, str]:
    await _load_owned_graph(graph_id, svc, user)
    deleted = await svc.delete_graph(graph_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Graph not found")
    return {"status": "deleted", "graph_id": graph_id}


async def _do_execute_graph(
    graph_id: str,
    body: ExecuteGraphRequest,
    exe: ExecutorService,
    svc: GraphService,
    user: dict[str, Any],
) -> dict[str, Any]:
    await _load_owned_graph(graph_id, svc, user)  # owner check before spending resources
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
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    svc: Annotated[GraphService, Depends(get_graph_service)],
) -> dict[str, Any]:
    return await _do_save_graph(body, svc, user)


@router.get("")
async def list_graphs(
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    svc: Annotated[GraphService, Depends(get_graph_service)],
) -> list[dict[str, Any]]:
    return await _do_list_graphs(svc, user)


# ── Legacy /graphs/* aliases (must come before /{graph_id}) ──────────────────


@router.post("/graphs", status_code=201)
async def save_graph_legacy(
    body: SaveGraphRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    svc: Annotated[GraphService, Depends(get_graph_service)],
) -> dict[str, Any]:
    return await _do_save_graph(body, svc, user)


@router.get("/graphs")
async def list_graphs_legacy(
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    svc: Annotated[GraphService, Depends(get_graph_service)],
) -> list[dict[str, Any]]:
    return await _do_list_graphs(svc, user)


@router.get("/graphs/{graph_id}")
async def get_graph_legacy(
    graph_id: str,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    svc: Annotated[GraphService, Depends(get_graph_service)],
) -> dict[str, Any]:
    return await _do_get_graph(graph_id, svc, user)


@router.patch("/graphs/{graph_id}")
async def update_graph_legacy(
    graph_id: str,
    body: UpdateGraphRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    svc: Annotated[GraphService, Depends(get_graph_service)],
) -> dict[str, Any]:
    return await _do_update_graph(graph_id, body, svc, user)


@router.delete("/graphs/{graph_id}", status_code=200)
async def delete_graph_legacy(
    graph_id: str,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    svc: Annotated[GraphService, Depends(get_graph_service)],
) -> dict[str, str]:
    return await _do_delete_graph(graph_id, svc, user)


@router.post("/graphs/{graph_id}/execute")
async def execute_graph_legacy(
    graph_id: str,
    body: ExecuteGraphRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    exe: Annotated[ExecutorService, Depends(get_executor_service)],
    svc: Annotated[GraphService, Depends(get_graph_service)],
) -> dict[str, Any]:
    return await _do_execute_graph(graph_id, body, exe, svc, user)


# ── Parameterised routes (after fixed-path aliases) ───────────────────────────


@router.get("/{graph_id}")
async def get_graph(
    graph_id: str,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    svc: Annotated[GraphService, Depends(get_graph_service)],
) -> dict[str, Any]:
    return await _do_get_graph(graph_id, svc, user)


@router.patch("/{graph_id}")
async def update_graph(
    graph_id: str,
    body: UpdateGraphRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    svc: Annotated[GraphService, Depends(get_graph_service)],
) -> dict[str, Any]:
    return await _do_update_graph(graph_id, body, svc, user)


@router.delete("/{graph_id}", status_code=200)
async def delete_graph(
    graph_id: str,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    svc: Annotated[GraphService, Depends(get_graph_service)],
) -> dict[str, str]:
    return await _do_delete_graph(graph_id, svc, user)


@router.post("/{graph_id}/execute")
async def execute_graph(
    graph_id: str,
    body: ExecuteGraphRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    exe: Annotated[ExecutorService, Depends(get_executor_service)],
    svc: Annotated[GraphService, Depends(get_graph_service)],
) -> dict[str, Any]:
    return await _do_execute_graph(graph_id, body, exe, svc, user)
