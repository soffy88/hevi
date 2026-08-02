"""Export the live FastAPI contract as the API capability inventory.

Usage: ``uv run python scripts/export_api_inventory.py``.
The script never starts the app lifespan, so it does not connect to the
database or start workers.  Deprecated compatibility routes are marked in the
generated Markdown instead of being mistaken for canonical product features.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
METHOD_ORDER = ("get", "post", "put", "patch", "delete", "options", "head")


def _summary(operation: dict[str, Any]) -> str:
    return " ".join(str(operation.get("summary") or operation["operationId"]).split())


def render(schema: dict[str, Any]) -> str:
    grouped: dict[str, list[tuple[str, str, dict[str, Any]]]] = defaultdict(list)
    for path, methods in schema["paths"].items():
        for method in METHOD_ORDER:
            operation = methods.get(method)
            if operation is not None:
                for tag in operation.get("tags", ["untagged"]):
                    grouped[tag].append((path, method.upper(), operation))

    lines = [
        "# Hevi 后端 API 能力清单",
        "",
        "> 由 `scripts/export_api_inventory.py` 从 FastAPI OpenAPI 自动生成；不要手工编辑。",
        "> `⚠️ 兼容` 表示仍可调用但新客户端不应使用的弃用入口。",
        "",
    ]
    for tag in sorted(grouped):
        lines.extend([f"## {tag}", "", "| 方法 | 路径 | 说明 |", "|---|---|---|"])
        for path, method, operation in sorted(grouped[tag], key=lambda item: (item[0], item[1])):
            prefix = "⚠️ 兼容 · " if operation.get("deprecated") else ""
            lines.append(f"| {method} | `{path}` | {prefix}{_summary(operation)} |")
        lines.append("")
    return "\n".join(lines)


def render_mcp() -> str:
    """Generate an auditable inventory from the registered MCP surface."""
    from hevi.mcp.server import build_hevi_mcp_server

    server = build_hevi_mcp_server()
    tools = server._fastmcp._tool_manager._tools  # type: ignore[attr-defined]
    lines = [
        "# HEVI MCP 能力清单",
        "",
        "> 由 `scripts/export_api_inventory.py` 从 MCP 注册表自动生成；不要手工编辑。",
        "",
        "| 工具 | 说明 |",
        "|---|---|",
    ]
    for name, tool in sorted(tools.items()):
        lines.append(f"| `{name}` | {' '.join(str(tool.description).split())} |")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    from hevi.api.main import app

    schema = app.openapi()
    (ROOT / "docs" / "openapi.json").write_text(
        json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (ROOT / "docs" / "API-CAPABILITIES.md").write_text(render(schema), encoding="utf-8")
    (ROOT / "docs" / "MCP-CAPABILITIES.md").write_text(render_mcp(), encoding="utf-8")


if __name__ == "__main__":
    main()
