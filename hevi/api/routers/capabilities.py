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

The handdraw line additionally exposes a real 3-second MP4 preview via
:func:`render_capability_preview` (imported directly by the handdraw acceptance
tests); it reuses the same unified registry.
"""

from __future__ import annotations

import hashlib
import tempfile
import threading
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, Field

from hevi.capabilities import CapabilityError, get, list_capabilities
from hevi.huobao.capabilities import register_huobao_capabilities

router = APIRouter(prefix="/capabilities", tags=["capabilities"])

# Register the huobao (short-drama) capability family on import so
# GET /api/capabilities exposes them alongside every other line.
register_huobao_capabilities()


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
        "has_media_output": cap.has_media_output,
        "preview_restricted": cap.preview_restricted,
    }


@router.get("")
async def list_capabilities_endpoint() -> dict[str, list[dict[str, Any]]]:
    """List every registered capability (name, kind, aspects, line, cost hint).

    The payload is wrapped in a ``capabilities`` key so consumers can extend the
    envelope later without breaking the list itself.
    """
    return {
        "capabilities": [
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
    }


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
) -> Response:
    """Render a 3-second preview for ``name`` — or a report, by kind.

    A missing/unknown capability returns 404.  An unsupported aspect
    or an invalid param returns 422.  A genuine render failure
    returns 500 — never a fake success.

    Preview semantics by capability kind (M-15 / M-17 / S-03):

    * Media capabilities (``has_media_output``): the aspect check
      applies (unsupported aspect is 422) and the response is the
      produced media file.
    * Report/file capabilities (``has_media_output=False``): the
      render ignores aspect, so the aspect check is skipped, and
      the response is the report JSON (``qa`` payload + sha) — the
      endpoint never fabricates an MP4 for a capability that has no
      media, and never raises ``Path(None)`` on a missing artefact.
    * Restricted capabilities (``preview_restricted``, currently
      only ``video.blender_mcp``): always 422.  Arbitrary bpy code
      execution is not exposed to generic callers; trusted direct
      callers render in-process via ``render_safe`` instead.
    """
    try:
        cap = get(name)
    except CapabilityError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if cap.preview_restricted:
        raise HTTPException(
            status_code=422,
            detail=(
                f"capability {name} is restricted: it executes arbitrary "
                "code (bpy) in a live session and is not available through "
                "the generic preview endpoint; trusted direct callers only"
            ),
        )
    try:
        cap.validate_params(params or {})
    except CapabilityError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    # The capability declares the aspects it supports; an unsupported
    # one is a caller error (422), not a render failure (500).  This
    # check applies only to media capabilities: report/file renders
    # ignore aspect entirely (S-03), so it cannot gate them.
    if cap.has_media_output and not cap.supports_aspect(aspect):
        raise HTTPException(
            status_code=422,
            detail=f"capability {name} does not support aspect {aspect!r} "
            f"(supported: {cap.aspects})",
        )
    out = Path(tempfile.mkdtemp(prefix="scene3d_preview_"))
    try:
        res = cap.render_safe(params or {}, out, duration=3.0, aspect=aspect, seed=seed)
    except CapabilityError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    for media_path, media_type in (
        (res.mp4, "video/mp4"),
        (res.png, "image/png"),
        (res.wav, "audio/wav"),
    ):
        if media_path and Path(media_path).exists():
            video = Path(media_path)
            return FileResponse(str(video), media_type=media_type, filename=video.name)
    if not cap.has_media_output:
        return JSONResponse(
            {
                "name": name,
                "kind": "report",
                "sha256": res.sha256,
                "duration_s": res.duration_s,
                "qa": res.qa,
            }
        )
    raise HTTPException(status_code=500, detail="preview produced no artefact")


# ---------------------------------------------------------------------------
# Handdraw real-preview helpers (merged from feat/handdraw-line).  These are
# imported directly by the handdraw acceptance tests; they reuse the same
# unified registry so the capability contract stays single-source.
# ---------------------------------------------------------------------------

_PREVIEW_LOCK = threading.Lock()
REPO_ROOT = Path(__file__).resolve().parents[3]
TEMP_ROOT = REPO_ROOT / ".tmp" / "capability-previews"


class CapabilityPreviewRequest(BaseModel):
    topic: str = Field(default="小狐狸学会轮流", min_length=2, max_length=120)
    aspect: Literal["16:9", "9:16"] = "16:9"
    style_id: Literal["1", "8", "10", "17"] = "17"
    hand_preset: Literal["navy", "pen-only"] = "navy"
    seed: int = 0


def list_capability_contracts() -> dict:
    """Expose the same registered capability catalog used by product lines."""
    import hevi.capabilities.handdraw  # noqa: F401 - import registers the capabilities

    return {
        "items": [
            {
                "name": cap.name,
                "kind": cap.kind,
                "aspects": list(cap.aspects),
                "params_schema": cap.params_schema,
                "cpu_cost_hint": cap.cpu_cost_hint,
                "description": cap.description,
            }
            for cap in list_capabilities()
        ]
    }


def render_capability_preview(name: str, body: CapabilityPreviewRequest) -> FileResponse:
    """Render a real 3-second MP4 using the shared capability implementation."""
    if name != "handdraw.full":
        raise HTTPException(
            status_code=422,
            detail="Only video capability handdraw.full provides MP4 previews.",
        )
    try:
        import hevi.capabilities.handdraw  # noqa: F401 - ensure registration

        capability = get(name)
        TEMP_ROOT.mkdir(parents=True, exist_ok=True)
        key = hashlib.sha256(
            f"{body.topic}|{body.aspect}|{body.style_id}|{body.hand_preset}|{body.seed}".encode()
        ).hexdigest()[:16]
        # Per-request folder avoids stale manifests; all intermediates stay in .tmp.
        with _PREVIEW_LOCK:
            out_dir = Path(tempfile.mkdtemp(prefix=f"{key}-", dir=TEMP_ROOT))
            result = capability.render(
                {
                    "topic": body.topic,
                    "aspect": body.aspect,
                    "style_id": body.style_id,
                    "hand_preset": body.hand_preset,
                },
                out_dir,
                duration=3.0,
                aspect=body.aspect,
                seed=body.seed,
            )
        if result.mp4 is None or not result.mp4.is_file() or result.duration_s is None:
            raise CapabilityError("preview renderer returned no MP4")
        if abs(float(result.duration_s) - 3.0) > 0.1:
            raise CapabilityError(f"preview duration is {result.duration_s}, expected 3 seconds")
        return FileResponse(
            str(result.mp4),
            media_type="video/mp4",
            filename="handdraw-preview.mp4",
            headers={
                "X-Capability-Duration": f"{float(result.duration_s):.3f}",
                "X-Capability-SHA256": str(result.sha256 or ""),
                "X-Capability-Name": name,
            },
        )
    except HTTPException:
        raise
    except CapabilityError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Capability preview failed: {type(exc).__name__}: {exc}",
        ) from exc


__all__ = ["router", "CapabilityPreviewRequest", "list_capability_contracts", "render_capability_preview"]
