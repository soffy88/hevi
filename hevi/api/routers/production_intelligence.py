"""P2 Production Intelligence API.

The API is intentionally thin: it validates typed control-plane records and
persists them in the existing ProductionGraphRepository.  It does not expose
provider calls or create a second scheduler/task system.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from hevi.api.routers.studio_v2 import get_graph_repository
from hevi.auth.dependencies import get_current_user
from hevi.production_graph.ids import new_id
from hevi.production_graph.intelligence import (
    RECORD_TYPES,
    DispatchLease,
    ProductionIntelligenceService,
    ProductionOutcome,
)
from hevi.production_graph.repository import ProductionGraphRepository

router = APIRouter(prefix="/studio", tags=["production-intelligence"])
UserDep = Annotated[dict[str, Any], Depends(get_current_user)]
RepoDep = Annotated[ProductionGraphRepository, Depends(get_graph_repository)]


class IntelligenceRecordRequest(BaseModel):
    kind: str
    record: dict[str, Any]


class LearnRequest(BaseModel):
    outcome: dict[str, Any]
    preference_key: str
    preference_value: Any


async def _owned(repo: ProductionGraphRepository, project_id: str, user: dict[str, Any]):
    snapshot = await repo.get_snapshot(project_id)
    if snapshot is None or snapshot.project.user_id != str(user["id"]):
        raise HTTPException(status_code=404, detail="project not found")
    return snapshot


@router.get("/projects/{project_id}/intelligence/{kind}")
async def list_intelligence(project_id: str, kind: str, user: UserDep, repo: RepoDep):
    await _owned(repo, project_id, user)
    try:
        items = await ProductionIntelligenceService(repo).list(project_id, kind)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"kind": kind, "records": items}


@router.post("/projects/{project_id}/intelligence", status_code=status.HTTP_201_CREATED)
async def create_intelligence(
    project_id: str,
    body: IntelligenceRecordRequest,
    user: UserDep,
    repo: RepoDep,
):
    snapshot = await _owned(repo, project_id, user)
    model_type = RECORD_TYPES.get(body.kind)
    if model_type is None:
        raise HTTPException(status_code=400, detail=f"unknown P2 record type: {body.kind}")
    payload = {"project_id": project_id, "revision_id": snapshot.revision.id, **body.record}
    payload.setdefault("id", new_id())
    try:
        record = model_type.model_validate(payload)
        saved = await ProductionIntelligenceService(repo).save(record)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"record": saved}


@router.post("/projects/{project_id}/intelligence/learn", status_code=status.HTTP_201_CREATED)
async def learn_outcome(project_id: str, body: LearnRequest, user: UserDep, repo: RepoDep):
    snapshot = await _owned(repo, project_id, user)
    outcome = ProductionOutcome(
        project_id=project_id,
        revision_id=snapshot.revision.id,
        **body.outcome,
    )
    try:
        result, preference = await ProductionIntelligenceService(repo).learn_from_outcome(
            outcome,
            preference_key=body.preference_key,
            preference_value=body.preference_value,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"outcome": result, "preference": preference}


@router.post("/projects/{project_id}/intelligence/recover")
async def recover_dispatch(project_id: str, body: dict[str, Any], user: UserDep, repo: RepoDep):
    snapshot = await _owned(repo, project_id, user)
    lease = DispatchLease(
        project_id=project_id,
        revision_id=snapshot.revision.id,
        **body,
    )
    recovered = ProductionIntelligenceService.recover_lease(lease, worker_id=str(body["worker_id"]))
    return {"lease": await ProductionIntelligenceService(repo).save(recovered)}


__all__ = ["router"]
