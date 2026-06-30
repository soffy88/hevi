"""Mount hevi MCP server onto the FastAPI application at /mcp."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from hevi.mcp.server import build_hevi_mcp_server


def mount_mcp(app: FastAPI) -> None:
    """Attach hevi MCP server to FastAPI at /mcp (Streamable HTTP transport)."""
    server = build_hevi_mcp_server()
    asgi_app: Any = server._fastmcp.streamable_http_app()
    app.mount("/mcp", asgi_app)
