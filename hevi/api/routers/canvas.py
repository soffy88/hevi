from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from obase.persistence import PgPool
from pydantic import BaseModel

from hevi.auth.dependencies import get_current_user
from hevi.canvas.executor_service import ExecutorService
from hevi.canvas.graph_repository import GraphRepository
from hevi.canvas.graph_service import GraphService
from hevi.db.pg_pool import get_hevi_pg_pool

router = APIRouter(prefix="/canvas", tags=["canvas"])

_MAX_REFERENCE_IMAGE_BYTES = 12 * 1024 * 1024  # 12MB,同 subjects.py 的参考图上限


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
    # 计划级自我批判(HEVI 路线图 Phase4 #44):不给就跳过预算/时长检查(向后兼容,
    # 不强制所有调用方都得算好这两个值才能执行)。
    budget_usd: float | None = None
    target_duration_s: float | None = None


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
    return _serialize_graph(
        await svc.save_graph(
            name=body.name,
            description=body.description,
            nodes=body.nodes,
            edges=body.edges,
            user_id=str(user["id"]),  # owner is the authenticated user
        )
    )


async def _do_list_graphs(svc: GraphService, user: dict[str, Any]) -> list[dict[str, Any]]:
    return [_serialize_graph(g) for g in await svc.list_graphs(user_id=str(user["id"]))]


async def _do_get_graph(graph_id: str, svc: GraphService, user: dict[str, Any]) -> dict[str, Any]:
    return _serialize_graph(await _load_owned_graph(graph_id, svc, user))


async def _do_update_graph(
    graph_id: str, body: UpdateGraphRequest, svc: GraphService, user: dict[str, Any]
) -> dict[str, Any]:
    await _load_owned_graph(graph_id, svc, user)
    result = await svc.update_graph(
        graph_id,
        name=body.name,
        description=body.description,
        nodes=body.nodes,
        edges=body.edges,
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
    from hevi.canvas.preflight import PreflightError

    await _load_owned_graph(graph_id, svc, user)  # owner check before spending resources
    try:
        return await exe.execute_graph(
            graph_id,
            on_error=body.on_error,
            budget_usd=body.budget_usd,
            target_duration_s=body.target_duration_s,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PreflightError as exc:
        raise HTTPException(status_code=402, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# ── Primary routes (frontend-compatible paths) ────────────────────────────────


@router.post("/reference-image", status_code=201)
async def upload_canvas_reference_image(
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    file: Annotated[UploadFile, File(description="i2v 参考图,不经过角色库")],
) -> dict[str, str]:
    """通用 i2v 参考图上传(HEVI 路线图 Phase1 #31)——canvas 节点图的 video 节点
    `config.reference_image` 字段一直有后端支持(node_mapper.py::_video_executor
    直接读取任意路径),但没有对应前端入口:此前只有走"角色库→选主体→自动锁 i2v"
    这一条路。这里补上"上传任意一张照片,不经过角色库,直接给这个节点做参考图"的
    独立入口——复用 ReferenceStore(同角色库参考图一样落盘),但用随机 id 命名空间,
    不写进任何 Subject 记录。
    """
    if not (file.content_type or "").startswith("image/"):
        raise HTTPException(status_code=422, detail="只接受图片文件")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=422, detail="空文件")
    if len(data) > _MAX_REFERENCE_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="图片过大(上限 12MB)")

    from hevi.subjects.reference_store import ReferenceStore

    namespace = f"canvas-{uuid.uuid4()}"
    path = ReferenceStore().save_upload(namespace, file.filename or "reference.png", data)
    return {"path": path}


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
