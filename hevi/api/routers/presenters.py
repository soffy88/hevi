"""Presenter profiles: reusable digital-human appearance and delivery settings."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from hevi.auth.dependencies import get_current_user
from hevi.db.pg_pool import get_hevi_pg_pool
from hevi.presenters.repository import PresenterRepository

router = APIRouter(prefix="/presenters", tags=["presenters"])


class PresenterRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    subject_id: str | None = None
    voice_profile_id: str | None = None
    performance: str = "narrator"
    motion: str = "picture_in_picture"
    lipsync: str = "none"
    delivery: dict[str, Any] = Field(default_factory=dict)
    description: str = ""


async def get_repository() -> PresenterRepository:
    return PresenterRepository(await get_hevi_pg_pool())


def _serialize(row: dict[str, Any]) -> dict[str, Any]:
    return {**row, "id": str(row["id"]), "delivery": row.get("delivery_json") or {}}


@router.post("", status_code=201)
async def create_presenter(
    body: PresenterRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    repo: Annotated[PresenterRepository, Depends(get_repository)],
) -> dict[str, Any]:
    row = await repo.create(
        {
            "user_id": str(user["id"]),
            "name": body.name,
            "subject_id": body.subject_id,
            "voice_profile_id": body.voice_profile_id,
            "performance": body.performance,
            "motion": body.motion,
            "lipsync": body.lipsync,
            "delivery_json": body.delivery,
            "description": body.description,
        }
    )
    return _serialize(row)


@router.get("")
async def list_presenters(
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    repo: Annotated[PresenterRepository, Depends(get_repository)],
) -> list[dict[str, Any]]:
    return [_serialize(row) for row in await repo.list(str(user["id"]))]


@router.get("/{presenter_id}")
async def get_presenter(
    presenter_id: str,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    repo: Annotated[PresenterRepository, Depends(get_repository)],
) -> dict[str, Any]:
    row = await repo.get(presenter_id, str(user["id"]))
    if row is None:
        raise HTTPException(status_code=404, detail="presenter 不存在")
    return _serialize(row)


@router.post("/{presenter_id}/test")
async def test_presenter(
    presenter_id: str,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    repo: Annotated[PresenterRepository, Depends(get_repository)],
) -> dict[str, Any]:
    """Validate a Presenter before a production requests a provider run."""
    row = await repo.get(presenter_id, str(user["id"]))
    if row is None:
        raise HTTPException(status_code=404, detail="presenter 不存在")

    issues: list[str] = []
    motion = str(row.get("motion") or "picture_in_picture")
    lipsync = str(row.get("lipsync") or "none")
    if motion != "voice_over" and not row.get("subject_id"):
        issues.append("on-camera Presenter 需要 subject_id")
    if lipsync != "none" and not row.get("voice_profile_id"):
        issues.append("启用口型同步时需要 voice_profile_id")

    return {
        "presenter_id": presenter_id,
        "ready": not issues,
        "issues": issues,
        "strategy": {
            "performance": row.get("performance", "narrator"),
            "motion": motion,
            "lipsync": lipsync,
            "delivery": row.get("delivery_json") or {},
        },
    }


@router.patch("/{presenter_id}")
async def update_presenter(
    presenter_id: str,
    body: PresenterRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    repo: Annotated[PresenterRepository, Depends(get_repository)],
) -> dict[str, Any]:
    row = await repo.update(
        presenter_id,
        str(user["id"]),
        {
            "name": body.name,
            "subject_id": body.subject_id,
            "voice_profile_id": body.voice_profile_id,
            "performance": body.performance,
            "motion": body.motion,
            "lipsync": body.lipsync,
            "delivery_json": body.delivery,
            "description": body.description,
        },
    )
    if row is None:
        raise HTTPException(status_code=404, detail="presenter 不存在")
    return _serialize(row)
