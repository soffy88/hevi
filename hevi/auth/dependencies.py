from typing import Annotated, Any

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from obase.persistence import PgPool

from hevi.auth.auth_service import _safe_user
from hevi.auth.jwt_handler import decode_access_token
from hevi.auth.repository import UserRepository
from hevi.core.config import settings
from hevi.db.pg_pool import get_hevi_pg_pool

security = HTTPBearer()


def _admin_user_ids() -> set[str]:
    """Operator allowlist for global (non-tenant-scoped) administration routes.

    Global registries (usage ledger, declarative endpoints) have no owner
    dimension, so they are admin-only and fail closed when no allowlist is
    configured. Set ``HEVI_ADMIN_USER_IDS`` to a comma-separated list.
    """
    import os

    raw = os.getenv("HEVI_ADMIN_USER_IDS", str(getattr(settings, "admin_user_ids", "") or ""))
    return {part.strip() for part in raw.split(",") if part.strip()}


def internal_line_allowlist() -> set[str]:
    """Extra users allowed to see internal Studio lines (ids or emails)."""
    import os

    raw = os.getenv("HEVI_INTERNAL_LINE_ALLOWLIST", "")
    return {part.strip() for part in raw.split(",") if part.strip()}


def can_view_internal_lines(user: dict[str, Any] | None) -> bool:
    """Admins and the explicit allowlist may see/execute internal lines."""
    if not user:
        return False
    identity = {str(user.get("id") or ""), str(user.get("email") or "")}
    if identity & _admin_user_ids():
        return True
    return bool(identity & internal_line_allowlist())


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
    except HTTPException:
        raise
    except Exception as exc:
        # Don't leak exception internals (stack/impl detail) to the client.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        ) from exc

    user = await repo.get(user_id)
    if not user or not user.get("is_active", True):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )
    return _safe_user(user)


async def require_admin(
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    """Admin-only dependency for global (non-tenant-scoped) resources.

    Fails closed: an empty allowlist denies everyone. Global registries have
    no owner column, so tenant isolation cannot be expressed by scoping; the
    honest control is a server-side operator allowlist.
    """
    if str(user.get("id") or "") not in _admin_user_ids():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator access required",
        )
    return user
