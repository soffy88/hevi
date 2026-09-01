"""hevi/api/routers/material_corpus.py - 修复 Any 导入"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from hevi.core.config import settings
from hevi.video.material_corpus import (
    search_archive_videos,
    search_coverr_videos,
    search_pixabay_videos,
)

router = APIRouter(prefix="/material", tags=["material"])

@router.get("/pixabay", response_model=list[dict[str, Any]])
async def get_pixabay_videos(
    query: str = Query(default="")
) -> list[dict[str, Any]]: # 修复类型别名 Any
    """Pixabay 视频搜索 API - 直接复用 material_corpus.search_pixabay_videos 逻辑"""
    try:
        return [item.to_dict() for item in search_pixabay_videos(query, settings.pixabay_api_key)]
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Pixabay search failed: {exc}") from exc

@router.get("/coverr", response_model=list[dict[str, Any]])
async def get_coverr_videos(
    query: str = Query(default="")
) -> list[dict[str, Any]]: # 修复类型别名 Any
    """Coverr 视频搜索 API - 直接复用 material_corpus.search_coverr_videos 逻辑"""
    try:
        return [item.to_dict() for item in search_coverr_videos(query, settings.coverr_api_key)]
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Coverr search failed: {exc}") from exc

@router.get("/archive", response_model=list[dict[str, Any]])
async def get_archive_videos(
    query: str = Query(default="")
) -> list[dict[str, Any]]: # 修复类型别名 Any
    """Archive.org 搜索 API - 直接复用 material_corpus.search_archive_videos 逻辑"""
    try:
        return [item.to_dict() for item in search_archive_videos(query)]
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Archive.org search failed: {exc}") from exc

__all__ = [
    "get_archive_videos",
    "get_coverr_videos",
    "get_pixabay_videos",
    "router",
]
