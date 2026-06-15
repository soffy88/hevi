from __future__ import annotations

import logging

from hevi.payment.order_service import OrderService
from hevi.payment.paddle_service import PaddleService
from hevi.payment.repository import OrderRepository

logger = logging.getLogger(__name__)


class WebhookHandler:
    def __init__(
        self, 
        order_svc: OrderService, 
        paddle_svc: PaddleService,
        repo: OrderRepository
    ):
        self._order_svc = order_svc
        self._paddle_svc = paddle_svc
        self._repo = repo

    async def handle_webhook(self, raw_body: bytes, signature: str) -> None:
        """Handle incoming Paddle webhook."""
        # 1. Verify signature
        if not self._paddle_svc.verify_webhook_signature(raw_body, signature):
            logger.warning("Invalid webhook signature")
            raise ValueError("Invalid signature")

        # 2. Parse payload
        import json
        try:
            payload = json.loads(raw_body)
        except json.JSONDecodeError:
            raise ValueError("Invalid JSON body") from None

        event_id = payload.get("event_id")
        event_type = payload.get("event_type")
        data = payload.get("data", {})
        
        if not event_id or not event_type:
            raise ValueError("Missing event_id or event_type")

        # 3. Idempotency check
        if await self._repo.is_event_processed(event_id):
            logger.info(f"Event {event_id} already processed, skipping")
            return

        # 4. Dispatch by event type
        # Note: Mapping depends on Paddle API version (v2 vs Billing)
        # Assuming modern Billing API event names
        if event_type == "transaction.completed":
            # In Paddle Billing, metadata or custom_data contains our internal order_id
            order_id = data.get("custom_data", {}).get("order_id")
            if order_id:
                await self._order_svc.fulfill_order(order_id, event_id)
            else:
                logger.error(f"Webhook {event_id} missing order_id in custom_data")
        
        elif event_type == "transaction.failed":
            order_id = data.get("custom_data", {}).get("order_id")
            if order_id:
                await self._order_svc.fail_order(order_id)
        
        else:
            logger.info(f"Unhandled webhook event type: {event_type}")
