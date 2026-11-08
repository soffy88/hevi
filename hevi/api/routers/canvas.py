from __future__ import annotations

import hmac
import os
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse
from obase.persistence import PgPool
from pydantic import BaseModel

from hevi.api.rate_limit import rate_limit
from hevi.auth.dependencies import get_current_user
from hevi.canvas.executor_service import ExecutorService
from hevi.canvas.graph_repository import GraphRepository
from hevi.canvas.graph_service import GraphService
from hevi.canvas.node_store import PgNodeStore
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


def _merge_node_state(graph: dict[str, Any], states: dict[str, Any]) -> dict[str, Any]:
    """JSON mirror + execution state (status/review/revision/artifacts)."""
    nodes: list[dict[str, Any]] = []
    for node in graph.get("nodes_json", []) or []:
        merged = dict(node)
        state = states.get(str(node.get("node_id")))
        if state is not None:
            data = state.as_dict() if hasattr(state, "as_dict") else dict(state)
            merged.update(
                {
                    "status": data.get("status"),
                    "revision": data.get("revision"),
                    "locked": data.get("locked"),
                    "review": data.get("review"),
                    "artifacts": data.get("artifacts") or [],
                    "output": data.get("output"),
                    "estimated_cost": data.get("estimated_cost"),
                    "actual_cost": data.get("actual_cost"),
                }
            )
        nodes.append(merged)
    return {**graph, "nodes": nodes, "edges": graph.get("edges_json", [])}


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
    # Canvas MVP: dirty (default) 只跑 stale/pending/fail；selected 只跑选中节点
    # 及其下游；all 全跑。locked 节点永远跳过并在结果里报 locked_skipped。
    scope: str = "dirty"
    selected_ids: list[str] = []
    max_retries: int = 1


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
    return GraphService(GraphRepository(pool), node_store=PgNodeStore(pool))


async def get_executor_service(
    graph_svc: Annotated[GraphService, Depends(get_graph_service)],
) -> ExecutorService:
    return ExecutorService(graph_svc)


# ── ChatGPT review queue (internal, token-authenticated) ─────────────────────
# local2's MCP tools call these three routes from 127.0.0.1 / the docker
# network.  The public thumbnail route is read-only and carries a 15-minute
# HMAC token; it can only serve a path already recorded in a review row.


class ReviewClaimRequest(BaseModel):
    limit: int = 3


class ReviewSubmitRequest(BaseModel):
    item_id: str
    verdict: str
    issues: list[str] = []
    redo_nodes: list[str] = []
    reason: str = ""


def _review_internal_token() -> str:
    return os.getenv("HEVI_REVIEW_INTERNAL_TOKEN", "").strip()


async def require_review_internal_token(
    x_hevi_review_token: str | None = Header(default=None),
) -> None:
    expected = _review_internal_token()
    if not expected:
        raise HTTPException(status_code=503, detail="review internal token is not configured")
    if not x_hevi_review_token or not hmac.compare_digest(x_hevi_review_token, expected):
        raise HTTPException(status_code=401, detail="invalid review token")


@router.post("/review/claim", dependencies=[Depends(require_review_internal_token)])
async def review_claim(body: ReviewClaimRequest, pool: Annotated[PgPool, Depends(get_pg_pool)]) -> dict[str, Any]:
    from hevi.canvas.review_queue import claim

    items = await claim(pool, limit=body.limit)
    return {"items": items, "count": len(items)}


@router.post("/review/submit", dependencies=[Depends(require_review_internal_token)])
async def review_submit(body: ReviewSubmitRequest, pool: Annotated[PgPool, Depends(get_pg_pool)]) -> dict[str, Any]:
    from hevi.canvas.review_queue import submit

    try:
        return await submit(
            pool,
            item_id=body.item_id,
            verdict=body.verdict,
            issues=body.issues,
            redo_nodes=body.redo_nodes,
            reason=body.reason,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/review/status", dependencies=[Depends(require_review_internal_token)])
async def review_status(pool: Annotated[PgPool, Depends(get_pg_pool)]) -> dict[str, Any]:
    from hevi.canvas.review_queue import queue_status

    return await queue_status(pool)


@router.get("/review/thumb/{token}")
async def review_thumbnail(token: str, pool: Annotated[PgPool, Depends(get_pg_pool)]) -> FileResponse:
    """Read-only 15-minute signed link to one recorded review thumbnail."""
    from hevi.canvas.review_queue import verify_thumb_token

    parsed = verify_thumb_token(token)
    if parsed is None:
        raise HTTPException(status_code=404, detail="link expired or invalid")
    item_id, index = parsed
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT thumbnails FROM canvas_review_queue WHERE id=$1", uuid.UUID(item_id)
        )
    if row is None:
        raise HTTPException(status_code=404, detail="review item not found")
    thumbs = list(row["thumbnails"] or [])
    if index < 0 or index >= len(thumbs):
        raise HTTPException(status_code=404, detail="thumbnail not found")
    path = str(thumbs[index])
    if not path.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
        raise HTTPException(status_code=404, detail="thumbnail not found")
    from pathlib import Path

    if not Path(path).is_file():
        raise HTTPException(status_code=404, detail="thumbnail file missing")
    return FileResponse(path)


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
    graph = await _load_owned_graph(graph_id, svc, user)
    store = svc.node_store
    if store is not None:
        try:
            states = await store.load_nodes(graph_id)
        except Exception:
            states = {}
        if states:
            return _merge_node_state(graph, states)
    return _serialize_graph(graph)


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
            scope=body.scope,
            selected_ids=list(body.selected_ids or []),
            max_retries=max(0, int(body.max_retries)),
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


# ── Canvas MVP: koubo default graph + node-level operations ──────────────
# Fixed paths come before /{graph_id}; node subroutes hang off the
# parameterised graph path. Every node op reuses the same ExecutorService and
# node store as the graph-level execute, so there is no second executor.


class KouboTemplateRequest(BaseModel):
    script_text: str = ""
    topic: str = ""
    duration_s: float = 10.0
    engine: str = "livliv"
    character_id: str = "d03ft"
    out_dir: str = ""
    plan: dict[str, Any] | None = None
    positions: dict[str, Any] | None = None


class NodePatchRequest(BaseModel):
    config: dict[str, Any] | None = None
    label: str | None = None
    position: dict[str, Any] | None = None
    locked: bool | None = None


@router.post("/templates/koubo", status_code=201)
async def create_koubo_template(
    body: KouboTemplateRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    svc: Annotated[GraphService, Depends(get_graph_service)],
) -> dict[str, Any]:
    """Create (and save) the default koubo_cut graph, one node per step."""
    from hevi.canvas.koubo_template import build_koubo_graph, project_execution_plan

    graph = build_koubo_graph(
        script_text=body.script_text,
        topic=body.topic,
        duration_s=body.duration_s,
        engine=body.engine,
        character_id=body.character_id,
        out_dir=body.out_dir,
        plan=body.plan,
        positions=body.positions,
    )
    saved = await svc.save_graph(
        name=str(graph.get("name") or "koubo_cut 口播默认图"),
        description=str(graph.get("description") or ""),
        nodes=graph["nodes"],
        edges=graph["edges"],
        user_id=str(user["id"]),
    )
    graph_id = str(saved.get("id") or saved.get("graph_id"))
    states = {}
    if svc.node_store is not None:
        states = await svc.node_store.load_nodes(graph_id)
    payload = _merge_node_state(saved, states) if states else _serialize_graph(saved)
    return {
        **payload,
        "graph_id": graph_id,
        "template_id": "koubo_cut",
        "projection": project_execution_plan(body.plan),
    }


async def _node_state_or_404(svc: GraphService, graph_id: str, node_key: str):
    if svc.node_store is None:
        raise HTTPException(status_code=503, detail="node store unavailable")
    state = await svc.node_store.get_node(graph_id, node_key)
    if state is None:
        raise HTTPException(status_code=404, detail="Node not found")
    return state


@router.get("/{graph_id}/nodes/{node_key}/revisions")
async def list_node_revisions(
    graph_id: str,
    node_key: str,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    svc: Annotated[GraphService, Depends(get_graph_service)],
) -> dict[str, Any]:
    await _load_owned_graph(graph_id, svc, user)
    await _node_state_or_404(svc, graph_id, node_key)
    rows = await svc.node_store.list_revisions(graph_id, node_key)  # type: ignore[union-attr]
    return {"graph_id": graph_id, "node_id": node_key, "revisions": rows}


@router.patch("/{graph_id}/nodes/{node_key}")
async def patch_node(
    graph_id: str,
    node_key: str,
    body: NodePatchRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    svc: Annotated[GraphService, Depends(get_graph_service)],
) -> dict[str, Any]:
    """Edit one node's config/label/position and/or lock it.

    A config change goes through the normal graph update, which marks the
    changed node and its downstream stale without rewriting them.
    """
    graph = await _load_owned_graph(graph_id, svc, user)
    nodes = []
    found = False
    for node in graph.get("nodes_json", []) or []:
        item = dict(node)
        if str(item.get("node_id")) == node_key:
            found = True
            if body.config is not None:
                item["config"] = {**(item.get("config") or {}), **body.config}
            if body.label is not None:
                item["label"] = body.label
            if body.position is not None:
                item["position"] = body.position
        nodes.append(item)
    if not found:
        raise HTTPException(status_code=404, detail="Node not found")
    updated = await svc.update_graph(graph_id, nodes=nodes)
    if updated is None:
        raise HTTPException(status_code=404, detail="Graph not found")
    if body.locked is not None and svc.node_store is not None:
        await svc.node_store.set_locked(graph_id, node_key, body.locked)
    state = await svc.node_store.get_node(graph_id, node_key) if svc.node_store else None
    return {
        "graph_id": graph_id,
        "node": {
            **(next((n for n in nodes if str(n.get("node_id")) == node_key), {})),
            **({"status": state.status, "revision": state.revision, "locked": state.locked}
               if state else {}),
        },
    }


@router.post(
    "/{graph_id}/nodes/{node_key}/execute",
    dependencies=[Depends(rate_limit("canvas_execute", max_requests=20, window_s=60, per_user=True))],
)
async def execute_node(
    graph_id: str,
    node_key: str,
    body: ExecuteGraphRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    exe: Annotated[ExecutorService, Depends(get_executor_service)],
    svc: Annotated[GraphService, Depends(get_graph_service)],
) -> dict[str, Any]:
    """Rerun exactly this node plus its downstream (scope=selected)."""
    await _load_owned_graph(graph_id, svc, user)
    await _node_state_or_404(svc, graph_id, node_key)
    return await _do_execute_graph(
        graph_id,
        ExecuteGraphRequest(
            on_error=body.on_error,
            budget_usd=body.budget_usd,
            target_duration_s=body.target_duration_s,
            scope="selected",
            selected_ids=[node_key],
            max_retries=body.max_retries,
        ),
        exe,
        svc,
        user,
    )


@router.post("/{graph_id}/nodes/{node_key}/review")
async def review_node_endpoint(
    graph_id: str,
    node_key: str,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    svc: Annotated[GraphService, Depends(get_graph_service)],
) -> dict[str, Any]:
    """Re-run the node self-check on its latest output and write it back."""
    from hevi.canvas.self_check import review_node, status_for_review

    await _load_owned_graph(graph_id, svc, user)
    state = await _node_state_or_404(svc, graph_id, node_key)
    review = review_node(
        {"node_type": state.node_type, "config": state.config},
        state.output,
    )
    await svc.node_store.set_status(  # type: ignore[union-attr]
        graph_id, node_key, status_for_review(review), review=review
    )
    return {"graph_id": graph_id, "node_id": node_key, "status": status_for_review(review),
            "review": review}


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


@router.post(
    "/{graph_id}/execute",
    dependencies=[Depends(rate_limit("canvas_execute", max_requests=20, window_s=60, per_user=True))],
)
async def execute_graph(
    graph_id: str,
    body: ExecuteGraphRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    exe: Annotated[ExecutorService, Depends(get_executor_service)],
    svc: Annotated[GraphService, Depends(get_graph_service)],
) -> dict[str, Any]:
    return await _do_execute_graph(graph_id, body, exe, svc, user)
