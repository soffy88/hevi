from typing import Any

from obase.auth import jwt_create, jwt_verify

from hevi.core.config import settings


def sign_access_token(user_id: str) -> str:
    """Create a JWT access token for a user."""
    return jwt_create(
        payload={"sub": user_id},
        secret=settings.jwt_secret,
        expires_in_minutes=60, # 1 hour
    )


def decode_access_token(token: str) -> dict[str, Any]:
    """Verify and decode a JWT access token."""
    return jwt_verify(
        token=token,
        secret=settings.jwt_secret,
    )
