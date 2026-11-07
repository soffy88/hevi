"""K-18 mcp_tool_invoke — invoke an MCP tool and normalise the result.

Composes oprim:
    - mcp_call_tool
    - mcp_tool_to_schema  (for arg validation)
    - summarize_subagent_result  (result normalisation)

IO-orchestration (MCP network call). Stateless.
"""

from __future__ import annotations

import json
from typing import Any, Protocol

from oprim import mcp_call_tool, mcp_tool_to_schema, summarize_subagent_result  # noqa: F401
from oprim._hicode_types import McpToolSpec, ToolResult


class McpSession(Protocol):
    async def call_tool(self, name: str, args: dict[str, Any]) -> Any: ...
    async def list_tools(self) -> list[dict[str, Any]]: ...


async def mcp_tool_invoke(
    session: McpSession,
    *,
    name: str,
    args: dict[str, Any],
) -> ToolResult:
    """Invoke an MCP tool via *session* and return a normalised ToolResult.

    Composes: mcp_call_tool, mcp_tool_to_schema, summarize_subagent_result.

    Args:
        session: Injected MCP session Protocol.
        name: Tool name (without mcp_ prefix).
        args: Tool arguments dict.

    Returns:
        ToolResult with call_id, content (possibly truncated), is_error flag.

    Raises:
        ValueError: If args fail schema validation.
    """
    import uuid

    call_id = str(uuid.uuid4())[:8]

    # Validate args against schema (if we can get the spec)
    try:
        tool_list = await session.list_tools()
        tool_spec_dict = next((t for t in tool_list if t.get("name") == name), None)
        if tool_spec_dict is not None:
            spec = McpToolSpec(
                name=tool_spec_dict.get("name", name),
                description=tool_spec_dict.get("description", ""),
                input_schema=tool_spec_dict.get("inputSchema", {}),
            )
            schema = mcp_tool_to_schema(spec)
            required = schema.get("parameters", {}).get("required", [])
            for req_field in required:
                if req_field not in args:
                    raise ValueError(f"Missing required arg: {req_field!r}")
    except ValueError:
        raise
    except Exception:
        pass  # can't validate, proceed

    # Invoke the tool
    try:
        result = await mcp_call_tool(session, name=name, args=args)
    except Exception as exc:
        return ToolResult(call_id=call_id, content=f"Error: {exc}", is_error=True)

    # Normalise result
    if isinstance(result, str):
        content = result
    elif isinstance(result, dict):
        content = json.dumps(result)
    elif isinstance(result, list):
        content = "\n".join(str(item) for item in result)
    else:
        content = str(result)

    # Truncate large results
    if len(content) > 10_000:
        content = content[:10_000] + "\n... [truncated]"

    return ToolResult(call_id=call_id, content=content, is_error=False)
