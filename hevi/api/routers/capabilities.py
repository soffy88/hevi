"""Capabilities API router (FIX-15).
Exposes GET /api/capabilities per CAPABILITY_CONTRACT.md.
"""

from __future__ import annotations

from typing import Any
from fastapi import APIRouter

from hevi.capabilities import registry

router = APIRouter(tags=["capabilities"])


@router.get("/capabilities")
async def list_capabilities() -> dict[str, list[dict[str, Any]]]:
    """列出全部注册的能力清单。"""
    caps = registry.list_capabilities()
    items = []
    for c in caps:
        items.append({
            "name": c.name,
            "kind": c.kind,
            "aspects": c.aspects,
            "params_schema": c.params_schema,
            "description": c.description,
            "line": c.line,
            "cpu_cost_hint": c.cpu_cost_hint,
        })
    return {"capabilities": items}
