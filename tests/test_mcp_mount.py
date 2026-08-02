from __future__ import annotations

from unittest.mock import patch

import pytest

from hevi.api.mcp_mount import authenticated_mcp_app
from hevi.mcp.auth_context import require_mcp_actor


@pytest.mark.asyncio
async def test_authenticated_mcp_app_binds_verified_token_subject() -> None:
    async def inner(scope, receive, send):
        assert scope["type"] == "http"
        assert require_mcp_actor() == "user-1"
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    sent = []

    async def send(message):
        sent.append(message)

    with patch("hevi.api.mcp_mount.decode_access_token", return_value={"sub": "user-1"}):
        await authenticated_mcp_app(inner)(
            {"type": "http", "headers": [(b"authorization", b"Bearer valid")]},
            None,
            send,
        )

    assert sent[0]["status"] == 200


@pytest.mark.asyncio
async def test_authenticated_mcp_app_rejects_missing_token() -> None:
    async def inner(scope, receive, send):
        raise AssertionError("anonymous request reached MCP app")

    sent = []

    async def send(message):
        sent.append(message)

    await authenticated_mcp_app(inner)({"type": "http", "headers": []}, None, send)

    assert sent[0]["status"] == 401


@pytest.mark.asyncio
async def test_authenticated_mcp_app_rejects_token_without_subject() -> None:
    async def inner(scope, receive, send):
        raise AssertionError("subjectless token reached MCP app")

    sent = []

    async def send(message):
        sent.append(message)

    with patch("hevi.api.mcp_mount.decode_access_token", return_value={}):
        await authenticated_mcp_app(inner)(
            {"type": "http", "headers": [(b"authorization", b"Bearer valid")]},
            None,
            send,
        )

    assert sent[0]["status"] == 401
