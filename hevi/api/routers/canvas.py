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


class WorkflowToGraphRequest(BaseModel):
    workflow: dict[str, Any]
    positions: dict[str, Any] | None = None


class GraphToWorkflowRequest(BaseModel):
    graph: dict[str, Any]
    include_position: bool = False


class PlannedGraphRequest(BaseModel):
    source: dict[str, Any]  # workflow dict or canvas graph dict
    selected_ids: list[str]


class WorkflowPreflightRequest(BaseModel):
    workflow: dict[str, Any]
    budget_usd: float | None = None
    target_duration_s: float | None = None


class WorkflowExecuteRequest(BaseModel):
    workflow: dict[str, Any]
    name: str = "Untitled"
    description: str = ""
    on_error: str = "rollback"
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


@router.post("/graphs", status_code=201, deprecated=True)
async def save_graph_legacy(
    body: SaveGraphRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    svc: Annotated[GraphService, Depends(get_graph_service)],
) -> dict[str, Any]:
    return await _do_save_graph(body, svc, user)


@router.get("/graphs", deprecated=True)
async def list_graphs_legacy(
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    svc: Annotated[GraphService, Depends(get_graph_service)],
) -> list[dict[str, Any]]:
    return await _do_list_graphs(svc, user)


@router.get("/graphs/{graph_id}", deprecated=True)
async def get_graph_legacy(
    graph_id: str,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    svc: Annotated[GraphService, Depends(get_graph_service)],
) -> dict[str, Any]:
    return await _do_get_graph(graph_id, svc, user)


@router.patch("/graphs/{graph_id}", deprecated=True)
async def update_graph_legacy(
    graph_id: str,
    body: UpdateGraphRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    svc: Annotated[GraphService, Depends(get_graph_service)],
) -> dict[str, Any]:
    return await _do_update_graph(graph_id, body, svc, user)


@router.delete("/graphs/{graph_id}", status_code=200, deprecated=True)
async def delete_graph_legacy(
    graph_id: str,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    svc: Annotated[GraphService, Depends(get_graph_service)],
) -> dict[str, str]:
    return await _do_delete_graph(graph_id, svc, user)


@router.post("/graphs/{graph_id}/execute", deprecated=True)
async def execute_graph_legacy(
    graph_id: str,
    body: ExecuteGraphRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    exe: Annotated[ExecutorService, Depends(get_executor_service)],
    svc: Annotated[GraphService, Depends(get_graph_service)],
) -> dict[str, Any]:
    return await _do_execute_graph(graph_id, body, exe, svc, user)


# ── Workflow adapter routes (M-14) ────────────────────────────────────────
# The workflow model (story.canvas_workflow) is a pure model: it never
# executes.  These routes are the product entry point for the adapter
# (hevi/canvas/workflow_adapter.py): workflow <-> canvas graph
# conversion, rerun planning, preflight, and execution — where
# execution is delegated to ExecutorService exactly like the
# hand-drawn graph path (save the converted graph, then execute it by
# id).  Async service execution is never squeezed into the
# Capability.render synchronous signature.  Placed before the
# parameterised /{graph_id} routes so the fixed paths cannot collide.

from hevi.canvas.workflow_adapter import (  # noqa: E402
    WorkflowAdapterError,
    canvas_edge_warnings,
    graph_to_workflow,
    plan_rerun,
    planned_graph,
    run_preflight_for_workflow,
    workflow_to_graph,
)
from hevi.capabilities.errors import CapabilityError as _CapabilityError  # noqa: E402


def _adapter_error_to_http(exc: Exception) -> HTTPException:
    if isinstance(exc, (_CapabilityError, WorkflowAdapterError, ValueError)):
        return HTTPException(status_code=422, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))


@router.post("/workflow-to-graph")
async def workflow_to_graph_endpoint(
    body: WorkflowToGraphRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    """Convert a story.canvas_workflow workflow to a canvas graph."""
    try:
        graph = workflow_to_graph(body.workflow, positions=body.positions)
        return {"graph": graph, "edge_warnings": canvas_edge_warnings(graph)}
    except Exception as exc:
        raise _adapter_error_to_http(exc) from exc


@router.post("/graph-to-workflow")
async def graph_to_workflow_endpoint(
    body: GraphToWorkflowRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    """Convert a canvas graph back to a story.canvas_workflow workflow."""
    try:
        return {"workflow": graph_to_workflow(body.graph, include_position=body.include_position)}
    except Exception as exc:
        raise _adapter_error_to_http(exc) from exc


@router.post("/planned-graph")
async def planned_graph_endpoint(
    body: PlannedGraphRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    """Rerun scope for a workflow/graph: planned graph + run/skip plan."""
    try:
        return {
            "graph": planned_graph(body.source, body.selected_ids),
            "plan": plan_rerun(body.source, body.selected_ids),
        }
    except Exception as exc:
        raise _adapter_error_to_http(exc) from exc


@router.post("/workflow-preflight")
async def workflow_preflight_endpoint(
    body: WorkflowPreflightRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    """Run the existing canvas preflight on a workflow (no execution)."""
    try:
        report = run_preflight_for_workflow(
            body.workflow,
            budget_usd=body.budget_usd,
            target_duration_s=body.target_duration_s,
        )
        if hasattr(report, "model_dump"):
            return report.model_dump()
        import dataclasses

        if dataclasses.is_dataclass(report):
            return dataclasses.asdict(report)
        return dict(report)
    except Exception as exc:
        raise _adapter_error_to_http(exc) from exc


@router.post("/workflow-execute")
async def workflow_execute_endpoint(
    body: WorkflowExecuteRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    svc: Annotated[GraphService, Depends(get_graph_service)],
    exe: Annotated[ExecutorService, Depends(get_executor_service)],
) -> dict[str, Any]:
    """Save a workflow as a canvas graph (owner = caller), then execute it.

    Execution is delegated to ExecutorService, the same path as a
    hand-drawn graph: the workflow itself is never executed inside
    the capability layer.
    """
    try:
        graph = workflow_to_graph(body.workflow)
    except Exception as exc:
        raise _adapter_error_to_http(exc) from exc
    saved = await svc.save_graph(
        name=body.name,
        description=body.description,
        nodes=graph["nodes"],
        edges=graph["edges"],
        user_id=str(user["id"]),
    )
    graph_id = saved.get("graph_id") or saved.get("id")
    if not graph_id:
        raise HTTPException(status_code=500, detail="graph save returned no id")
    return await _do_execute_graph(
        graph_id,
        ExecuteGraphRequest(
            on_error=body.on_error,
            budget_usd=body.budget_usd,
            target_duration_s=body.target_duration_s,
        ),
        exe,
        svc,
        user,
    )


# ── Material-pack routes (canvas.material_pack) ─────────────────────────
# A stable-film material pack mapped onto the canvas: one segment
# node per segment, asset nodes, continuation/reference edges, and
# the human edit loop (edit -> dirty/downstream review -> gates ->
# single-segment regeneration -> adopt as a new version). Placed
# before the parameterised /{graph_id} routes so the fixed paths
# cannot collide.


class MaterialPackGraphRequest(BaseModel):
    pack: dict[str, Any]
    existing_graph: dict[str, Any] | None = None
    pack_revision: int | None = None


class MaterialPackEditRequest(BaseModel):
    graph: dict[str, Any]
    segment_id: str
    patch: dict[str, Any]
    base_revision: int


class MaterialPackRegenerateRequest(BaseModel):
    graph: dict[str, Any]
    segment_id: str
    confirmed: Any = None
    smoke_passed: Any = False
    budget_usd: float | None = None
    estimated_unit_cost: Any = None
    free_route: bool = False
    execute: bool = False
    on_error: str = "rollback"
    target_duration_s: float | None = None


@router.post("/material-pack/graph")
async def material_pack_graph_endpoint(
    body: MaterialPackGraphRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    """Map a material pack (or stable-film manifest) to a canvas graph."""
    from hevi.canvas.material_pack import MaterialPackError, map_to_graph

    try:
        return map_to_graph(
            body.pack, body.existing_graph, pack_revision=body.pack_revision
        )
    except MaterialPackError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/material-pack/edit")
async def material_pack_edit_endpoint(
    body: MaterialPackEditRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    """Apply a human prompt edit to one segment node (dirty + downstream)."""
    from hevi.canvas.material_pack import MaterialPackError, apply_segment_edit

    try:
        return apply_segment_edit(
            body.graph, body.segment_id, body.patch, base_revision=body.base_revision
        )
    except MaterialPackError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/material-pack/regenerate")
async def material_pack_regenerate_endpoint(
    body: MaterialPackRegenerateRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    svc: Annotated[GraphService, Depends(get_graph_service)],
    exe: Annotated[ExecutorService, Depends(get_executor_service)],
) -> dict[str, Any]:
    """Gate one segment for regeneration; execute only if asked.

    Without ``execute`` this returns the ready/refused plan and runs
    nothing. With ``execute`` the single segment node (plan-only
    segment executor) is run through ExecutorService like any other
    graph -- the whole film is never re-run from here.
    """
    from hevi.canvas.material_pack import MaterialPackError, request_regeneration

    try:
        plan = await request_regeneration(
            body.graph,
            body.segment_id,
            confirmed=body.confirmed,
            smoke_passed=body.smoke_passed,
            budget_usd=body.budget_usd,
            estimated_unit_cost=body.estimated_unit_cost,
            free_route=body.free_route,
        )
    except MaterialPackError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if plan.get("status") == "refused":
        raise HTTPException(status_code=422, detail="; ".join(plan["blockers"]))
    if not body.execute:
        return plan
    segment_nodes = [
        n
        for n in (body.graph.get("nodes") or [])
        if isinstance(n, dict)
        and n.get("node_id") == body.segment_id
        and n.get("node_type") == "segment"
    ]
    if not segment_nodes:
        raise HTTPException(status_code=422, detail="segment node not found in graph")
    saved = await svc.save_graph(
        name=f"material-pack segment {body.segment_id}",
        description="single-segment regeneration (material pack)",
        nodes=segment_nodes,
        edges=[],
        user_id=str(user["id"]),
    )
    graph_id = saved.get("graph_id") or saved.get("id")
    if not graph_id:
        raise HTTPException(status_code=500, detail="graph save returned no id")
    execution = await _do_execute_graph(
        str(graph_id),
        ExecuteGraphRequest(
            on_error=body.on_error,
            budget_usd=body.budget_usd,
            target_duration_s=body.target_duration_s,
        ),
        exe,
        svc,
        user,
    )
    return {**plan, "status": "executed", "graph_id": str(graph_id), "execution": execution}


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
