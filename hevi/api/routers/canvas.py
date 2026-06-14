from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from obase.persistence import PgPool
from pydantic import BaseModel

from hevi.canvas.executor_service import ExecutorService
from hevi.canvas.graph_repository import GraphRepository
from hevi.canvas.graph_service import GraphService
from hevi.core.config import settings

router = APIRouter(prefix="/canvas", tags=["canvas"])


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


@router.post("/graphs", status_code=201)
async def save_graph(
    body: SaveGraphRequest,
    svc: Annotated[GraphService, Depends(get_graph_service)],
) -> dict[str, Any]:
    return await svc.save_graph(
        name=body.name,
        description=body.description,
        nodes=body.nodes,
        edges=body.edges,
        user_id=body.user_id,
    )


@router.get("/graphs")
async def list_graphs(
    svc: Annotated[GraphService, Depends(get_graph_service)],
    user_id: str | None = None,
) -> list[dict[str, Any]]:
    return await svc.list_graphs(user_id=user_id)


@router.get("/graphs/{graph_id}")
async def get_graph(
    graph_id: str,
    svc: Annotated[GraphService, Depends(get_graph_service)],
) -> dict[str, Any]:
    graph = await svc.load_graph(graph_id)
    if graph is None:
        raise HTTPException(status_code=404, detail="Graph not found")
    return graph


@router.patch("/graphs/{graph_id}")
async def update_graph(
    graph_id: str,
    body: UpdateGraphRequest,
    svc: Annotated[GraphService, Depends(get_graph_service)],
) -> dict[str, Any]:
    result = await svc.update_graph(
        graph_id,
        name=body.name,
        description=body.description,
        nodes=body.nodes,
        edges=body.edges,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Graph not found")
    return result


@router.delete("/graphs/{graph_id}", status_code=200)
async def delete_graph(
    graph_id: str,
    svc: Annotated[GraphService, Depends(get_graph_service)],
) -> dict[str, str]:
    deleted = await svc.delete_graph(graph_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Graph not found")
    return {"status": "deleted", "graph_id": graph_id}


@router.post("/graphs/{graph_id}/execute")
async def execute_graph(
    graph_id: str,
    body: ExecuteGraphRequest,
    exe: Annotated[ExecutorService, Depends(get_executor_service)],
) -> dict[str, Any]:
    try:
        return await exe.execute_graph(graph_id, on_error=body.on_error)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
c:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
