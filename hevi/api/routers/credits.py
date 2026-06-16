from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from obase.persistence import PgPool
from pydantic import BaseModel

from hevi.auth.dependencies import get_current_user
from hevi.credits.account_service import AccountService
from hevi.credits.billing_service import BillingService
from hevi.credits.repository import CreditRepository
from hevi.db.pg_pool import get_hevi_pg_pool

router = APIRouter(prefix="/credits", tags=["credits"])


# ── Request schemas ───────────────────────────────────────────────────────────


class EstimateCreditsRequest(BaseModel):
    duration_archetype: str
    video_provider: str = "ltx2_cloud"
    ltx2_tier: str = "fast"
    quality_profile: str = "standard"
    num_characters: int = 1


class TopupRequest(BaseModel):
    amount: int
    order_ref: str | None = None


# ── Dependencies ──────────────────────────────────────────────────────────────


async def get_pg_pool() -> PgPool:
    return await get_hevi_pg_pool()


async def get_account_service(
    pool: Annotated[PgPool, Depends(get_pg_pool)],
) -> AccountService:
    return AccountService(CreditRepository(pool))


async def get_billing_service(
    account_svc: Annotated[AccountService, Depends(get_account_service)],
) -> BillingService:
    return BillingService(account_svc)


# ── Routes ────────────────────────────────────────────────────────────────────


@router.get("/balance")
async def get_balance(
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    svc: Annotated[AccountService, Depends(get_account_service)],
) -> dict[str, Any]:
    balance = await svc.get_balance(str(user["id"]))
    return {"user_id": user["id"], "balance": balance}


@router.get("/transactions")
async def list_transactions(
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    svc: Annotated[AccountService, Depends(get_account_service)],
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> list[dict[str, Any]]:
    return await svc.list_transactions(str(user["id"]), limit=limit, offset=offset)


@router.post("/estimate")
async def estimate_credits(
    body: EstimateCreditsRequest,
    svc: Annotated[BillingService, Depends(get_billing_service)],
) -> dict[str, Any]:
    credits_needed = await svc.estimate_credits(
        duration_archetype=body.duration_archetype,
        video_provider=body.video_provider,
        ltx2_tier=body.ltx2_tier,
        quality_profile=body.quality_profile,
        num_characters=body.num_characters,
    )
    return {"credits": credits_needed, "credits_needed": credits_needed}


@router.post("/topup")
async def manual_topup(
    body: TopupRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    svc: Annotated[AccountService, Depends(get_account_service)],
) -> dict[str, Any]:
    """Manual topup for dev/webhook use."""
    return await svc.topup(
        user_id=str(user["id"]), 
        amount=body.amount, 
        order_ref=body.order_ref
    )
