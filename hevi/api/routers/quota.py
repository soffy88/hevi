"""Public-beta quota status (S10).

The frontend shows ``remaining`` next to the generate button so a user never
has to guess how many films are left today.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from obase.persistence import PgPool

from hevi.auth.dependencies import get_current_user
from hevi.db.pg_pool import get_hevi_pg_pool
from hevi.quota import get_quota_service

router = APIRouter(prefix="/quota", tags=["quota"])


async def get_pg_pool() -> PgPool:
    return await get_hevi_pg_pool()


@router.get("/status")
async def quota_status(
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    pool: Annotated[PgPool, Depends(get_pg_pool)],
) -> dict[str, Any]:
    return await get_quota_service(pool).status(str(user["id"]))
