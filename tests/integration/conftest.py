"""Shared fixtures for the production integration acceptance tests.

These fixtures deliberately expose a real ``obase.persistence.PgPool``. The
tests must never silently fall back to SQLite, a fake repository, or an
in-memory database.
"""

from __future__ import annotations

import os
import uuid

import pytest


@pytest.fixture(scope="session")
def pg_dsn() -> str:
    return os.getenv("HEVI_TEST_DSN", "postgresql://hevi:hevi@localhost:5432/hevi")


@pytest.fixture
async def pool(pg_dsn: str):
    # Use the same composition-root pool as production so JSON/JSONB codecs
    # are registered exactly as they are for API/worker processes.
    from hevi.db.pg_pool import get_hevi_pg_pool

    pool = await get_hevi_pg_pool()
    yield pool


@pytest.fixture
def test_run_id() -> str:
    return uuid.uuid4().hex


def ref(test_run_id: str, name: str) -> str:
    return f"{name}:{test_run_id}"


@pytest.fixture
async def fresh_user(pool):
    """Create a disposable user/account for integration tests that need it."""

    user_id = uuid.uuid4()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO users
                (id, email, display_name, auth_provider, is_active, created_at, updated_at)
            VALUES ($1, $2, $3, 'password', TRUE, NOW(), NOW())
            """,
            user_id,
            f"itest_{user_id.hex}@example.com",
            "Integration Test User",
        )
        await conn.execute(
            """
            INSERT INTO credit_accounts (user_id, balance, reserved_balance, updated_at)
            VALUES ($1, 0, 0, NOW())
            """,
            user_id,
        )
    return str(user_id)
