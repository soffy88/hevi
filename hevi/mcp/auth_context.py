"""Request-scoped identity for authenticated MCP tool execution."""

from __future__ import annotations

from contextvars import ContextVar, Token

_mcp_actor_id: ContextVar[str | None] = ContextVar("mcp_actor_id", default=None)


class MCPAuthenticationError(PermissionError):
    """Raised when a state-changing MCP tool has no authenticated actor."""


def set_mcp_actor(user_id: str) -> Token[str | None]:
    """Bind the verified HTTP token subject for the lifetime of one MCP request."""

    return _mcp_actor_id.set(user_id)


def reset_mcp_actor(token: Token[str | None]) -> None:
    _mcp_actor_id.reset(token)


def require_mcp_actor() -> str:
    user_id = _mcp_actor_id.get()
    if not user_id:
        raise MCPAuthenticationError("MCP authentication is required for production tasks")
    return user_id
