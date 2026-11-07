"""K-15 tool_schema_assemble — build complete tool schema list for LLM.

Composes oprim:
    - build_tool_schema
    - normalize_tool_schema
    - mcp_tool_to_schema

Sync (pure algorithm). Stateless.
"""

from __future__ import annotations

from typing import Any, cast

from oprim import build_tool_schema, mcp_tool_to_schema, normalize_tool_schema
from oprim._hicode_types import McpToolSpec, Tool


def tool_schema_assemble(
    tools: list[Tool],
    *,
    provider: str,
    mcp_specs: list[McpToolSpec] | None = None,
) -> list[dict[str, Any]]:
    """Build the complete tool schema list (built-in + MCP) for a provider.

    Composes: build_tool_schema (×n), mcp_tool_to_schema (MCP tools),
              normalize_tool_schema.

    Args:
        tools: Built-in Tool definitions.
        provider: Target provider for schema format.
        mcp_specs: Optional MCP tool specifications.

    Returns:
        Provider-formatted list of tool schema dicts.
    """
    raw_schemas: list[dict[str, Any]] = []

    # Built-in tools
    for tool in tools:
        try:
            schema = build_tool_schema(tool)
            raw_schemas.append(schema)
        except ValueError:
            continue  # skip tools with no description

    # MCP tools (with mcp_ prefix for namespace isolation)
    if mcp_specs:
        for spec in mcp_specs:
            schema = mcp_tool_to_schema(spec)
            raw_schemas.append(schema)

    if not raw_schemas:
        return []

    # Normalize to provider format
    return cast(list[dict[str, Any]], normalize_tool_schema(raw_schemas, provider=provider))
