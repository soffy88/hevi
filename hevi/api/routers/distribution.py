from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from hevi.auth.dependencies import get_current_user
from hevi.distribution.models import DistributionPlatform, DistributionTarget
from hevi.distribution.service import create_job, execute_job, matrixmedia_provider

router = APIRouter(prefix="/distribution", tags=["distribution"])


class DistributionRequest(BaseModel):
    source: str
    artifact_id: str
    platform: DistributionPlatform
    account_ref: str
    title: str = Field(min_length=1)
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    scheduled_at: str | None = None
    idempotency_key: str | None = None
    quality_passed: bool = False


async def _run(req: DistributionRequest, mode: str, _user: dict[str, Any] | None) -> dict[str, Any]:
    try:
        target = DistributionTarget.model_validate(req.model_dump(exclude={"source", "artifact_id", "idempotency_key", "quality_passed"}))
        job = create_job(req.source, target, artifact_id=req.artifact_id, quality_passed=req.quality_passed, idempotency_key=req.idempotency_key)
        result = await execute_job(job, req.source, mode=mode)
    except (OSError, ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return result.model_dump(mode="json")


@router.get("/probe")
async def probe(_user: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None) -> dict[str, Any]:
    return await matrixmedia_provider().probe()


@router.get("/accounts")
async def accounts(_user: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None) -> dict[str, Any]:
    items = await matrixmedia_provider().list_accounts()
    return {"accounts": [item.model_dump(mode="json") for item in items]}


@router.get("/history")
async def history(_user: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None) -> dict[str, Any]:
    items = await matrixmedia_provider().history()
    return {"history": list(items)}


@router.post("/publish")
async def publish(req: DistributionRequest, _user: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None) -> dict[str, Any]:
    return await _run(req, "publish", _user)


@router.post("/schedule")
async def schedule(req: DistributionRequest, _user: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None) -> dict[str, Any]:
    return await _run(req, "schedule", _user)


@router.post("/draft")
async def draft(req: DistributionRequest, _user: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None) -> dict[str, Any]:
    return await _run(req, "draft", _user)
