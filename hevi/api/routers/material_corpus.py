"""hevi/api/routers/material_corpus.py - 修复 Any 导入"""

from __future__ import annotations

from typing import Any
from fastapi import APIRouter, Depends, HTTPException

router = APIRouter(prefix="/material", tags=["material"])

@router.get("/pixabay", response_model=list[dict[str, Any]])
async def get_pixabay_videos(
    query: str = Depends(lambda: settings.material_query_default or "")
) -> list[dict[str, Any]]: # 修复类型别名 Any
    """Pixabay 视频搜索 API - 直接复用 material_corpus.search_pixabay_videos 逻辑"""
    try:
        return await search_pixabay_videos(query)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Pixabay search failed: {exc}")

@router.get("/coverr", response_model=list[dict[str, Any]])
async def get_coverr_videos(
    query: str = Depends(lambda: settings.material_query_default or "")
) -> list[dict[str, Any]]: # 修复类型别名 Any
    """Coverr 视频搜索 API - 直接复用 material_corpus.search_coverr_videos 逻辑"""
    try:
        return await search_coverr_videos(query)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Coverr search failed: {exc}")

@router.get("/archive", response_model=list[dict[str, Any]])
async def get_archive_videos(
    query: str = Depends(lambda: settings.material_query_default or "")
) -> list[dict[str, Any]]: # 修复类型别名 Any
    """Archive.org 搜索 API - 直接复用 material_corpus.search_archive_videos 逻辑"""
    try:
        return await search_archive_videos(query)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Archive.org search failed: {exc}")

__all__ = [
    "router",
    "get_pixabay_videos",
    "get_coverr_videos",
    "get_archive_videos",
]