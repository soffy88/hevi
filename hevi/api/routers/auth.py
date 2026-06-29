from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from obase.persistence import PgPool
from pydantic import BaseModel, EmailStr

from hevi.api.rate_limit import rate_limit
from hevi.auth.auth_service import AuthService
from hevi.auth.dependencies import get_current_user, get_user_repository
from hevi.auth.repository import UserRepository
from hevi.credits.account_service import AccountService
from hevi.credits.repository import CreditRepository
from hevi.db.pg_pool import get_hevi_pg_pool

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    display_name: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class OAuthRequest(BaseModel):
    code: str


class TokenResponse(BaseModel):
    access_token: str
    token: str           # alias for frontend compatibility
    token_type: str = "bearer"
    user: dict[str, Any]


async def get_auth_service(
    repo: Annotated[UserRepository, Depends(get_user_repository)],
    pool: Annotated[PgPool, Depends(get_hevi_pg_pool)],
) -> AuthService:
    account_svc = AccountService(CreditRepository(pool))
    return AuthService(repo, account_svc=account_svc)


@router.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit("auth_register", max_requests=5, window_s=60))],
)
async def register(
    body: RegisterRequest,
    svc: Annotated[AuthService, Depends(get_auth_service)],
) -> TokenResponse:
    try:
        user, token = await svc.register(
            email=body.email, password=body.password, display_name=body.display_name
        )
        return TokenResponse(access_token=token, token=token, user=user)
    except ValueError as exc:
        status_code = (
            status.HTTP_409_CONFLICT
            if "already registered" in str(exc)
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@router.post(
    "/login",
    dependencies=[Depends(rate_limit("auth_login", max_requests=10, window_s=60))],
)
async def login(
    body: LoginRequest,
    svc: Annotated[AuthService, Depends(get_auth_service)],
) -> TokenResponse:
    try:
        user, token = await svc.login(email=body.email, password=body.password)
        return TokenResponse(access_token=token, token=token, user=user)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc


@router.get("/me")
async def get_me(
    current_user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    return current_user


@router.post(
    "/oauth/google",
    dependencies=[Depends(rate_limit("auth_oauth", max_requests=10, window_s=60))],
)
async def google_oauth(
    body: OAuthRequest,
    svc: Annotated[AuthService, Depends(get_auth_service)],
) -> TokenResponse:
    try:
        user, token = await svc.oauth_callback(provider="google", code=body.code)
        return TokenResponse(access_token=token, token=token, user=user)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
