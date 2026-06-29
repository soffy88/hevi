from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from obase.persistence import PgPool
from pydantic import BaseModel

from hevi.auth.dependencies import get_current_user
from hevi.db.pg_pool import get_hevi_pg_pool
from hevi.templates.template_repository import TemplateRepository
from hevi.templates.template_service import TemplateService

router = APIRouter(prefix="/templates", tags=["templates"])


class TemplateCreateRequest(BaseModel):
    name: str
    category: str
    canvas_json: dict[str, Any]
    thumbnail: str | None = None
    metadata: dict[str, Any] = {}
    # NOTE: is_official / user_id are NOT accepted from the client — is_official is
    # forced False (no self-minted "official" templates) and user_id comes from the JWT.


async def get_pg_pool() -> PgPool:
    return await get_hevi_pg_pool()


async def get_template_service(
    pool: Annotated[PgPool, Depends(get_pg_pool)],
) -> TemplateService:
    return TemplateService(TemplateRepository(pool))


def _visible(template: dict[str, Any], user: dict[str, Any]) -> bool:
    """A template is visible if it's official or owned by the caller."""
    return bool(template.get("is_official")) or template.get("user_id") == str(user["id"])


@router.post("", status_code=201)
@router.post("/", status_code=201)
async def create_template(
    body: TemplateCreateRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    svc: Annotated[TemplateService, Depends(get_template_service)],
) -> dict[str, Any]:
    return await svc.create_template(
        name=body.name,
        category=body.category,
        canvas_json=body.canvas_json,
        thumbnail=body.thumbnail,
        is_official=False,  # server-controlled; clients cannot mint official templates
        user_id=str(user["id"]),
        metadata=body.metadata,
    )


@router.get("")
@router.get("/")
async def list_templates(
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    svc: Annotated[TemplateService, Depends(get_template_service)],
    category: str | None = None,
    official_only: bool = False,
) -> list[dict[str, Any]]:
    # Repo returns official OR caller-owned when user_id is set.
    return await svc.list_templates(
        category=category, official_only=official_only, user_id=str(user["id"])
    )


@router.get("/{template_id}")
async def get_template(
    template_id: str,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    svc: Annotated[TemplateService, Depends(get_template_service)],
) -> dict[str, Any]:
    template = await svc.get_template(template_id)
    if template is None or not _visible(template, user):
        raise HTTPException(status_code=404, detail="Template not found")
    return template


@router.post("/{template_id}/apply")
async def apply_template(
    template_id: str,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    svc: Annotated[TemplateService, Depends(get_template_service)],
) -> dict[str, Any]:
    template = await svc.get_template(template_id)
    if template is None or not _visible(template, user):
        raise HTTPException(status_code=404, detail="Template not found")
    try:
        return await svc.apply_template(template_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/{template_id}")
async def delete_template(
    template_id: str,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    svc: Annotated[TemplateService, Depends(get_template_service)],
) -> dict[str, str]:
    template = await svc.get_template(template_id)
    # Only the owner may delete; official templates aren't deletable here.
    if template is None or template.get("user_id") != str(user["id"]):
        raise HTTPException(status_code=404, detail="Template not found")
    success = await svc.delete_template(template_id)
    if not success:
        raise HTTPException(status_code=404, detail="Template not found")
    return {"status": "deleted", "template_id": template_id}
