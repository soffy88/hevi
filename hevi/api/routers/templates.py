from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from obase.persistence import PgPool
from pydantic import BaseModel

from hevi.db.pg_pool import get_hevi_pg_pool
from hevi.templates.template_repository import TemplateRepository
from hevi.templates.template_service import TemplateService

router = APIRouter(prefix="/templates", tags=["templates"])


class TemplateCreateRequest(BaseModel):
    name: str
    category: str
    canvas_json: dict[str, Any]
    thumbnail: str | None = None
    is_official: bool = False
    user_id: str | None = None
    metadata: dict[str, Any] = {}


async def get_pg_pool() -> PgPool:
    return await get_hevi_pg_pool()


async def get_template_service(
    pool: Annotated[PgPool, Depends(get_pg_pool)],
) -> TemplateService:
    return TemplateService(TemplateRepository(pool))


@router.post("/", status_code=201)
async def create_template(
    body: TemplateCreateRequest,
    svc: Annotated[TemplateService, Depends(get_template_service)],
) -> dict[str, Any]:
    return await svc.create_template(
        name=body.name,
        category=body.category,
        canvas_json=body.canvas_json,
        thumbnail=body.thumbnail,
        is_official=body.is_official,
        user_id=body.user_id,
        metadata=body.metadata,
    )


@router.get("/")
async def list_templates(
    svc: Annotated[TemplateService, Depends(get_template_service)],
    category: str | None = None,
    official_only: bool = False,
    user_id: str | None = None,
) -> list[dict[str, Any]]:
    return await svc.list_templates(
        category=category, official_only=official_only, user_id=user_id
    )


@router.get("/{template_id}")
async def get_template(
    template_id: str,
    svc: Annotated[TemplateService, Depends(get_template_service)],
) -> dict[str, Any]:
    template = await svc.get_template(template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="Template not found")
    return template


@router.post("/{template_id}/apply")
async def apply_template(
    template_id: str,
    svc: Annotated[TemplateService, Depends(get_template_service)],
) -> dict[str, Any]:
    try:
        return await svc.apply_template(template_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/{template_id}")
async def delete_template(
    template_id: str,
    svc: Annotated[TemplateService, Depends(get_template_service)],
) -> dict[str, str]:
    success = await svc.delete_template(template_id)
    if not success:
        raise HTTPException(status_code=404, detail="Template not found")
    return {"status": "deleted", "template_id": template_id}
