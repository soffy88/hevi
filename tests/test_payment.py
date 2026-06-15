import json
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from hevi.payment.repository import OrderRepository


async def _register_and_login(client, email):
    await client.post("/api/auth/register", json={
        "email": email, "password": "password123", "display_name": email.split("@")[0]
    })
    resp = await client.post("/api/auth/login", json={"email": email, "password": "password123"})
    return {"token": resp.json()["access_token"], "user": resp.json()["user"]}


@pytest.mark.asyncio
async def test_list_plans(client):
    resp = await client.get("/api/payment/plans")
    assert resp.status_code == 200
    assert "starter" in resp.json()
    assert resp.json()["starter"]["credits"] == 1000


@pytest.mark.asyncio
async def test_checkout_create_order(client):
    user_email = f"pay_{uuid.uuid4().hex[:6]}@example.com"
    user = await _register_and_login(client, user_email)
    token = user["token"]

    _target = "hevi.payment.paddle_service.PaddleService.create_checkout_session"
    with patch(_target, new_callable=AsyncMock) as mock_paddle:
        mock_paddle.return_value = {"id": "ct_123", "url": "https://paddle.com/checkout"}
        
        resp = await client.post(
            "/api/payment/checkout?plan_id=starter",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert resp.status_code == 200
        assert resp.json()["checkout_url"] == "https://paddle.com/checkout"
        
        # Verify order in list
        resp = await client.get(
            "/api/payment/orders", headers={"Authorization": f"Bearer {token}"}
        )
        orders = resp.json()
        assert len(orders) == 1
        assert orders[0]["plan_id"] == "starter"
        assert orders[0]["status"] == "pending"


@pytest.mark.asyncio
async def test_webhook_fulfillment(client):
    user_email = f"web_{uuid.uuid4().hex[:6]}@example.com"
    user = await _register_and_login(client, user_email)
    token = user["token"]
    user_id = user["user"]["id"]

    from hevi.db.pg_pool import get_hevi_pg_pool
    pool = await get_hevi_pg_pool()
    repo = OrderRepository(pool)
    
    order = await repo.create_order({
        "user_id": uuid.UUID(user_id),
        "plan_id": "starter",
        "credits": 1000,
        "amount_usd": 9.9,
        "status": "pending"
    })
    order_id = str(order["id"])

    payload = {
        "event_id": f"evt_{uuid.uuid4().hex}",
        "event_type": "transaction.completed",
        "data": {"custom_data": {"order_id": order_id}}
    }
    raw_body = json.dumps(payload).encode()
    
    _v_sig = "hevi.payment.paddle_service.PaddleService.verify_webhook_signature"
    _topup = "hevi.payment.order_service.AccountService.topup"
    with patch(_v_sig, return_value=True), \
         patch(_topup, new_callable=AsyncMock) as mock_topup:
        
        resp = await client.post(
            "/api/payment/webhook",
            content=raw_body,
            headers={"Paddle-Signature": "valid_sig"}
        )
        assert resp.status_code == 200
        mock_topup.assert_awaited_once()
        assert mock_topup.call_args.kwargs["amount"] == 1000
        
        resp = await client.get(
            "/api/payment/orders", headers={"Authorization": f"Bearer {token}"}
        )
        assert resp.json()[0]["status"] == "completed"


@pytest.mark.asyncio
async def test_webhook_idempotency(client):
    user_email = f"idem_{uuid.uuid4().hex[:6]}@example.com"
    user = await _register_and_login(client, user_email)
    user_id = user["user"]["id"]

    from hevi.db.pg_pool import get_hevi_pg_pool
    pool = await get_hevi_pg_pool()
    repo = OrderRepository(pool)
    
    order = await repo.create_order({
        "user_id": uuid.UUID(user_id),
        "plan_id": "starter", "credits": 1000, "amount_usd": 9.9, "status": "pending"
    })
    order_id = str(order["id"])
    event_id = f"evt_once_{uuid.uuid4().hex}"

    payload = {
        "event_id": event_id,
        "event_type": "transaction.completed",
        "data": {"custom_data": {"order_id": order_id}}
    }
    raw_body = json.dumps(payload).encode()

    _v_sig = "hevi.payment.paddle_service.PaddleService.verify_webhook_signature"
    _topup = "hevi.payment.order_service.AccountService.topup"
    with patch(_v_sig, return_value=True), \
         patch(_topup, new_callable=AsyncMock) as mock_topup:
        
        await client.post(
            "/api/payment/webhook", content=raw_body, headers={"Paddle-Signature": "sig"}
        )
        assert mock_topup.call_count == 1
        
        await client.post(
            "/api/payment/webhook", content=raw_body, headers={"Paddle-Signature": "sig"}
        )
        assert mock_topup.call_count == 1


@pytest.mark.asyncio
async def test_webhook_invalid_signature(client):
    payload = {"event_id": "evt_fail", "event_type": "any"}
    raw_body = json.dumps(payload).encode()

    _v_sig = "hevi.payment.paddle_service.PaddleService.verify_webhook_signature"
    with patch(_v_sig, return_value=False):
        resp = await client.post(
            "/api/payment/webhook",
            content=raw_body,
            headers={"Paddle-Signature": "wrong"}
        )
        assert resp.status_code == 400
        assert "Invalid signature" in resp.json()["detail"]
