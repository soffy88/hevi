"""Hevi unified capability API.

Exposes the capability registry (``hevi.capabilities``) over HTTP so any
front-end AI can pre-fill from a single source of truth, and any product line
can trigger a short preview by name.  See ``CAPABILITY_CONTRACT.md``.

Endpoints (mounted under ``/api`` by ``hevi/api/main.py``):

* ``GET  /api/capabilities``                     — list all capabilities.
* ``GET  /api/capabilities/{name}``              — describe one capability.
* ``POST /api/capabilities/{name}/preview``      — render a 3-second preview.

The preview runs the CPU-only SCENE3D renderer.  The renderer uses the
*Synchronous* Playwright API, which raises ``It looks like you are using
Playwright Sync API inside the asyncio loop`` if called from a coroutine on the
event loop.  The endpoint is therefore declared as a plain ``def``: FastAPI runs
synchronous endpoints in a worker thread, so the sync Playwright call is safe.
In a production deployment it would be dispatched to a dedicated worker; here it
is kept inline so the offline tool stays self-contained.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from hevi.capabilities import CapabilityError, get, list_capabilities

router = APIRouter(prefix="/capabilities", tags=["capabilities"])


def _summary(name: str) -> dict[str, Any]:
    cap = get(name)
    return {
        "name": cap.name,
        "kind": cap.kind,
        "aspects": cap.aspects,
        "line": cap.line,
        "cpu_cost_hint": cap.cpu_cost_hint,
        "description": cap.description,
        "params_schema": cap.params_schema,
    }


@router.get("")
async def list_capabilities_endpoint() -> list[dict[str, Any]]:
    """List every registered capability (name, kind, aspects, line, cost hint)."""
    return [
        {
            "name": c.name,
            "kind": c.kind,
            "aspects": c.aspects,
            "line": c.line,
            "cpu_cost_hint": c.cpu_cost_hint,
            "description": c.description,
        }
        for c in list_capabilities()
    ]


@router.get("/{name}")
async def get_capability_endpoint(name: str) -> dict[str, Any]:
    """Describe a single capability by name (422-equivalent via 404 on miss)."""
    try:
        return _summary(name)
    except CapabilityError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# NOTE: deliberately a *sync* ``def`` (not ``async def``).  FastAPI runs sync
# endpoints in a threadpool; the scene3d renderer uses the synchronous Playwright
# API and would otherwise raise "Playwright Sync API inside the asyncio loop".
@router.post("/{name}/preview")
def preview_capability_endpoint(
    name: str,
    params: dict[str, Any] | None = None,
    aspect: str = "16:9",
    seed: int = 1234,
) -> FileResponse:
    """Render a 3-second preview clip for ``name`` and return it as an MP4.

    A missing/unknown capability returns 404.  An unsupported aspect or an
    invalid param returns 422.  A genuine render failure (or a missing
    artefact) returns 500 — never a fake success.
    """
    try:
        cap = get(name)
    except CapabilityError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    try:
        cap.validate_params(params or {})
    except CapabilityError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    # The capability declares the aspects it supports; an unsupported one is a
    # caller error (422), not a render failure (500).
    if not cap.supports_aspect(aspect):
        raise HTTPException(
            status_code=422,
            detail=f"capability {name} does not support aspect {aspect!r} "
            f"(supported: {cap.aspects})",
        )
    out = Path(tempfile.mkdtemp(prefix="scene3d_preview_"))
    try:
        res = cap.render(params or {}, out, duration=3.0, aspect=aspect, seed=seed)
    except CapabilityError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    video = Path(res.mp4)
    if not video.exists():
        raise HTTPException(status_code=500, detail="preview produced no artefact")
    return FileResponse(str(video), media_type="video/mp4", filename=video.name)


__all__ = ["router"]
