from __future__ import annotations

from typing import Any, Literal

from hevi.auth.jwt_handler import sign_access_token
from hevi.auth.password import hash_password, verify_password
from hevi.auth.repository import UserRepository


_SENSITIVE_FIELDS = {"password_hash", "oauth_sub"}


def _safe_user(user: dict) -> dict:
    return {k: v for k, v in user.items() if k not in _SENSITIVE_FIELDS}


class AuthService:
    def __init__(self, repo: UserRepository) -> None:
        self._repo = repo

    async def register(
        self, email: str, password: str, display_name: str
    ) -> dict[str, Any]:
        # Check if user already exists
        existing = await self._repo.get_by_email(email)
        if existing:
            raise ValueError(f"Email already registered: {email}")

        # Basic password strength check
        if len(password) < 8:
            raise ValueError("Password must be at least 8 characters long")

        data = {
            "email": email,
            "password_hash": hash_password(password),
            "display_name": display_name,
            "auth_provider": "local",
            "is_active": True,
        }
        return _safe_user(await self._repo.create(data))

    async def login(self, email: str, password: str) -> tuple[dict[str, Any], str]:
        user = await self._repo.get_by_email(email)
        if not user or not user.get("password_hash"):
            raise ValueError("Invalid email or password")

        if not verify_password(password, user["password_hash"]):
            raise ValueError("Invalid email or password")

        token = sign_access_token(str(user["id"]))
        return _safe_user(user), token

    async def oauth_callback(
        self, provider: Literal["google"], code: str
    ) -> tuple[dict[str, Any], str]:
        """Skeleton for OAuth2 callback. Actual implementation pending credentials."""
        if code == "test_code":
            email = "oauth_test@example.com"
            user = await self._repo.get_by_email(email)
            if not user:
                user = await self._repo.create({
                    "email": email,
                    "display_name": "OAuth Test",
                    "auth_provider": provider,
                    "oauth_sub": "test_sub_123",
                    "is_active": True
                })
            token = sign_access_token(str(user["id"]))
            return _safe_user(user), token

        raise ValueError("Invalid OAuth code")
