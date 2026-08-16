"""Mount hevi MCP server onto the FastAPI application at /mcp."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from fastapi import FastAPI

from hevi.auth.jwt_handler import decode_access_token
from hevi.mcp.auth_context import reset_mcp_actor, set_mcp_actor
from hevi.mcp.server import build_hevi_mcp_server


def authenticated_mcp_app(app: Any) -> Any:
    """Require a verified bearer token and expose its subject to MCP handlers."""

    async def _app(scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await app(scope, receive, send)
            return
        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        authorization = headers.get(b"authorization", b"").decode("latin-1")
        if not authorization.startswith("Bearer "):
            await send(
                {
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [(b"content-type", b"application/json")],
                }
            )
            await send(
                {
                    "type": "http.response.body",
                    "body": b'{"detail":"Missing MCP bearer token"}',
                }
            )
            return
        try:
            subject = decode_access_token(authorization.removeprefix("Bearer ")).get("sub")
            if not isinstance(subject, str) or not subject:
                raise ValueError("token has no subject")
            user_id = subject
        except Exception:
            await send(
                {
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [(b"content-type", b"application/json")],
                }
            )
            await send(
                {
                    "type": "http.response.body",
                    "body": b'{"detail":"Invalid MCP bearer token"}',
                }
            )
            return
        token = set_mcp_actor(user_id)
        try:
            await app(scope, receive, send)
        finally:
            reset_mcp_actor(token)

    return _app


def mount_mcp(app: FastAPI) -> None:
    """Attach hevi MCP server to FastAPI at /mcp (Streamable HTTP transport)."""
    server = build_hevi_mcp_server()
    asgi_app: Any = server._fastmcp.streamable_http_app()
    app.mount("/mcp", authenticated_mcp_app(asgi_app))

    # mcp 2.0: mount 子 app lifespan 不自动运行 → 500 task group;
    # 包装现有 lifespan 托管 mcp lifespan (main.py 零改动)。
    from contextlib import asynccontextmanager

    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def _combined(application: FastAPI) -> AsyncIterator[None]:
        async with (
            original_lifespan(application),
            asgi_app.router.lifespan_context(application),
        ):
            yield

    app.router.lifespan_context = _combined
