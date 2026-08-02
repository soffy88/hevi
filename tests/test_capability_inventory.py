"""CI guard: every registered HTTP and MCP entry point must be inventoried."""

from pathlib import Path

from scripts.export_api_inventory import render, render_mcp


def test_http_capability_inventory_is_current() -> None:
    from hevi.api.main import app

    assert render(app.openapi()) == Path("docs/API-CAPABILITIES.md").read_text(encoding="utf-8")


def test_mcp_capability_inventory_is_current() -> None:
    assert render_mcp() == Path("docs/MCP-CAPABILITIES.md").read_text(encoding="utf-8")
