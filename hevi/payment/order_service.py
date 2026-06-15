from __future__ import annotations

from datetime import datetime
from typing import Any

from hevi.credits.account_service import AccountService
from hevi.payment.paddle_service import PaddleService
from hevi.payment.pricing_plans import get_plan
from hevi.payment.repository import OrderRepository


class OrderService:
    def __init__(
        self, 
        repo: OrderRepository, 
        paddle_svc: PaddleService,
        account_svc: AccountService
    ):
        self._repo = repo
        self._paddle_svc = paddle_svc
        self._account_svc = account_svc

    async def create_checkout(self, user_id: str, email: str, plan_id: str) -> str:
        """Initialize order and return Paddle checkout URL."""
        plan = get_plan(plan_id)
        
        # 1. Create pending order in DB
        order_data = {
            "user_id": user_id,
            "plan_id": plan_id,
            "credits": plan["credits"],
            "amount_usd": plan["price_usd"],
            "status": "pending",
        }
        order = await self._repo.create_order(order_data)
        
        # 2. Call Paddle
        session = await self._paddle_svc.create_checkout_session(
            price_id=plan["paddle_price_id"],
            user_id=user_id,
            email=email
        )
        
        # 3. Update order with paddle checkout ID
        await self._repo.update_order(str(order["id"]), {"paddle_checkout_id": session["id"]})
        
        return str(session["url"])

    async def fulfill_order(self, order_id: str, event_id: str) -> dict[str, Any]:
        """Mark order as completed and topup credits."""
        order = await self._repo.get_order(order_id)
        if not order:
            raise ValueError(f"Order not found: {order_id}")
        
        if order["status"] == "completed":
            return order # Already fulfilled

        # 1. Update order status
        updated = await self._repo.update_order(
            order_id, 
            {
                "status": "completed", 
                "completed_at": datetime.utcnow(),
                "paddle_event_id": event_id
            }
        )
        
        # 2. Topup user account
        await self._account_svc.topup(
            user_id=str(order["user_id"]),
            amount=order["credits"],
            order_ref=order_id
        )
        
        return updated or {}

    async def fail_order(self, order_id: str, error_msg: str | None = None) -> None:
        """Mark order as failed."""
        await self._repo.update_order(order_id, {"status": "failed"})
