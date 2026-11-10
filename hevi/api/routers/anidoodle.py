"""Anidoodle style library API (S29).

Endpoints are authenticated like the rest of Studio.  Rendering is CPU-local
and can take seconds to a minute, so the blocking render runs in a worker
thread and the response carries the measured time, the hash and the gate
verdict.  Files are served only from the anidoodle output root.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from hevi.auth.dependencies import get_current_user

router = APIRouter(prefix="/anidoodle", tags=["anidoodle"])


class RecommendRequest(BaseModel):
    topic: str = ""
    intent: str = ""
    avoid: list[str] = Field(default_factory=list)


class StillRequest(BaseModel):
    style_id: str = Field(min_length=1)
    frame: int | None = Field(default=None, ge=0)
    scale: float = Field(default=1.0, gt=0, le=2)


class DrawRequest(BaseModel):
    style_id: str = Field(min_length=1)
    poster_frame: int | None = Field(default=None, ge=0)
    scale: float = Field(default=1.0, gt=0, le=2)
    gates: bool = True


class MusicRequest(BaseModel):
    style: str = "lofiElectronic"
    mood: str = ""
    key: str = ""
    bpm: int = Field(default=0, ge=0, le=200)
    bars: int = Field(default=12, ge=6, le=96)
    seed: int = Field(default=29, ge=0)
    format: str = "mp3"


class BgmRequest(BaseModel):
    duration_s: float = Field(gt=0, le=900)
    style: str = "lofiElectronic"
    mood: str = ""
    key: str = ""
    seed: int = Field(default=29, ge=0)
    target_lufs: float = Field(default=-14.0, ge=-30, le=-8)


class PartialRequest(BaseModel):
    style_id: str = Field(min_length=1)
    base_mp4: str = Field(min_length=1)
    start_s: float = Field(ge=0)
    end_s: float = Field(gt=0)


class GateRequest(BaseModel):
    film: str = Field(min_length=1)
    mp4: str = Field(min_length=1)
    drawing: bool = True


def _root() -> Path:
    from hevi.anidoodle.engine import output_root

    return output_root().resolve()


def _public(path: str | Path) -> dict[str, str]:
    file = Path(path).expanduser().resolve()
    try:
        file.relative_to(_root())
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail="file outside the anidoodle output root"
        ) from exc
    return {"path": str(file), "url": f"/api/anidoodle/file?path={file}"}


def _require_public(style_id: str, user: dict[str, Any] | None) -> None:
    from hevi.anidoodle import validation_for
    from hevi.auth.dependencies import can_view_internal_lines

    status = validation_for(style_id)
    if status.get("status") != "public" and not can_view_internal_lines(user):
        raise HTTPException(
            status_code=403,
            detail=f"style {style_id} is admin-only: {status.get('reason')}",
        )


def _error(exc: Exception) -> HTTPException:
    from hevi.anidoodle import AnidoodleError

    if isinstance(exc, AnidoodleError):
        return HTTPException(status_code=503, detail=str(exc))
    return HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}")


@router.get("/styles")
async def styles(
    topic: str = "",
    intent: str = "",
    _user: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    from hevi.anidoodle import families, list_styles, recommend_style, validation_for

    rows = [{**style.to_dict(), **validation_for(style.id)} for style in list_styles()]
    payload: dict[str, Any] = {
        "styles": rows,
        "families": families(),
        "total": len(rows),
        "attribution": {
            "name": "anidoodle",
            "author": "Alex Greenshpun",
            "license": "Apache-2.0",
            "url": "https://github.com/alexgreensh/anidoodle",
            "note": "HEVI vendors the engine; modified files are noted in THIRD_PARTY_NOTICES.md.",
        },
        "rights_notice": "匹配参考图只接受用户自己拥有权利的图片；本功能不做照片转真人写真。",
    }
    if topic or intent:
        payload["recommendation"] = recommend_style(topic, intent=intent)
    return payload


@router.post("/recommend")
async def recommend(
    req: RecommendRequest,
    _user: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    from hevi.anidoodle import recommend_style

    return recommend_style(req.topic, intent=req.intent, avoid=req.avoid)


@router.get("/engine")
async def engine(
    _user: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    from hevi.anidoodle import engine_info, families, list_styles

    try:
        info = await asyncio.to_thread(engine_info)
    except Exception as exc:
        raise _error(exc) from exc
    return {
        "engine": info.to_dict(),
        "styles": len(list_styles()),
        "families": len(families()),
        "backend": "playwright (Chromium); remotion adapter not installed by decision",
    }


@router.post("/still")
async def still(
    req: StillRequest,
    _user: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    from hevi.anidoodle import render_still

    _require_public(req.style_id, _user)
    try:
        result = await asyncio.to_thread(
            render_still, req.style_id, frame=req.frame, scale=req.scale
        )
    except Exception as exc:
        raise _error(exc) from exc
    return {**result, "file": _public(result["path"])}


@router.post("/gallery")
async def gallery(
    scale: float = Query(default=0.5, gt=0, le=1),
    _user: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    from hevi.anidoodle import render_gallery

    try:
        result = await asyncio.to_thread(render_gallery, scale=scale)
    except Exception as exc:
        raise _error(exc) from exc
    return {**result, "file": _public(result["path"])}


@router.post("/draw-clip")
async def draw_clip(
    req: DrawRequest,
    _user: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    from hevi.anidoodle import render_draw_clip, run_gate, run_verify_export

    _require_public(req.style_id, _user)
    try:
        result = await asyncio.to_thread(
            render_draw_clip,
            req.style_id,
            poster_frame=req.poster_frame,
            scale=req.scale,
        )
        payload: dict[str, Any] = {**result, "file": _public(result["path"])}
        if req.gates and req.scale == 1.0:
            gate = await asyncio.to_thread(run_gate, result["film"], result["path"], drawing=True)
            verify = await asyncio.to_thread(run_verify_export, result["path"])
            payload["gate"] = {
                key: gate[key]
                for key in ("ok", "verdict", "passed_count", "failures", "dead_air_profile")
            }
            payload["verify_export"] = {
                key: verify[key] for key in ("ok", "verdict", "passed_count", "failures")
            }
    except Exception as exc:
        raise _error(exc) from exc
    return payload


@router.post("/music")
async def music(
    req: MusicRequest,
    _user: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    from hevi.anidoodle import compose_bgm

    try:
        result = await asyncio.to_thread(
            compose_bgm,
            style=req.style,
            mood=req.mood,
            key=req.key,
            bpm=req.bpm,
            bars=req.bars,
            seed=req.seed,
            fmt=req.format,
        )
    except Exception as exc:
        raise _error(exc) from exc
    return {**result, "file": _public(result["path"])}


@router.post("/bgm")
async def bgm(
    req: BgmRequest,
    _user: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    from hevi.anidoodle import compose_for_duration

    try:
        result = await asyncio.to_thread(
            compose_for_duration,
            req.duration_s,
            style=req.style,
            mood=req.mood,
            key=req.key,
            seed=req.seed,
            target_lufs=req.target_lufs,
        )
    except Exception as exc:
        raise _error(exc) from exc
    return {**result, "file": _public(result["path"])}


@router.post("/partial")
async def partial(
    req: PartialRequest,
    _user: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    from hevi.anidoodle import render_partial

    base = Path(req.base_mp4).expanduser().resolve()
    try:
        base.relative_to(_root())
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail="base_mp4 outside the anidoodle output root"
        ) from exc
    try:
        result = await asyncio.to_thread(
            render_partial,
            req.style_id,
            start_s=req.start_s,
            end_s=req.end_s,
            base_mp4=base,
        )
    except Exception as exc:
        raise _error(exc) from exc
    return {**result, "file": _public(result["path"])}


@router.post("/gate")
async def gate(
    req: GateRequest,
    _user: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    from hevi.anidoodle import run_gate, run_verify_export

    path = Path(req.mp4).expanduser().resolve()
    try:
        path.relative_to(_root())
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail="mp4 outside the anidoodle output root"
        ) from exc
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"no such file: {path}")
    try:
        gate_report = await asyncio.to_thread(run_gate, req.film, path, drawing=req.drawing)
        verify = await asyncio.to_thread(run_verify_export, path)
    except Exception as exc:
        raise _error(exc) from exc
    return {"gate": gate_report, "verify_export": verify}


@router.get("/file")
async def file(
    path: str = Query(min_length=1),
    _user: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None,
) -> FileResponse:
    target = Path(path).expanduser().resolve()
    try:
        target.relative_to(_root())
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail="file outside the anidoodle output root"
        ) from exc
    if not target.is_file():
        raise HTTPException(status_code=404, detail="file not found")
    return FileResponse(target)
