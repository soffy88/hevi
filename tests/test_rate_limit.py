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
    statuses = [(await client.post("/api/auth/login", json=body)).status_code for _ in range(15)]
    assert 429 not in statuses


@pytest.mark.asyncio
async def test_video_submit_rate_limited(client: Any, _enforce_limits: None) -> None:
    """出片提交 (/api/pipeline/generate) 限 10/分钟 → 第 11 次 429。"""
    body = {
        "source_channel": "hub_quick",
        "adapter_type": "default",
        "config": {"prompt": "rate limit probe"},
    }
    statuses = [
        (await client.post("/api/pipeline/generate", json=body)).status_code
        for _ in range(12)
    ]
    assert all(s != 429 for s in statuses[:10])
    assert statuses[10] == 429


@pytest.mark.asyncio
async def test_canvas_execute_rate_limited(client: Any, _enforce_limits: None) -> None:
    """画布出片执行 (/api/canvas/{id}/execute) 限 20/分钟 → 第 21 次 429。"""
    statuses = [
        (await client.post("/api/canvas/not-a-real-graph/execute", json={})).status_code
        for _ in range(22)
    ]
    assert all(s != 429 for s in statuses[:20])
    assert statuses[20] == 429


@pytest.mark.asyncio
async def test_per_user_bucket_isolated(_enforce_limits: None) -> None:
    """per_user=True 时按 JWT sub 分桶：同一用户连发触发 429，另一用户不受影响。"""
    from fastapi import HTTPException
    from starlette.requests import Request

    from hevi.auth.jwt_handler import sign_access_token

    def _request(token: str) -> Request:
        return Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/api/pipeline/generate",
                "headers": [(b"authorization", f"Bearer {token}".encode())],
                "client": ("203.0.113.9", 12345),
            }
        )

    dep = rl.rate_limit("probe_user", max_requests=1, window_s=60, per_user=True)
    a, b = _request(sign_access_token("user-a")), _request(sign_access_token("user-b"))
    await dep(a)
    with pytest.raises(HTTPException) as exc:
        await dep(a)
    assert exc.value.status_code == 429
    await dep(b)  # 不同用户独立桶，不触发
