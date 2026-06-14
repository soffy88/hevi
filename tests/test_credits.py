import uuid
from unittest.mock import AsyncMock, patch

import pytest

from hevi.credits.account_service import AccountService
from hevi.credits.billing_service import BillingService
from hevi.credits.repository import CreditRepository


@pytest.mark.asyncio
async def test_estimate_credits(client):
    # Register and get token
    user_email = f"cred_est_{uuid.uuid4().hex[:6]}@example.com"
    user_payload = {
        "email": user_email, "password": "password123", "display_name": "Cred User"
    }
    await client.post("/api/auth/register", json=user_payload)
    login_resp = await client.post("/api/auth/login", json={
        "email": user_payload["email"], "password": user_payload["password"]
    })
    token = login_resp.json()["access_token"]
    
    # Test estimate route
    payload = {"duration_archetype": "1-5min", "video_provider": "ltx2_cloud"}
    resp = await client.post(
        "/api/credits/estimate", json=payload, headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "credits_needed" in data
    # 1-5min = 180s * 0.04 = $7.20 = 720 credits
    assert data["credits_needed"] == 720

@pytest.mark.asyncio
async def test_topup_and_balance(client):
    user_email = f"topup_{uuid.uuid4().hex[:6]}@example.com"
    user_payload = {"email": user_email, "password": "password123", "display_name": "User"}
    await client.post("/api/auth/register", json=user_payload)
    login_resp = await client.post("/api/auth/login", json={
        "email": user_payload["email"], "password": user_payload["password"]
    })
    token = login_resp.json()["access_token"]

    # Check balance (should be 0)
    resp = await client.get("/api/credits/balance", headers={"Authorization": f"Bearer {token}"})
    assert resp.json()["balance"] == 0

    # Topup
    await client.post(
        "/api/credits/topup", 
        json={"amount": 1000, "order_ref": "ORD-1"}, 
        headers={"Authorization": f"Bearer {token}"}
    )
    
    # Check balance (should be 1000)
    resp = await client.get("/api/credits/balance", headers={"Authorization": f"Bearer {token}"})
    assert resp.json()["balance"] == 1000

    # List transactions
    resp = await client.get(
        "/api/credits/transactions", headers={"Authorization": f"Bearer {token}"}
    )
    txs = resp.json()
    assert len(txs) == 1
    assert txs[0]["tx_type"] == "topup"
    assert txs[0]["amount"] == 1000

@pytest.mark.asyncio
async def test_consume_and_refund(client):
    # Setup user with credits
    user_email = f"tx_{uuid.uuid4().hex[:6]}@example.com"
    await client.post("/api/auth/register", json={
        "email": user_email, "password": "password123", "display_name": "TX"
    })
    login_resp = await client.post("/api/auth/login", json={
        "email": user_email, "password": "password123"
    })
    token = login_resp.json()["access_token"]
    user_id = login_resp.json()["user"]["id"]

    await client.post(
        "/api/credits/topup", json={"amount": 500}, headers={"Authorization": f"Bearer {token}"}
    )
    
    from hevi.db.pg_pool import get_hevi_pg_pool
    pool = await get_hevi_pg_pool()
    repo = CreditRepository(pool)
    account_svc = AccountService(repo)
    billing_svc = BillingService(account_svc)

    # 1. Consume
    await billing_svc.consume(user_id, 200, "TASK-1")
    assert await account_svc.get_balance(user_id) == 300

    # 2. Insufficient
    with pytest.raises(ValueError, match="Insufficient credits"):
        await billing_svc.consume(user_id, 400, "TASK-2")
    
    # 3. Refund
    await billing_svc.refund(user_id, 200, "TASK-1")
    assert await account_svc.get_balance(user_id) == 500

@pytest.mark.asyncio
async def test_task_integration_credits(client):
    user_email = f"task_cred_{uuid.uuid4().hex[:6]}@example.com"
    await client.post("/api/auth/register", json={
        "email": user_email, "password": "password123", "display_name": "TaskUser"
    })
    login_resp = await client.post("/api/auth/login", json={
        "email": user_email, "password": "password123"
    })
    token = login_resp.json()["access_token"]

    # Create task (should fail with 402 Insufficient credits)
    payload = {"topic": "Sci-fi", "duration_archetype": "1-5min", "video_provider": "ltx2_cloud"}
    resp = await client.post(
        "/api/tasks/longvideo", json=payload, headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 402
    assert "Insufficient credits" in resp.json()["detail"]

    # Topup
    await client.post(
        "/api/credits/topup", json={"amount": 1000}, headers={"Authorization": f"Bearer {token}"}
    )

    # Create task (should succeed)
    with patch(
        "hevi.tasks.task_service.orchestrate_longvideo", new_callable=AsyncMock
    ) as mock_orch:
        mock_orch.return_value = {
            "url": "http://video.mp4", "duration": 180, "metadata": {"shots": 5}
        }
        resp = await client.post(
            "/api/tasks/longvideo", json=payload, headers={"Authorization": f"Bearer {token}"}
        )
        assert resp.status_code == 201
        
        # Balance should be deducted once task starts (in background)
        import asyncio
        await asyncio.sleep(0.5)
        
        resp = await client.get(
            "/api/credits/balance", headers={"Authorization": f"Bearer {token}"}
        )
        assert resp.json()["balance"] == 1000 - 720 # 280
