"""Mount hevi MCP server onto the FastAPI application at /mcp."""

from __future__ import annotations

import json
import os
import time
from collections import defaultdict, deque
from collections.abc import AsyncIterator
from typing import Any

from fastapi import FastAPI

from hevi.auth.jwt_handler import decode_access_token
from hevi.mcp.auth_context import reset_mcp_actor, set_mcp_actor
from hevi.mcp.server import build_hevi_mcp_server

_MCP_HITS: dict[str, deque[float]] = defaultdict(deque)
_MCP_WINDOW_S = 60.0
_MCP_LIMIT = int(os.environ.get("HEVI_MCP_RATE_LIMIT", "30"))
# 只读档（默认关闭）：只放行查询类工具，写/付费工具一律拒绝。
_MCP_READ_ONLY = os.environ.get("HEVI_MCP_READ_ONLY", "").lower() in {"1", "true", "yes"}
_READ_ONLY_ALLOWED = (".list", ".get", ".status", ".capabilities", "list_capabilities", "ops.list")


def _mcp_tool_names(body: bytes) -> list[str]:
    try:
        payload = json.loads(body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return []
    messages = payload if isinstance(payload, list) else [payload]
    names: list[str] = []
    for item in messages:
        if not isinstance(item, dict):
            continue
        params = item.get("params")
        if isinstance(params, dict) and isinstance(params.get("name"), str):
            names.append(params["name"])
    return names


def _rate_limited(user_id: str) -> bool:
    bucket = _MCP_HITS[user_id]
    now = time.monotonic()
    cutoff = now - _MCP_WINDOW_S
    while bucket and bucket[0] <= cutoff:
        bucket.popleft()
    if len(bucket) >= _MCP_LIMIT:
        return True
    bucket.append(now)
    return False


async def _json_error(send: Any, status: int, detail: str) -> None:
    body = json.dumps({"detail": detail}, ensure_ascii=False).encode("utf-8")
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json; charset=utf-8")]})
    await send({"type": "http.response.body", "body": body})


def authenticated_mcp_app(app: Any) -> Any:
    """Require a verified bearer token and expose its subject to MCP handlers.

    S25 加固：
    * 按用户限流（默认 30 次/60 秒，进程内，与现有单实例拓扑一致）；
    * ``HEVI_MCP_READ_ONLY=1`` 时只放行查询类工具，写/付费工具直接 403；
    * 仍不记录 token，只把 subject 放进 contextvar。
    """

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
        if _rate_limited(user_id):
            await _json_error(send, 429, "MCP rate limit exceeded, retry shortly")
            return

        buffered = b""
        use_replay = scope.get("method") not in ("GET", "HEAD")
        if use_replay:
            while True:
                message = await receive()
                if message["type"] != "http.request":
                    buffered = b""
                    break
                buffered += message.get("body", b"")
                if not message.get("more_body"):
                    break
            if _MCP_READ_ONLY:
                blocked = [n for n in _mcp_tool_names(buffered) if not any(
                    n.endswith(suffix) or suffix in n for suffix in _READ_ONLY_ALLOWED
                )]
                if blocked:
                    await _json_error(send, 403, f"MCP read-only mode blocks: {', '.join(blocked[:3])}")
                    return

        async def replay() -> dict[str, Any]:
            return {"type": "http.request", "body": buffered, "more_body": False}

        token = set_mcp_actor(user_id)
        try:
            await app(scope, replay if use_replay else receive, send)
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
