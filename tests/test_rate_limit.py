"""Rate limiting — disabled under debug, enforced otherwise (per-IP sliding window)."""
import uuid
from typing import Any

import pytest

from hevi.api import rate_limit as rl
from hevi.core.config import settings


@pytest.fixture
def _enforce_limits():
    """Turn rate limiting on (conftest autouse sets debug=True, which disables it)
    and clear buckets so the test is isolated."""
    rl._BUCKETS.clear()
    prev = settings.debug
    settings.debug = False
    yield
    settings.debug = prev
    rl._BUCKETS.clear()


@pytest.mark.asyncio
async def test_login_rate_limited(client: Any, _enforce_limits: None) -> None:
    """auth_login 限 10/分钟 → 第 11 次 429。"""
    body = {"email": f"nope_{uuid.uuid4().hex[:6]}@example.com", "password": "wrongpass1"}
    statuses = []
    for _ in range(12):
        resp = await client.post("/api/auth/login", json=body)
        statuses.append(resp.status_code)
    # 前 10 次是正常的 401(凭证错),之后被 429 拦截
    assert 429 in statuses
    assert statuses[:10] == [401] * 10
    assert statuses[10] == 429


@pytest.mark.asyncio
async def test_limit_disabled_under_debug(client: Any) -> None:
    """debug 模式(测试默认)下不限流 — 连发不出现 429。"""
    rl._BUCKETS.clear()
    body = {"email": f"nope_{uuid.uuid4().hex[:6]}@example.com", "password": "wrongpass1"}
    statuses = [
        (await client.post("/api/auth/login", json=body)).status_code for _ in range(15)
    ]
    assert 429 not in statuses
