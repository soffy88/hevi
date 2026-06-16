from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from obase.persistence import PgPool
from pydantic import BaseModel

from hevi.db.pg_pool import get_hevi_pg_pool
from hevi.subjects.repository import SubjectRepository
from hevi.subjects.subject_service import SubjectService

router = APIRouter(prefix="/subjects", tags=["subjects"])


def _serialize_subject(s: dict) -> dict:
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
            user_id=body.user_id,
        ))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("")
@router.get("/")
async def list_subjects(
    svc: Annotated[SubjectService, Depends(get_subject_service)],
    kind: str | None = None,
    query: str | None = None,
    user_id: str | None = None,
) -> list[dict[str, Any]]:
    return [_serialize_subject(s) for s in await svc.search_subjects(kind=kind, query=query, user_id=user_id)]


@router.get("/{subject_id}")
async def get_subject(
    subject_id: str,
    svc: Annotated[SubjectService, Depends(get_subject_service)],
) -> dict[str, Any]:
    subject = await svc.get_subject(subject_id)
    if subject is None:
        raise HTTPException(status_code=404, detail="Subject not found")
    return _serialize_subject(subject)


@router.patch("/{subject_id}")
async def update_subject(
    subject_id: str,
    body: SubjectUpdateRequest,
    svc: Annotated[SubjectService, Depends(get_subject_service)],
) -> dict[str, Any]:
    result = await svc.update_subject_metadata(subject_id, metadata=body.metadata)
    if result is None:
        raise HTTPException(status_code=404, detail="Subject not found")
    return _serialize_subject(result)


@router.delete("/{subject_id}", status_code=200)
async def delete_subject(
    subject_id: str,
    svc: Annotated[SubjectService, Depends(get_subject_service)],
) -> dict[str, str]:
    deleted = await svc.delete_subject(subject_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Subject not found")
    return {"status": "deleted", "subject_id": subject_id}
