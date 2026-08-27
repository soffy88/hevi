"""P0-D Integration Tests: Transactional Billing Reservation with real PostgreSQL.

Tests bypass the mock layer and exercise BillingService against a live database.
RUN:
    DATABASE_URL=postgresql://hevi:hevi@localhost:5432/hevi \
    uv run pytest tests/integration/test_billing_reservation_p0d.py -v
"""

import asyncio
import os
import uuid

import pytest
from obase.persistence import PgPool

from hevi.credits.account_service import AccountService
from hevi.credits.billing_service import (
    BillingService,
    InsufficientCredits,
)
from hevi.credits.repository import CreditRepository

# Unique per test run so external_ref is never reused (idempotency isolation)
TEST_RUN_ID = uuid.uuid4().hex[:8]


def ref(name: str) -> str:
    return f"{name}:{TEST_RUN_ID}"


@pytest.fixture
async def pool():
    pg_url = os.getenv("HEVI_TEST_DSN", "postgresql://hevi:hevi@localhost:5432/hevi")
    pool = await PgPool.create(name='billing_test', dsn=pg_url)
    yield pool
    await pool.close()


@pytest.fixture
async def account_svc(pool):
    repo = CreditRepository(pool)
    return AccountService(repo)


@pytest.fixture
async def billing_svc(account_svc, pool):
    return BillingService(account_svc, pool=pool)


@pytest.fixture
async def fresh_user(pool):
    """Create a fresh user with known balance for testing."""
    user_id = uuid.uuid4()
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO users (id, email, display_name, auth_provider, is_active, created_at, updated_at) 
               VALUES ($1, $2, $3, $4, $5, NOW(), NOW())""",
            user_id,
            f"billing_test_{user_id.hex[:8]}@example.com",
            "Test User",
            "password",
            True,
        )
        await conn.execute(
            """INSERT INTO credit_accounts (user_id, balance, reserved_balance, updated_at)
               VALUES ($1, 0, 0, NOW())""",
            user_id,
        )
    return str(user_id)


async def _set_balance(pool, user_id: str, balance: int) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE credit_accounts SET balance=$1, reserved_balance=0 WHERE user_id=$2",
            balance,
            uuid.UUID(user_id),
        )


async def _get_account(pool, user_id: str) -> dict:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT balance, reserved_balance FROM credit_accounts WHERE user_id=$1",
            uuid.UUID(user_id),
        )
        return dict(row)


# ============ TEST 1: Basic reserve + consume ============
@pytest.mark.asyncio
async def test_reserve_consume_basic(pool, account_svc, billing_svc, fresh_user):
    user_id = fresh_user
    await _set_balance(pool, user_id, 1000)

    res = await billing_svc.reserve(user_id, 100, external_ref=ref("t1:reserve"))
    assert res["status"] == "active"
    assert res["amount_cents"] == 100

    acct = await _get_account(pool, user_id)
    assert acct["balance"] == 1000, f"balance={acct['balance']} expected 1000"
    assert acct["reserved_balance"] == 100, f"reserved={acct['reserved_balance']} expected 100"

    # Consume 80
    consumed = await billing_svc.consume(res["id"], 80, external_ref=ref("t1:consume"))
    assert consumed["status"] == "consumed"

    acct = await _get_account(pool, user_id)
    assert acct["balance"] == 920, f"balance={acct['balance']} expected 920"
    assert acct["reserved_balance"] == 0, f"reserved={acct['reserved_balance']} expected 0"
    assert acct["balance"] - acct["reserved_balance"] == 920, f"available={acct['balance'] - acct['reserved_balance']} expected 920"


# ============ TEST 2: Full consume ============
@pytest.mark.asyncio
async def test_reserve_full_consume(pool, account_svc, billing_svc, fresh_user):
    user_id = fresh_user
    await _set_balance(pool, user_id, 1000)

    res = await billing_svc.reserve(user_id, 100, external_ref=ref("t2:reserve"))
    await billing_svc.consume(res["id"], 100, external_ref=ref("t2:consume"))

    acct = await _get_account(pool, user_id)
    assert acct["balance"] == 900, f"balance={acct['balance']} expected 900"
    assert acct["reserved_balance"] == 0, f"reserved={acct['reserved_balance']} expected 0"


# ============ TEST 3: Release ============
@pytest.mark.asyncio
async def test_reserve_release(pool, account_svc, billing_svc, fresh_user):
    user_id = fresh_user
    await _set_balance(pool, user_id, 1000)

    res = await billing_svc.reserve(user_id, 100, external_ref=ref("t3:reserve"))
    await billing_svc.release(res["id"], external_ref=ref("t3:release"))

    acct = await _get_account(pool, user_id)
    assert acct["balance"] == 1000, f"balance={acct['balance']} expected 1000"
    assert acct["reserved_balance"] == 0, f"reserved={acct['reserved_balance']} expected 0"


# ============ TEST 4: Double consume idempotency ============
@pytest.mark.asyncio
async def test_double_consume_idempotent(pool, account_svc, billing_svc, fresh_user):
    user_id = fresh_user
    await _set_balance(pool, user_id, 1000)

    res = await billing_svc.reserve(user_id, 100, external_ref=ref("t4:reserve"))
    await billing_svc.consume(res["id"], 80, external_ref=ref("t4:consume"))
    # Second consume with same amount is idempotent (no additional charge)
    result2 = await billing_svc.consume(res["id"], 80, external_ref=ref("t4:consume"))
    assert result2["status"] == "consumed"
    assert result2["consumed_amount_cents"] == 80

    acct = await _get_account(pool, user_id)
    assert acct["balance"] == 920, f"balance={acct['balance']} expected 920"
    assert acct["reserved_balance"] == 0, f"reserved={acct['reserved_balance']} expected 0"


# ============ TEST 5: Double release idempotency ============
@pytest.mark.asyncio
async def test_double_release_idempotent(pool, account_svc, billing_svc, fresh_user):
    user_id = fresh_user
    await _set_balance(pool, user_id, 1000)

    res = await billing_svc.reserve(user_id, 100, external_ref=ref("t5:reserve"))
    await billing_svc.release(res["id"], external_ref=ref("t5:release"))
    await billing_svc.release(res["id"], external_ref=ref("t5:release2"))  # idempotent

    acct = await _get_account(pool, user_id)
    assert acct["balance"] == 1000, f"balance={acct['balance']} expected 1000"
    assert acct["reserved_balance"] == 0, f"reserved={acct['reserved_balance']} expected 0"


# ============ TEST 6: Concurrent reserve (only 1 succeeds) ============
@pytest.mark.asyncio
async def test_concurrent_reserve_race(pool, account_svc, billing_svc, fresh_user):
    """Two concurrent reserve(80) on balance=100: exactly one succeeds."""
    user_id = fresh_user
    await _set_balance(pool, user_id, 100)

    async def _try_reserve(ref_name):
        try:
            return await billing_svc.reserve(user_id, 80, external_ref=ref(ref_name))
        except InsufficientCredits:
            return None

    # Run concurrently
    results = await asyncio.gather(
        _try_reserve("t6:r1"),
        _try_reserve("t6:r2"),
        return_exceptions=False,
    )

    successes = [r for r in results if r is not None]
    assert len(successes) == 1, f"expected exactly 1 success, got {len(successes)}"

    acct = await _get_account(pool, user_id)
    assert acct["reserved_balance"] == 80, f"reserved={acct['reserved_balance']} expected 80"
    assert acct["balance"] == 100, f"balance={acct['balance']} expected 100"
    assert acct["reserved_balance"] != 160, "reserved_balance must not be 160"


# ============ TEST 7: Reservation ID persistence ============
@pytest.mark.asyncio
async def test_reservation_persistence(pool, account_svc, billing_svc, fresh_user):
    """Reservation ID must be recoverable from DB after "worker restart"."""
    user_id = fresh_user
    await _set_balance(pool, user_id, 1000)

    res = await billing_svc.reserve(user_id, 100, task_id=str(uuid.uuid4()), external_ref=ref("t7:reserve"))
    reservation_id = res["id"]

    # Simulate worker restart: read from DB by task_id
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, status FROM billing_reservations WHERE external_ref=$1",
            ref("t7:reserve"),
        )
        assert row is not None
        assert str(row["id"]) == reservation_id
        assert row["status"] == "active"

    # Recover and consume
    await billing_svc.consume(reservation_id, 50, external_ref=ref("t7:consume"))
    acct = await _get_account(pool, user_id)
    assert acct["balance"] == 950
    assert acct["reserved_balance"] == 0


# ============ TEST 8: Release after provider submit failure ============
@pytest.mark.asyncio
async def test_release_on_provider_failure(pool, account_svc, billing_svc, fresh_user):
    user_id = fresh_user
    await _set_balance(pool, user_id, 1000)

    res = await billing_svc.reserve(user_id, 100, external_ref=ref("t8:reserve"))
    # Provider submit failed before consume
    await billing_svc.release(res["id"], external_ref=ref("t8:release"))

    acct = await _get_account(pool, user_id)
    assert acct["balance"] == 1000
    assert acct["reserved_balance"] == 0


# ============ TEST 9: Refund after consume ============
@pytest.mark.asyncio
async def test_refund_after_consume(pool, account_svc, billing_svc, fresh_user):
    user_id = fresh_user
    await _set_balance(pool, user_id, 1000)

    task_id = uuid.uuid4()
    res = await billing_svc.reserve(user_id, 100, task_id=str(task_id), external_ref=ref("t9:reserve"))
    await billing_svc.consume(res["id"], 100, external_ref=ref("t9:consume"))

    acct_before = await _get_account(pool, user_id)
    assert acct_before["balance"] == 900

    # Refund 50 (partial)
    await billing_svc.refund_consumed(str(task_id), 50, external_ref=ref("t9:refund"))
    acct_after = await _get_account(pool, user_id)
    assert acct_after["balance"] == 950, f"balance={acct_after['balance']} expected 950"
    assert acct_after["reserved_balance"] == 0, f"reserved={acct_after['reserved_balance']} expected 0"


# ============ TEST 10: Double refund idempotency ============
@pytest.mark.asyncio
async def test_double_refund_idempotent(pool, account_svc, billing_svc, fresh_user):
    user_id = fresh_user
    await _set_balance(pool, user_id, 1000)

    task_id = uuid.uuid4()
    res = await billing_svc.reserve(user_id, 100, task_id=str(task_id), external_ref=ref("t10:reserve"))
    await billing_svc.consume(res["id"], 100, external_ref=ref("t10:consume"))
    await billing_svc.refund_consumed(str(task_id), 50, external_ref=ref("t10:refund1"))

    acct_before = await _get_account(pool, user_id)
    assert acct_before["balance"] == 950

    # Second refund with same amount: must not double-add
    await billing_svc.refund_consumed(str(task_id), 50, external_ref=ref("t10:refund1"))
    acct_after = await _get_account(pool, user_id)
    assert acct_after["balance"] == 950, f"balance={acct_after['balance']} expected 950 (not 1000)"
    assert acct_after["reserved_balance"] == 0


# ============ TEST 11: reserved_balance never negative ============
@pytest.mark.asyncio
async def test_reserved_balance_never_negative(pool, account_svc, billing_svc, fresh_user):
    user_id = fresh_user
    await _set_balance(pool, user_id, 1000)

    res = await billing_svc.reserve(user_id, 100, external_ref=ref("t11:reserve"))
    await billing_svc.consume(res["id"], 50, external_ref=ref("t11:consume"))
    # reserved should be exactly 0 after consume (full reservation released)
    acct = await _get_account(pool, user_id)
    assert acct["reserved_balance"] == 0, f"reserved={acct['reserved_balance']} must be 0 not negative"
    assert acct["reserved_balance"] >= 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
