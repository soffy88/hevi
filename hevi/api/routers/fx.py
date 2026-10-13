"""FX template API router.

Endpoints (all mounted under ``/api/fx``):

- ``GET /templates`` — list with optional ``category`` / ``source`` / ``q`` filters
- ``GET /templates/{id}`` — single template detail
- ``GET /templates/{id}/preview`` — preview MP4 (404 when not rendered)
- ``GET /templates/{id}/thumbnail`` — preview thumbnail JPG (404 when not rendered)

The catalog is read-only: it is loaded from ``hevi.fx.sources`` and never
mutated by this router. Preview files are produced by ``scripts/fx_preview.py``.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse

from hevi.fx.loader import get_registry
from hevi.fx.registry import Category, Source, preview_mp4_path, preview_thumbnail_path

router = APIRouter(prefix="/fx", tags=["fx"])


def _invalid_detail(kind: str, value: str, allowed: list[str]) -> HTTPException:
    return HTTPException(
        status_code=400,
        detail=f"Invalid {kind}: {value}. Must be one of: {allowed}",
    )


@router.get("/templates")
def list_templates(
    category: str | None = Query(None, description="Filter by category"),
    source: str | None = Query(None, description="Filter by source"),
    q: str | None = Query(None, description="Case-insensitive search on id, name_zh, tags"),
) -> JSONResponse:
    """List FX templates with optional filtering.

    Returns:
        JSON with ``total``, per-category / per-source breakdowns, and the
        filtered ``templates`` list.
    """
    registry = get_registry()

    if category is not None:
        try:
            Category(category)
        except ValueError:
            raise _invalid_detail("category", category, [c.value for c in Category]) from None

    if source is not None:
        try:
            Source(source)
        except ValueError:
            raise _invalid_detail("source", source, [s.value for s in Source]) from None

    templates = registry.filter(category=category, source=source, q=q)

    return JSONResponse(
        {
            "total": len(templates),
            "categories": registry.categories(),
            "sources": registry.sources(),
            "templates": [t.to_dict() for t in templates],
        }
    )


@router.get("/templates/{template_id}")
def get_template(template_id: str) -> JSONResponse:
    """Get a single FX template by id (e.g. ``tc:focus-dim-spotlight``)."""
    registry = get_registry()
    template = registry.get(template_id)

    if template is None:
        raise HTTPException(status_code=404, detail=f"Template not found: {template_id}")

    return JSONResponse(template.to_dict())


def _serve_asset(template_id: str, path, description: str, media_type: str) -> FileResponse:
    """Serve a preview asset, raising a precise 404 when it is absent."""
    registry = get_registry()
    template = registry.get(template_id)
    if template is None:
        raise HTTPException(status_code=404, detail=f"Template not found: {template_id}")

    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"No {description} available for template: {template_id}",
        )

    return FileResponse(path=str(path), media_type=media_type, filename=path.name)


@router.get("/templates/{template_id}/preview", response_model=None)
def get_template_preview(template_id: str):
    """Return the template's preview MP4, or 404 if it has not been rendered.

    Previews are 2s / 540x960 / 30fps files written by ``scripts/fx_preview.py``
    into ``output/fx_previews/``. A 404 here is honest — no placeholder is served.
    """
    return _serve_asset(
        template_id,
        preview_mp4_path(template_id),
        "preview",
        "video/mp4",
    )


@router.get("/templates/{template_id}/thumbnail", response_model=None)
def get_template_thumbnail(template_id: str):
    """Return the template's thumbnail JPG, or 404 if it has not been rendered."""
    return _serve_asset(
        template_id,
        preview_thumbnail_path(template_id),
        "thumbnail",
        "image/jpeg",
    )
