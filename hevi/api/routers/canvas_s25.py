"""S25：画布增强 API（对话建画布 / 模板版本 / 费用预估 / 备份 / 报错 / 素材 / 技能 / 资产库）。

前缀 ``/canvas/s25``，与既有 ``/canvas`` 不冲突；所有写操作要求登录，读模板与技能
也要求登录（避免匿名枚举工作区结构）。实现全部在 ``hevi.canvas.*_s25`` 与
``agent_build`` 里，本文件只做 HTTP 适配。
"""

from __future__ import annotations

import asyncio
import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from hevi.api.rate_limit import rate_limit
from hevi.api.routers.canvas import _do_get_graph, _load_owned_graph
from hevi.auth.dependencies import get_current_user
from hevi.canvas import (
    agent_build,
    backup_s25,
    diagnostics_s25,
    library_s25,
    material_ops_s25,
    plugin_contract_s25,
    pricing_s25,
    skills_s25,
    templates_s25,
)

router = APIRouter(prefix="/canvas/s25", tags=["canvas-s25"])


async def _graph_service():
    """按需创建 GraphService：save=False / 纯计算接口不碰数据库。"""
    from hevi.canvas.graph_repository import GraphRepository
    from hevi.canvas.graph_service import GraphService
    from hevi.canvas.node_store import PgNodeStore
    from hevi.db.pg_pool import get_hevi_pg_pool

    pool = await get_hevi_pg_pool()
    return GraphService(GraphRepository(pool), node_store=PgNodeStore(pool))

_MAX_UPLOAD = 24 * 1024 * 1024
_ALLOWED_UPLOAD_SUFFIX = {".png", ".jpg", ".jpeg", ".webp", ".mp4", ".mov", ".mp3", ".wav"}


# ── 对话建画布 ───────────────────────────────────────────────────────────────


class PlanRequest(BaseModel):
    prompt: str
    format: str | None = None
    style: str | None = None
    line_id: str | None = None
    slots: dict[str, Any] = Field(default_factory=dict)
    lines: list[str] | None = None
    seconds: float = 5.0
    provider: str | None = None
    narration: str | None = None
    aspect: str | None = None
    structural_only: bool = False
    # 只在显式要求时调用文本模型；默认离线、确定性、快。
    use_llm: bool = False


class PlanPatchRequest(BaseModel):
    plan: dict[str, Any]
    node_key: str
    patch: dict[str, Any] = Field(default_factory=dict)


class PlanApplyRequest(BaseModel):
    plan: dict[str, Any]
    confirm_token: str
    name: str | None = None
    selected_nodes: list[str] | None = None
    save: bool = True


async def _llm_lines(prompt: str, timeout: float = 20.0) -> list[str]:
    """调用现有 ``script.quick``；失败/超时返回空，让方案退回确定性脚本。"""
    try:
        from hevi.studio.tools import invoke_tool

        result = await asyncio.wait_for(
            invoke_tool("script.quick", {"topic": prompt, "max_lines": 6}), timeout=timeout
        )
        payload = getattr(result, "payload", None) or {}
        raw = payload.get("script_lines") or []
        lines: list[str] = []
        for item in raw:
            text = item.get("text") if isinstance(item, dict) else item
            if text and str(text).strip():
                lines.append(str(text).strip())
        return lines
    except Exception:
        return []


@router.post("/plan", dependencies=[Depends(rate_limit("canvas-s25-plan", 30, 60, per_user=True))])
async def plan(
    body: PlanRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    lines = body.lines
    plan_source = "given"
    if not lines and body.use_llm:
        lines = await _llm_lines(body.prompt)
        plan_source = "llm" if lines else "offline"
    elif not lines:
        plan_source = "offline"
    try:
        built = await asyncio.to_thread(
            agent_build.build_plan,
            body.prompt,
            format_id=body.format,
            style_id=body.style,
            line_id=body.line_id,
            slots=body.slots,
            lines=lines,
            seconds=body.seconds,
            provider=body.provider,
            narration=body.narration,
            aspect=body.aspect,
            structural_only=body.structural_only,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "plan": built,
        "summary": agent_build.plan_summary(built),
        "script_source": plan_source,
        "requires_confirm": True,
    }


@router.post("/plan/patch", dependencies=[Depends(rate_limit("canvas-s25-patch", 60, 60, per_user=True))])
async def patch_plan(
    body: PlanPatchRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    try:
        patched = await asyncio.to_thread(
            agent_build.patch_plan_node, body.plan, body.node_key, body.patch
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"plan": patched, "summary": agent_build.plan_summary(patched)}


@router.post("/plan/apply", status_code=201)
async def apply_plan(
    body: PlanApplyRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    try:
        payload = agent_build.apply_plan(
            body.plan,
            confirm_token=body.confirm_token,
            name=body.name,
            selected_nodes=body.selected_nodes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not body.save:
        return {"saved": False, **payload}
    svc = await _graph_service()
    saved = await svc.save_graph(
        name=payload["name"],
        description=payload["description"],
        nodes=payload["nodes"],
        edges=payload["edges"],
        user_id=str(user["id"]),
    )
    return {
        "saved": True,
        "graph_id": str(saved.get("id")),
        "name": saved.get("name"),
        "numbers": payload["numbers"],
        "estimate": payload["estimate"],
        "plan_token": payload["plan_token"],
    }


# ── 费用预估（与 S22 账本同源） ──────────────────────────────────────────────


class EstimateRequest(BaseModel):
    graph: dict[str, Any] | None = None
    graph_id: str | None = None
    plan_id: str | None = None
    format: str = ""
    style: str = ""


@router.post("/estimate")
async def estimate(
    body: EstimateRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    graph = body.graph
    if graph is None and body.graph_id:
        svc = await _graph_service()
        graph = await _load_owned_graph(body.graph_id, svc, user)
    if graph is None:
        raise HTTPException(status_code=422, detail="需要 graph 或 graph_id")
    est = pricing_s25.estimate_graph(graph)
    seconds = sum(
        float(n.get("seconds") or 0) for n in est["per_node"] if n.get("kind") == "video"
    )
    shots = sum(1 for n in est["per_node"] if n.get("kind") == "video")
    out: dict[str, Any] = {
        **est,
        "quote": pricing_s25.quote_text(est, seconds=seconds, shots=shots),
        "format": body.format,
        "style": body.style,
    }
    if body.plan_id:
        cmp = pricing_s25.compare_with_ledger(body.plan_id, est)
        out["ledger"] = cmp
    return out


# ── 工作流模板（带版本） ────────────────────────────────────────────────────


class TemplateFlagRequest(BaseModel):
    builtin: bool = False


class TemplateCreateRequest(BaseModel):
    id: str
    name: str
    graph: dict[str, Any]
    format: str = ""
    style: str = ""
    note: str = ""


class TemplatePublishRequest(BaseModel):
    graph: dict[str, Any]
    note: str = ""
    name: str | None = None


class TemplateApplyRequest(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict)
    version: int | None = None
    save: bool = False
    name: str | None = None


@router.get("/templates")
async def list_templates(
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    format: str | None = None,
) -> dict[str, Any]:
    items = await asyncio.to_thread(templates_s25.ensure_builtin_templates)
    if format:
        items = [it for it in items if it.get("format") == format]
    return {"templates": items, "total": len(items)}


@router.get("/templates/{template_id}")
async def get_template(
    template_id: str,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    version: int | None = None,
) -> dict[str, Any]:
    try:
        body = await asyncio.to_thread(templates_s25.get_template, template_id, version)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"template": templates_s25.template_payload_meta(body), "graph": body["graph"]}


@router.post("/templates", status_code=201)
async def create_template(
    body: TemplateCreateRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    try:
        made = await asyncio.to_thread(
            templates_s25.create_template,
            template_id=body.id,
            name=body.name,
            graph=body.graph,
            format_id=body.format,
            style=body.style,
            note=body.note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"template": templates_s25.template_payload_meta(made)}


@router.post("/templates/{template_id}/versions", status_code=201)
async def publish_version(
    template_id: str,
    body: TemplatePublishRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    try:
        made = await asyncio.to_thread(
            templates_s25.publish_version,
            template_id,
            body.graph,
            note=body.note,
            name=body.name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"template": templates_s25.template_payload_meta(made)}


@router.get("/templates/{template_id}/diff")
async def diff_template_versions(
    template_id: str,
    from_version: int,
    to_version: int,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(
            templates_s25.diff_versions, template_id, from_version, to_version
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/templates/{template_id}/apply")
async def apply_template(
    template_id: str,
    body: TemplateApplyRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    try:
        applied = await asyncio.to_thread(
            templates_s25.apply_template, template_id, body.values, version=body.version
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not body.save:
        return {"saved": False, **applied}
    svc = await _graph_service()
    saved = await svc.save_graph(
        name=body.name or f"{applied['template_name']} v{applied['template_version']}",
        description=f"由模板 {template_id} v{applied['template_version']} 创建",
        nodes=applied["nodes"],
        edges=applied["edges"],
        user_id=str(user["id"]),
    )
    return {
        "saved": True,
        "graph_id": str(saved.get("id")),
        "template_id": template_id,
        "template_version": applied["template_version"],
        "numbers": applied["numbers"],
    }


# ── 备份导出 / 导入 ─────────────────────────────────────────────────────────


class BackupVerifyRequest(BaseModel):
    payload: dict[str, Any]
    strict_media: bool = False


class BackupImportRequest(BaseModel):
    payload: dict[str, Any]
    allow_checksum_mismatch: bool = False
    strict_media: bool = False
    save: bool = True


@router.get("/backup")
async def export_backup(
    graph_id: str,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    svc = await _graph_service()
    graph = await _do_get_graph(graph_id, svc, user)
    return await asyncio.to_thread(
        backup_s25.export_backup,
        graph,
        name=str(graph.get("name") or ""),
    )


@router.post("/backup/verify")
async def verify_backup(
    body: BackupVerifyRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    return await asyncio.to_thread(backup_s25.verify_backup, body.payload, strict_media=body.strict_media)


@router.post("/backup/import", status_code=201)
async def import_backup(
    body: BackupImportRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    try:
        payload = await asyncio.to_thread(
            backup_s25.import_backup,
            body.payload,
            allow_checksum_mismatch=body.allow_checksum_mismatch,
            strict_media=body.strict_media,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not body.save:
        return {"saved": False, **payload}
    svc = await _graph_service()
    saved = await svc.save_graph(
        name=payload["name"],
        description=payload["description"],
        nodes=payload["nodes"],
        edges=payload["edges"],
        user_id=str(user["id"]),
    )
    return {
        "saved": True,
        "graph_id": str(saved.get("id")),
        "verify": payload["verify"],
        "numbers": {"nodes": len(payload["nodes"]), "edges": len(payload["edges"])},
    }


# ── 报错可读化 ──────────────────────────────────────────────────────────────


class ExplainRequest(BaseModel):
    error: str | None = None
    node_type: str = ""
    config: dict[str, Any] = Field(default_factory=dict)
    review: dict[str, Any] | None = None


@router.post("/diagnostics/explain")
async def explain(
    body: ExplainRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    return diagnostics_s25.explain_failure(
        body.error, node_type=body.node_type, config=body.config, review=body.review
    )


@router.get("/diagnostics/{graph_id}")
async def diagnostics(
    graph_id: str,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    svc = await _graph_service()
    graph = await _do_get_graph(graph_id, svc, user)
    annotated = diagnostics_s25.annotate_graph(graph)
    problems = [n for n in annotated["nodes"] if n.get("diagnostic")]
    return {
        "graph_id": graph_id,
        "nodes": annotated["nodes"],
        "problems": len(problems),
        "diagnostics": {n["node_id"]: n["diagnostic"] for n in problems if n.get("node_id")},
    }


# ── 素材加工（离线三项 + 局部重绘边界） ──────────────────────────────────────


@router.get("/material/capabilities")
async def material_capabilities(
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    return material_ops_s25.capabilities()


@router.post("/material/op")
async def material_op(
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    file: Annotated[UploadFile, File()],
    op: Annotated[str, Form()] = "crop",
    params: Annotated[str, Form()] = "{}",
) -> dict[str, Any]:
    name = str(file.filename or "upload.png")
    suffix = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if suffix not in _ALLOWED_UPLOAD_SUFFIX:
        raise HTTPException(status_code=422, detail=f"不支持的素材格式：{suffix or '未知'}")
    data = await file.read()
    if not data or len(data) > _MAX_UPLOAD:
        raise HTTPException(status_code=413, detail="文件为空或超过 24MB")
    try:
        args = json.loads(params or "{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail="params 不是合法 JSON") from exc
    folder = material_ops_s25.OUT_ROOT / "inbox"
    folder.mkdir(parents=True, exist_ok=True)
    upload = folder / f"{material_ops_s25.new_batch()}{suffix}"
    upload.write_bytes(data)
    try:
        if op == "crop":
            result = await asyncio.to_thread(material_ops_s25.crop, upload, args)
        elif op == "split_grid":
            result = await asyncio.to_thread(
                material_ops_s25.split_grid,
                upload,
                cols=int(args.get("cols") or 3),
                rows=int(args.get("rows") or 3),
            )
        elif op == "annotate":
            marks = args.get("marks") if isinstance(args.get("marks"), list) else []
            result = await asyncio.to_thread(material_ops_s25.annotate, upload, marks)
        elif op == "inpaint":
            raise HTTPException(status_code=409, detail=material_ops_s25.inpaint_availability())
        else:
            raise HTTPException(status_code=422, detail=f"未知素材操作：{op}")
    except material_ops_s25.MaterialOpError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"参数不合法：{exc}") from exc
    return {"status": "ok", "source": str(upload), **result}


# ── 文字技能库（带版本） ────────────────────────────────────────────────────


@router.get("/skills")
async def list_skills(
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    include_disabled: bool = True,
) -> dict[str, Any]:
    return {"skills": skills_s25.list_skills(include_disabled=include_disabled)}


@router.get("/skills/{skill_id}")
async def get_skill(
    skill_id: str,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    version: int | None = None,
) -> dict[str, Any]:
    try:
        return skills_s25.get_skill(skill_id, version=version)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


class SkillToggleRequest(BaseModel):
    enabled: bool


@router.post("/skills/{skill_id}/toggle")
async def toggle_skill(
    skill_id: str,
    body: SkillToggleRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    try:
        return skills_s25.set_enabled(skill_id, body.enabled)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# ── 个人资产库 ──────────────────────────────────────────────────────────────


class LibraryAddRequest(BaseModel):
    title: str
    path: str = ""
    url: str = ""
    kind: str = ""
    source_graph: str = ""
    source_node: str = ""
    prompt: str = ""
    tags: list[str] = Field(default_factory=list)


@router.get("/library")
async def list_library(
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    kind: str | None = None,
    q: str = "",
) -> dict[str, Any]:
    items = library_s25.list_items(str(user["id"]), kind=kind, q=q)
    return {"items": items, "total": len(items)}


@router.post("/library", status_code=201)
async def add_library(
    body: LibraryAddRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    try:
        item = library_s25.add_item(
            str(user["id"]),
            title=body.title,
            path=body.path,
            url=body.url,
            kind=body.kind,
            source_graph=body.source_graph,
            source_node=body.source_node,
            prompt=body.prompt,
            tags=body.tags,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"item": item}


@router.delete("/library/{item_id}")
async def remove_library(
    item_id: str,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    removed = library_s25.remove_item(str(user["id"]), item_id)
    if not removed:
        raise HTTPException(status_code=404, detail="资产不存在")
    return {"removed": True, "item_id": item_id}


# ── 插件契约（内部，只读） ──────────────────────────────────────────────────


@router.get("/plugin-contract")
async def plugin_contract(
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    return plugin_contract_s25.contract_doc()
