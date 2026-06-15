from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from obase.persistence import PgPool

from hevi.auth.dependencies import get_current_user
from hevi.credits.account_service import AccountService
from hevi.credits.repository import CreditRepository
from hevi.db.pg_pool import get_hevi_pg_pool
from hevi.payment.order_service import OrderService
from hevi.payment.paddle_service import PaddleService
from hevi.payment.pricing_plans import CREDIT_PLANS
from hevi.payment.repository import OrderRepository
from hevi.payment.webhook_handler import WebhookHandler

router = APIRouter(prefix="/payment", tags=["payment"])


# ── Dependencies ──────────────────────────────────────────────────────────────


async def get_pg_pool() -> PgPool:
    return await get_hevi_pg_pool()


async def get_order_repository(pool: Annotated[PgPool, Depends(get_pg_pool)]) -> OrderRepository:
    return OrderRepository(pool)


async def get_order_service(
    repo: Annotated[OrderRepository, Depends(get_order_repository)],
    pool: Annotated[PgPool, Depends(get_pg_pool)],
) -> OrderService:
    paddle_svc = PaddleService()
    account_svc = AccountService(CreditRepository(pool))
    return OrderService(repo, paddle_svc, account_svc)


async def get_webhook_handler(
    order_svc: Annotated[OrderService, Depends(get_order_service)],
    repo: Annotated[OrderRepository, Depends(get_order_repository)],
) -> WebhookHandler:
    paddle_svc = PaddleService()
    return WebhookHandler(order_svc, paddle_svc, repo)


# ── Routes ────────────────────────────────────────────────────────────────────


@router.get("/plans")
async def list_plans() -> dict[str, dict[str, Any]]:
    """List available credit plans (public)."""
    return CREDIT_PLANS


@router.post("/checkout")
async def create_checkout(
    plan_id: str,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    svc: Annotated[OrderService, Depends(get_order_service)],
) -> dict[str, str]:
    """Initialize payment and get checkout URL."""
    try:
        url = await svc.create_checkout(
            user_id=str(user["id"]),
            email=user["email"],
            plan_id=plan_id
        )
        return {"checkout_url": url}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/webhook", include_in_schema=False)
async def paddle_webhook(
    request: Request,
    handler: Annotated[WebhookHandler, Depends(get_webhook_handler)],
    paddle_signature: Annotated[str | None, Header()] = None,
) -> dict[str, str]:
    """Paddle webhook endpoint (unprotected, uses signature verification)."""
    if not paddle_signature:
        raise HTTPException(status_code=401, detail="Missing signature")
    
    raw_body = await request.body()
    try:
        await handler.handle_webhook(raw_body, paddle_signature)
        return {"status": "ok"}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/orders")
async def list_my_orders(
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    repo: Annotated[OrderRepository, Depends(get_order_repository)],
    limit: int = 20,
) -> list[dict[str, Any]]:
    """List current user's orders."""
    return await repo.list_user_orders(user_id=str(user["id"]), limit=limit)
