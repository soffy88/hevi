from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from obase.persistence import PgPool
from pydantic import BaseModel

from hevi.auth.dependencies import get_current_user
from hevi.db.pg_pool import get_hevi_pg_pool
from hevi.subjects.repository import SubjectRepository
from hevi.subjects.subject_service import SubjectService

router = APIRouter(prefix="/subjects", tags=["subjects"])


def _check_owner(resource: dict[str, Any], user: dict[str, Any]) -> None:
    """404 (not 403, to avoid leaking existence) if the resource belongs to
    someone else. Legacy rows with no owner stay accessible."""
    if resource.get("user_id") and resource["user_id"] != str(user["id"]):
        raise HTTPException(status_code=404, detail="Subject not found")


def _serialize_subject(s: dict[str, Any]) -> dict[str, Any]:
    return {**s, "subject_id": s.get("id"), "kind": s.get("subject_type")}


class SubjectCreateRequest(BaseModel):
    kind: str
    name: str
    description: str = ""
    reference_images: list[str] = []
    metadata: dict[str, Any] = {}
    tags: list[str] = []
    user_id: str | None = None


class SubjectUpdateRequest(BaseModel):
    metadata: dict[str, Any]


async def get_pg_pool() -> PgPool:
    return await get_hevi_pg_pool()


async def get_subject_service(
    pool: Annotated[PgPool, Depends(get_pg_pool)],
) -> SubjectService:
    return SubjectService(SubjectRepository(pool))


@router.post("", status_code=201)
@router.post("/", status_code=201)
async def create_subject(
    body: SubjectCreateRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    svc: Annotated[SubjectService, Depends(get_subject_service)],
) -> dict[str, Any]:
    try:
        return _serialize_subject(await svc.create_subject(
            kind=body.kind,
            name=body.name,
            description=body.description,
            reference_images=body.reference_images if body.reference_images else None,
            metadata=body.metadata,
            tags=body.tags,
            user_id=str(user["id"]),  # owner is the authenticated user, not client-supplied
        ))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("")
@router.get("/")
async def list_subjects(
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    svc: Annotated[SubjectService, Depends(get_subject_service)],
    kind: str | None = None,
    query: str | None = None,
) -> list[dict[str, Any]]:
    # Scope to the caller — never honor a client-supplied user_id.
    results = await svc.search_subjects(kind=kind, query=query, user_id=str(user["id"]))
    return [_serialize_subject(s) for s in results]


@router.get("/{subject_id}")
async def get_subject(
    subject_id: str,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    svc: Annotated[SubjectService, Depends(get_subject_service)],
) -> dict[str, Any]:
    subject = await svc.get_subject(subject_id)
    if subject is None:
        raise HTTPException(status_code=404, detail="Subject not found")
    _check_owner(subject, user)
    return _serialize_subject(subject)


@router.patch("/{subject_id}")
async def update_subject(
    subject_id: str,
    body: SubjectUpdateRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    svc: Annotated[SubjectService, Depends(get_subject_service)],
) -> dict[str, Any]:
    existing = await svc.get_subject(subject_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Subject not found")
    _check_owner(existing, user)
    result = await svc.update_subject_metadata(subject_id, metadata=body.metadata)
    if result is None:
        raise HTTPException(status_code=404, detail="Subject not found")
    return _serialize_subject(result)


@router.delete("/{subject_id}", status_code=200)
async def delete_subject(
    subject_id: str,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    svc: Annotated[SubjectService, Depends(get_subject_service)],
) -> dict[str, str]:
    existing = await svc.get_subject(subject_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Subject not found")
    _check_owner(existing, user)
    deleted = await svc.delete_subject(subject_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Subject not found")
    return {"status": "deleted", "subject_id": subject_id}
