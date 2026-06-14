from typing import Annotated, Any

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from obase.persistence import PgPool

from hevi.auth.jwt_handler import decode_access_token
from hevi.auth.repository import UserRepository
from hevi.db.pg_pool import get_hevi_pg_pool

security = HTTPBearer()


async def get_user_repository(
    pool: Annotated[PgPool, Depends(get_hevi_pg_pool)],
) -> UserRepository:
    return UserRepository(pool)


async def get_current_user(
    repo: Annotated[UserRepository, Depends(get_user_repository)],
    auth: Annotated[HTTPAuthorizationCredentials, Depends(security)],
) -> dict[str, Any]:
    try:
        payload = decode_access_token(auth.credentials)
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token: missing sub",
            )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired token: {exc}",
        ) from exc

    user = await repo.get(user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )
    return user
