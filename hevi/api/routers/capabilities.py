"""Unified capability registry API router (CAPABILITY_CONTRACT v1).

Exposes:
- GET  /capabilities: List all registered capabilities (front-end AI one-click prefill).
- POST /capabilities/{name}/preview: Generate a 3-second preview video/artifact.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from hevi.capabilities.registry import CapabilityError, describe, get
from hevi.huobao.capabilities import register_huobao_capabilities

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/capabilities", tags=["capabilities"])

# Ensure registered capabilities are loaded on router initialization
register_huobao_capabilities()


class CapabilityPreviewRequest(BaseModel):
    params: dict[str, Any] = Field(default_factory=dict)
    aspect: str = "9:16"
    seed: int = 42
    preview_seconds: float = 3.0


@router.get("")
@router.get("/")
async def list_capabilities_endpoint() -> dict[str, Any]:
    """List all registered capabilities with kind, aspects, schema, and cost hint."""
    return {"capabilities": describe()}


@router.post("/{name}/preview")
async def preview_capability_endpoint(name: str, req: CapabilityPreviewRequest) -> dict[str, Any]:
    """Generate a short preview (default 3s) for a registered capability."""
    try:
        cap = get(name)
    except CapabilityError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    with tempfile.TemporaryDirectory(prefix=f"cap_preview_{name.replace('.', '_')}_") as td:
        out = Path(td)
        try:
            result = cap.render(
                req.params,
                out,
                duration=req.preview_seconds,
                aspect=req.aspect,
                seed=req.seed,
            )
        except CapabilityError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e
        return {
            "name": name,
            "preview_seconds": req.preview_seconds,
            "result": result.to_dict(),
        }
