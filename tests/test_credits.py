import uuid
from unittest.mock import AsyncMock, patch

import pytest

from hevi.credits.account_service import AccountService
from hevi.credits.billing_service import BillingService
from hevi.credits.repository import CreditRepository

SIGNUP_BONUS = 1000  # B: 新用户注册送 1000 credits


@pytest.mark.asyncio
async def test_estimate_credits(client):
    user_email = f"cred_est_{uuid.uuid4().hex[:6]}@example.com"
    user_payload = {
        "email": user_email, "password": "password123", "display_name": "Cred User"
    }
    await client.post("/api/auth/register", json=user_payload)
    login_resp = await client.post("/api/auth/login", json={
        "email": user_payload["email"], "password": user_payload["password"]
    })
    token = login_resp.json()["access_token"]

    payload = {"duration_archetype": "1-5min", "video_provider": "ltx2_cloud"}
    resp = await client.post(
        "/api/credits/estimate", json=payload, headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "credits_needed" in data
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

    # 新用户余额 = signup bonus(1000)
    resp = await client.get("/api/credits/balance", headers={"Authorization": f"Bearer {token}"})
    assert resp.json()["balance"] == SIGNUP_BONUS

    # Topup 1000
    await client.post(
        "/api/credits/topup",
        json={"amount": 1000, "order_ref": "ORD-1"},
        headers={"Authorization": f"Bearer {token}"}
    )

    # 余额 = signup bonus + topup
    resp = await client.get("/api/credits/balance", headers={"Authorization": f"Bearer {token}"})
    assert resp.json()["balance"] == SIGNUP_BONUS + 1000

    # 共 2 笔 transaction: signup_bonus + topup
    resp = await client.get(
        "/api/credits/transactions", headers={"Authorization": f"Bearer {token}"}
    )
    txs = resp.json()
    assert len(txs) == 2
    tx_types = {t["tx_type"] for t in txs}
    assert "topup" in tx_types


@pytest.mark.asyncio
async def test_consume_and_refund(client):
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
    # 余额 = 1000(signup) + 500(topup) = 1500

    from hevi.db.pg_pool import get_hevi_pg_pool
    pool = await get_hevi_pg_pool()
    repo = CreditRepository(pool)
    account_svc = AccountService(repo)
    billing_svc = BillingService(account_svc)

    # 1. Consume 200 → 1300
    await billing_svc.consume(user_id, 200, "TASK-1")
    assert await account_svc.get_balance(user_id) == SIGNUP_BONUS + 500 - 200

    # 2. Consume 超额(超过 1300)→ Insufficient
    with pytest.raises(ValueError, match="Insufficient credits"):
        await billing_svc.consume(user_id, 1400, "TASK-2")

    # 3. Refund 200 → 1300
    await billing_svc.refund(user_id, 200, "TASK-1")
    assert await account_svc.get_balance(user_id) == SIGNUP_BONUS + 500


@pytest.mark.asyncio
async def test_consume_refund_idempotent(client):
    """重复 consume/refund 同一 (user, reference, tx_type) 不得重复扣/退。"""
    user_email = f"idem_{uuid.uuid4().hex[:6]}@example.com"
    await client.post("/api/auth/register", json={
        "email": user_email, "password": "password123", "display_name": "Idem"
    })
    login_resp = await client.post("/api/auth/login", json={
        "email": user_email, "password": "password123"
    })
    user_id = login_resp.json()["user"]["id"]

    from hevi.db.pg_pool import get_hevi_pg_pool
    pool = await get_hevi_pg_pool()
    billing_svc = BillingService(AccountService(CreditRepository(pool)))

    # 重复 consume 同一 TASK-X：只扣一次
    await billing_svc.consume(user_id, 300, "TASK-X")
    await billing_svc.consume(user_id, 300, "TASK-X")
    await billing_svc.consume(user_id, 300, "TASK-X")
    acct = AccountService(CreditRepository(pool))
    assert await acct.get_balance(user_id) == SIGNUP_BONUS - 300

    # 重复 refund 同一 TASK-X：只退一次
    await billing_svc.refund(user_id, 300, "TASK-X")
    await billing_svc.refund(user_id, 300, "TASK-X")
    assert await acct.get_balance(user_id) == SIGNUP_BONUS


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

    # 新用户有 1000 credits(signup bonus),云任务需 720 → 直接够
    payload = {"topic": "Sci-fi", "duration_archetype": "1-5min", "video_provider": "ltx2_cloud"}
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

        import asyncio
        await asyncio.sleep(0.5)

        resp = await client.get(
            "/api/credits/balance", headers={"Authorization": f"Bearer {token}"}
        )
        assert resp.json()["balance"] == SIGNUP_BONUS - 720  # 1000 - 720 = 280


@pytest.mark.asyncio
async def test_cost_settlement_refunds_cheaper_actual(client):
    """实际成本 < 预扣(估算) → 完成后结算退差价,余额回升。"""
    import asyncio

    user_email = f"settle_{uuid.uuid4().hex[:6]}@example.com"
    await client.post("/api/auth/register", json={
        "email": user_email, "password": "password123", "display_name": "Settle"
    })
    login_resp = await client.post("/api/auth/login", json={
        "email": user_email, "password": "password123"
    })
    token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 估算按 1-5min(~180s) 预扣 720;实际只产出很短的视频 → 应退差价
    payload = {"topic": "Sci-fi", "duration_archetype": "1-5min", "video_provider": "ltx2_cloud"}
    with patch(
        "hevi.tasks.task_service.orchestrate_longvideo", new_callable=AsyncMock
    ) as mock_orch:
        mock_orch.return_value = {
            "url": "http://video.mp4", "duration": 20, "metadata": {"shots": 1}
        }
        resp = await client.post("/api/tasks/longvideo", json=payload, headers=headers)
        assert resp.status_code == 201
        await asyncio.sleep(0.5)

    balance = (await client.get("/api/credits/balance", headers=headers)).json()["balance"]
    # 预扣后是 280;实际成本远低 → 退差价 → 余额 > 280
    assert balance > SIGNUP_BONUS - 720
    txs = (await client.get("/api/credits/transactions", headers=headers)).json()
    assert any(t["tx_type"] == "refund" and str(t.get("reference", "")).endswith(":settle")
               for t in txs)


@pytest.mark.asyncio
async def test_task_cloud_insufficient_credits(client):
    """C 红线: 云任务余额不足 → 402(signup bonus 消耗完后)"""
    user_email = f"broke_{uuid.uuid4().hex[:6]}@example.com"
    await client.post("/api/auth/register", json={
        "email": user_email, "password": "password123", "display_name": "Broke"
    })
    login_resp = await client.post("/api/auth/login", json={
        "email": user_email, "password": "password123"
    })
    token = login_resp.json()["access_token"]
    user_id = login_resp.json()["user"]["id"]

    # 消耗掉所有 credits
    from hevi.db.pg_pool import get_hevi_pg_pool
    pool = await get_hevi_pg_pool()
    account_svc = AccountService(CreditRepository(pool))
    await account_svc.consume(user_id, SIGNUP_BONUS, "drain")

    # 云任务需 720 credits,余额 0 → 402
    payload = {"topic": "Sci-fi", "duration_archetype": "1-5min", "video_provider": "ltx2_cloud"}
    resp = await client.post(
        "/api/tasks/longvideo", json=payload, headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 402
    detail = resp.json()["detail"]
    assert detail["error"] == "insufficient_credits"
    assert detail["credits_needed"] > 0
    assert detail["credits_available"] == 0
