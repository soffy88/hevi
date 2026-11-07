"""stickman API router —— 火柴人流水线独立 HTTP 路由。"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Annotated, Any
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from hevi.auth.dependencies import get_current_user
from hevi.stickman.topic_scout import scout_topics
from hevi.stickman.structure_clone import clone_structure, CopyViolationError
from hevi.stickman.proposal import (
    create_proposal_from_script,
    DirectorProposal,
    StoryboardScene,
    ProposalError,
    ProposalNotApprovedError,
    ProposalModificationError,
)
from hevi.stickman.render_local import render_local_video
from hevi.stickman.flow_pack import export_flow_pack
from hevi.stickman.flow_import import import_and_stitch_flow_clips, FlowImportValidationError
from hevi.stickman.credits_ledger import CreditsLedger


router = APIRouter(prefix="/stickman", tags=["stickman"])


def _stickman_data_dir() -> Path:
    """Persistent dir for the ledger + proposal store (G11).

    ``$STICKMAN_DATA_DIR`` wins; otherwise ``<repo-root>/data/stickman``.
    In the production container that resolves to ``/app/data/stickman``,
    bind-mounted to a host directory, so both files survive container
    recreate. JSON (not PG) by design: single uvicorn worker, the
    CreditsLedger class already implements JSON save/load, and no
    migration is needed. Multi-instance deployments would need a shared
    store + file locking; production runs ``--workers 1`` (see G11 note
    in the launch report), so this is deliberately not built here.
    """
    env = os.environ.get("STICKMAN_DATA_DIR", "").strip()
    if env:
        return Path(env).expanduser()
    return Path(__file__).resolve().parents[2] / "data" / "stickman"


def _proposal_store_path() -> Path:
    return _stickman_data_dir() / "proposals.json"


def _save_proposal(prop: dict[str, Any]) -> None:
    """Upsert one proposal dict into proposals.json (atomic replace)."""
    store = _proposal_store_path()
    store.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = json.loads(store.read_text(encoding="utf-8")) if store.exists() else {}
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}
    data[str(prop.get("proposal_id", "prop_api"))] = prop
    tmp = store.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(store)


def _load_proposals() -> dict[str, Any]:
    store = _proposal_store_path()
    try:
        data = json.loads(store.read_text(encoding="utf-8")) if store.exists() else {}
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


_STICKMAN_DATA_DIR = _stickman_data_dir()
_GLOBAL_LEDGER = CreditsLedger(ledger_file=_STICKMAN_DATA_DIR / "credits_ledger.json")


class TopicScoutRequest(BaseModel):
    source: Any = Field(..., description="CSV 文本、文件路径或记录列表")
    min_views: int = 0
    top_n: int | None = None


class StructureCloneRequest(BaseModel):
    new_topic: str
    reference_script: Any = None
    target_duration: float = 60.0
    enforce_anti_copy: bool = True


class ProposalCreateRequest(BaseModel):
    script_data: dict[str, Any]
    aspect_ratio: str = "16:9"
    art_style: str = "classic_minimalist"
    bgm_style: str = "Kinetic Piano & Upbeat Lo-Fi Synth"
    auto_approve: bool = False


class ProposalUpdateRequest(BaseModel):
    proposal: dict[str, Any]
    aspect_ratio: str | None = None
    art_style: str | None = None
    hook: str | None = None


class RenderLocalRequest(BaseModel):
    proposal: dict[str, Any]
    out_path: str


class FlowPackRequest(BaseModel):
    proposal: dict[str, Any]
    out_dir: str


class FlowImportRequest(BaseModel):
    proposal: dict[str, Any]
    clip_paths: list[str]
    out_path: str


def _reconstruct_proposal(data: dict[str, Any]) -> DirectorProposal:
    scenes = [StoryboardScene(**s) for s in data.get("storyboard", [])]
    return DirectorProposal(
        proposal_id=data.get("proposal_id", "prop_api"),
        title=data.get("title", "未命名"),
        topic=data.get("topic", "未命名"),
        hook=data.get("hook", ""),
        color_palette=data.get("color_palette", {}),
        storyboard=scenes,
        voiceover=data.get("voiceover", {}),
        bgm_style=data.get("bgm_style", ""),
        aspect_ratio=data.get("aspect_ratio", "16:9"),
        art_style=data.get("art_style", "classic_minimalist"),
        status=data.get("status", "draft"),
    )


@router.post("/topic_scout")
def api_topic_scout(
    user: Annotated[dict[str, Any], Depends(get_current_user)],
req: TopicScoutRequest) -> dict[str, Any]:
    items = scout_topics(req.source, min_views=req.min_views, top_n=req.top_n)
    return {"status": "ok", "topics": items, "count": len(items)}


@router.post("/structure_clone")
def api_structure_clone(
    user: Annotated[dict[str, Any], Depends(get_current_user)],
req: StructureCloneRequest) -> dict[str, Any]:
    try:
        res = clone_structure(
            reference_script=req.reference_script or {},
            new_topic=req.new_topic,
            target_duration=req.target_duration,
            enforce_anti_copy=req.enforce_anti_copy,
        )
        return {"status": "ok", "script": res}
    except CopyViolationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/proposal/create")
def api_create_proposal(
    user: Annotated[dict[str, Any], Depends(get_current_user)],
req: ProposalCreateRequest) -> dict[str, Any]:
    prop = create_proposal_from_script(
        req.script_data,
        aspect_ratio=req.aspect_ratio,
        art_style=req.art_style,
        bgm_style=req.bgm_style,
    )
    if req.auto_approve:
        prop.approve()
    prop_d = prop.to_dict()
    _save_proposal(prop_d)
    return {"status": "ok", "proposal": prop_d}


@router.post("/proposal/approve")
def api_approve_proposal(
    user: Annotated[dict[str, Any], Depends(get_current_user)],
prop_data: dict[str, Any]) -> dict[str, Any]:
    prop = _reconstruct_proposal(prop_data)
    prop.approve()
    prop_d = prop.to_dict()
    _save_proposal(prop_d)
    return {"status": "ok", "proposal": prop_d}


@router.post("/render_local")
def api_render_local(
    user: Annotated[dict[str, Any], Depends(get_current_user)],
req: RenderLocalRequest) -> dict[str, Any]:
    prop = _reconstruct_proposal(req.proposal)
    try:
        res = render_local_video(prop, req.out_path)
        return {"status": "ok", "result": res}
    except ProposalNotApprovedError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"渲染失败: {exc}")


@router.post("/flow_pack")
def api_flow_pack(
    user: Annotated[dict[str, Any], Depends(get_current_user)],
req: FlowPackRequest) -> dict[str, Any]:
    prop = _reconstruct_proposal(req.proposal)
    try:
        res = export_flow_pack(prop, req.out_dir, ledger=_GLOBAL_LEDGER)
        return {"status": "ok", "result": res}
    except ProposalNotApprovedError as exc:
        raise HTTPException(status_code=403, detail=str(exc))


@router.post("/flow_import")
def api_flow_import(
    user: Annotated[dict[str, Any], Depends(get_current_user)],
req: FlowImportRequest) -> dict[str, Any]:
    prop = _reconstruct_proposal(req.proposal)
    try:
        res = import_and_stitch_flow_clips(req.clip_paths, prop, req.out_path)
        return {"status": "ok", "result": res}
    except FlowImportValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/credits")
def api_get_credits() -> dict[str, Any]:
    return {"status": "ok", "ledger": _GLOBAL_LEDGER.get_summary()}


@router.get("/proposals")
def api_list_proposals() -> dict[str, Any]:
    """List persisted proposals (G11: survives API restart)."""
    proposals = _load_proposals()
    return {"status": "ok", "proposals": list(proposals.values()), "count": len(proposals)}


@router.get("/proposals/{proposal_id}")
def api_get_proposal(proposal_id: str) -> dict[str, Any]:
    proposals = _load_proposals()
    if proposal_id not in proposals:
        raise HTTPException(status_code=404, detail=f"proposal not found: {proposal_id}")
    return {"status": "ok", "proposal": proposals[proposal_id]}
