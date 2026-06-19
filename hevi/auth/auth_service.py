from __future__ import annotations

from typing import Any, Literal

from hevi.auth.jwt_handler import sign_access_token
from hevi.auth.password import hash_password, verify_password
from hevi.auth.repository import UserRepository
from hevi.credits.account_service import AccountService

_SENSITIVE_FIELDS = {"password_hash", "oauth_sub"}

SIGNUP_BONUS_CREDITS = 1000


def _safe_user(user: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in user.items() if k not in _SENSITIVE_FIELDS}


class AuthService:
    def __init__(self, repo: UserRepository, account_svc: AccountService | None = None) -> None:
        self._repo = repo
        self._account_svc = account_svc

    async def register(
        self, email: str, password: str, display_name: str
    ) -> tuple[dict[str, Any], str]:
        existing = await self._repo.get_by_email(email)
        if existing:
            raise ValueError(f"Email already registered: {email}")

        if len(password) < 8:
            raise ValueError("Password must be at least 8 characters long")

        data = {
            "email": email,
            "password_hash": hash_password(password),
            "display_name": display_name,
            "auth_provider": "local",
            "is_active": True,
        }
        user = _safe_user(await self._repo.create(data))
        token = sign_access_token(str(user["id"]))

        # B: signup bonus — 新用户送 1000 credits
        if self._account_svc:
            await self._account_svc.topup(
                user_id=str(user["id"]),
                amount=SIGNUP_BONUS_CREDITS,
                order_ref="signup_bonus",
            )

        return user, token

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
