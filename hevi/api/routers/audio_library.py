from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from obase.persistence import PgPool
from pydantic import BaseModel

from hevi.audio_library.audio_lib_repository import AudioLibraryRepository
from hevi.audio_library.audio_lib_service import AudioLibraryService
from hevi.db.pg_pool import get_hevi_pg_pool

router = APIRouter(prefix="/audio", tags=["audio_library"])


class AudioAssetCreateRequest(BaseModel):
    name: str
    asset_type: Literal["bgm", "sfx"]
    file_path: str
    mood: str | None = None
    duration_s: float = 0.0
    tags: list[str] = []
    is_official: bool = False
    user_id: str | None = None


async def get_pg_pool() -> PgPool:
    return await get_hevi_pg_pool()


async def get_audio_service(
    pool: Annotated[PgPool, Depends(get_pg_pool)],
) -> AudioLibraryService:
    return AudioLibraryService(AudioLibraryRepository(pool))


@router.post("/", status_code=201)
async def create_audio_asset(
    body: AudioAssetCreateRequest,
    svc: Annotated[AudioLibraryService, Depends(get_audio_service)],
) -> dict[str, Any]:
    return await svc.create_audio_asset(
        name=body.name,
        asset_type=body.asset_type,
        file_path=body.file_path,
        mood=body.mood,
        duration_s=body.duration_s,
        tags=body.tags,
        is_official=body.is_official,
        user_id=body.user_id,
    )


@router.get("/")
async def search_audio(
    svc: Annotated[AudioLibraryService, Depends(get_audio_service)],
    asset_type: str | None = None,
    mood: str | None = None,
    tags: Annotated[list[str] | None, Query()] = None,
    query: str | None = None,
    user_id: str | None = None,
) -> list[dict[str, Any]]:
    return await svc.search_audio(
        asset_type=asset_type,
        mood=mood,
        tags=tags or [],
        query=query,
        user_id=user_id
    )


@router.get("/{asset_id}")
async def get_audio_asset(
    asset_id: str,
    svc: Annotated[AudioLibraryService, Depends(get_audio_service)],
) -> dict[str, Any]:
    asset = await svc.get_audio_asset(asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Audio asset not found")
    return asset


@router.delete("/{asset_id}")
async def delete_audio_asset(
    asset_id: str,
    svc: Annotated[AudioLibraryService, Depends(get_audio_service)],
) -> dict[str, str]:
    success = await svc.delete_audio_asset(asset_id)
    if not success:
        raise HTTPException(status_code=404, detail="Audio asset not found")
    return {"status": "deleted", "asset_id": asset_id}
