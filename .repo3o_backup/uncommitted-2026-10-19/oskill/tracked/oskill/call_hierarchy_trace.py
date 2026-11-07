"""K-11 call_hierarchy_trace — recursive LSP call hierarchy traversal.

Composes oprim:
    - lsp_prepare_call_hierarchy
    - lsp_incoming_calls
    - lsp_outgoing_calls
    - location_to_snippet

IO-orchestration (LSP). Recursive depth-limited.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Protocol

from oprim import (
    location_to_snippet,  # noqa: F401
    lsp_incoming_calls,
    lsp_outgoing_calls,
    lsp_prepare_call_hierarchy,
)

from ._hc_types import CallNode, CallTree, Pos


class LspConnection(Protocol):
    async def request(self, method: str, params: dict[str, Any]) -> Any: ...


async def call_hierarchy_trace(
    path: Path,
    *,
    pos: Pos,
    lsp: LspConnection,
    depth: int = 2,
) -> CallTree:
    """Trace call hierarchy (callers and callees) up to *depth* levels.

    Composes: lsp_prepare_call_hierarchy, lsp_incoming_calls,
              lsp_outgoing_calls, location_to_snippet.

    Args:
        path: Source file.
        pos: Symbol position.
        lsp: Injected LSP connection.
        depth: Maximum recursion depth.

    Returns:
        CallTree with root node and nested incoming/outgoing callers.
    """
    lsp_pos = {"line": pos.line, "character": pos.character}
    items = await lsp_prepare_call_hierarchy(path, pos=lsp_pos, lsp=lsp)

    if not items:
        return CallTree()

    root_item = items[0] if isinstance(items, list) else items
    root_name = (
        root_item.get("name", str(path.name)) if isinstance(root_item, dict) else str(path.name)
    )
    root_uri = root_item.get("uri", str(path)) if isinstance(root_item, dict) else str(path)
    root_line = (
        root_item.get("range", {}).get("start", {}).get("line", pos.line)
        if isinstance(root_item, dict)
        else pos.line
    )

    root_node = CallNode(name=root_name, path=root_uri, line=root_line)
    visited: set[str] = {f"{root_uri}:{root_line}"}

    async def _fill(node: CallNode, item: Any, current_depth: int) -> None:
        if current_depth <= 0:
            return

        gathered: list[Any] = list(
            await asyncio.gather(
                lsp_incoming_calls(item, lsp=lsp),
                lsp_outgoing_calls(item, lsp=lsp),
                return_exceptions=True,
            )
        )
        incoming_raw: Any = gathered[0]
        outgoing_raw: Any = gathered[1]

        if isinstance(incoming_raw, list):
            for call in incoming_raw:
                from_item = call.get("from", call) if isinstance(call, dict) else call
                name = from_item.get("name", "?") if isinstance(from_item, dict) else "?"
                uri = from_item.get("uri", "") if isinstance(from_item, dict) else ""
                line = (
                    from_item.get("range", {}).get("start", {}).get("line", 0)
                    if isinstance(from_item, dict)
                    else 0
                )
                key = f"{uri}:{line}"
                if key not in visited:
                    visited.add(key)
                    child = CallNode(name=name, path=uri, line=line)
                    node.incoming.append(child)
                    await _fill(child, from_item, current_depth - 1)

        if isinstance(outgoing_raw, list):
            for call in outgoing_raw:
                to_item = call.get("to", call) if isinstance(call, dict) else call
                name = to_item.get("name", "?") if isinstance(to_item, dict) else "?"
                uri = to_item.get("uri", "") if isinstance(to_item, dict) else ""
                line = (
                    to_item.get("range", {}).get("start", {}).get("line", 0)
                    if isinstance(to_item, dict)
                    else 0
                )
                key = f"{uri}:{line}"
                if key not in visited:
                    visited.add(key)
                    child = CallNode(name=name, path=uri, line=line)
                    node.outgoing.append(child)
                    await _fill(child, to_item, current_depth - 1)

    await _fill(root_node, root_item, depth)
    return CallTree(root=root_node, depth_reached=depth)
