"""hevi 素材搜索服务 - 对接 Pexels/Pixabay/Archive.org + CLIP 语义检索

P0: 解决 hevi 缺失的免费素材路径能力
整合来自 MPT 的素材搜索逻辑，提供 hevi-native 的素材搜索 API
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx
from loguru import logger
from pydantic import BaseModel


@dataclass
class MaterialSearchConfig:
    """素材搜索配置"""
    pexels_api_key: str = ""
    pixabay_api_key: str = ""
    coverr_api_key: str = ""
    archive_org_enabled: bool = True
    min_duration: int = 5
    min_dimension: int = 480
    per_page: int = 10


class MaterialItem(BaseModel):
    """统一素材项"""
    url: str
    thumbnail: str | None = None
    duration: float = 0.0
    width: int = 0
    height: int = 0
    source: str  # pexels/pixabay/coverr/archive_org
    search_term: str | None = None
    asset_id: str | None = None
    source_page: str | None = None
    creator: dict[str, str] | None = None
    rendition: dict[str, Any] | None = None
    score: float | None = None  # relevant score for ranking


class MaterialSearchResult(BaseModel):
    """素材搜索结果"""
    query: str
    source: str
    total: int
    items: list[MaterialItem]
    error: str | None = None


def _get_config() -> MaterialSearchConfig:
    return MaterialSearchConfig(
        pexels_api_key=os.getenv("PEXELS_API_KEY", ""),
        pixabay_api_key=os.getenv("PIXABAY_API_KEY", ""),
        coverr_api_key=os.getenv("COVERR_API_KEY", ""),
        archive_org_enabled=os.getenv("ARCHIVE_ORG_ENABLED", "true").lower() == "true",
    )


async def search_pexels(query: str, count: int = 10, min_duration: int = 5) -> MaterialSearchResult:
    """从 Pexels 搜索视频素材"""
    config = _get_config()
    if not config.pexels_api_key:
        return MaterialSearchResult(query=query, source="pexels", total=0, items=[], error="PEXELS_API_KEY not set")

    headers = {"Authorization": config.pexels_api_key}
    params: dict[str, str | int] = {"query": query, "per_page": count, "orientation": "portrait"}

    async with httpx.AsyncClient(timeout=30) as client:
        try:
            resp = await client.get("https://api.pexels.com/videos/search", headers=headers, params=params)
            resp.raise_for_status()
            data = resp.json()

            items: list[MaterialItem] = []
            for v in data.get("videos", []):
                duration = float(v.get("duration", 0))
                if duration < min_duration:
                    continue

                for rend in v.get("video_files", []):
                    w = rend.get("width", 0)
                    h = rend.get("height", 0)
                    if w >= 480 and h >= 480:
                        items.append(MaterialItem(
                            url=rend["link"],
                            thumbnail=v.get("picture"),
                            duration=duration,
                            width=w,
                            height=h,
                            source="pexels",
                            search_term=query,
                            asset_id=str(v.get("id")),
                            source_page=v.get("url"),
                            creator={"name": v.get("user", {}).get("name", "")} if v.get("user") else None,
                            rendition={"width": w, "height": h},
                            score=(v.get("promoted", False) and 1.0) or 0.5,
                        ))

            return MaterialSearchResult(query=query, source="pexels", total=data.get("total", len(items)), items=items[:count])
        except Exception as e:
            logger.error(f"Pexels search failed: {e}")
            return MaterialSearchResult(query=query, source="pexels", total=0, items=[], error=str(e))


async def search_pixabay(query: str, count: int = 10, min_duration: int = 5) -> MaterialSearchResult:
    """从 Pixabay 搜索视频素材"""
    config = _get_config()
    if not config.pixabay_api_key:
        return MaterialSearchResult(query=query, source="pixabay", total=0, items=[], error="PIXABAY_API_KEY not set")

    page = 1
    items: list[MaterialItem] = []
    async with httpx.AsyncClient(timeout=30) as client:
        while len(items) < count:
            params: dict[str, str | int] = {
                "key": config.pixabay_api_key,
                "q": query,
                "image_type": "video",
                "per_page": min(20, max(count, 20)),
                "page": page,
            }
            try:
                resp = await client.get("https://pixabay.com/api/videos/", params=params)
                resp.raise_for_status()
                data = resp.json()

                hits = data.get("hits", [])
                for h in hits:
                    duration = float(h.get("duration", 0))
                    if duration < min_duration:
                        continue

                    for vid in h.get("videos", {}).values():
                        w = vid.get("width", 0)
                        hgt = vid.get("height", 0)
                        if w >= 480 and hgt >= 480:
                            items.append(MaterialItem(
                                url=vid.get("url", ""),
                                thumbnail=h.get("picture"),
                                duration=duration,
                                width=w,
                                height=hgt,
                                source="pixabay",
                                search_term=query,
                                asset_id=str(h.get("id")),
                                source_page=h.get("pageURL"),
                                creator={"name": h.get("user", "")},
                                rendition={"width": w, "height": hgt},
                                score=0.5,
                            ))

                if page >= data.get("totalHits", 0) // params["per_page"] or not hits:
                    break
                page += 1
            except Exception as e:
                logger.error(f"Pixabay search failed: {e}")
                break

    return MaterialSearchResult(query=query, source="pixabay", total=len(items), items=items[:count])


async def search_archive_org(query: str, count: int = 10, min_duration: int = 5) -> MaterialSearchResult:
    """从 Archive.org 搜索公开素材"""
    config = _get_config()
    if not config.archive_org_enabled:
        return MaterialSearchResult(query=query, source="archive_org", total=0, items=[], error="Archive.org disabled")

    params: dict[str, str | int] = {
        "q": f"collection:movies AND mediatype:movies AND {query}",
        "fl[]": "identifier,title,duration",
        "page": 1,
        "pageSize": count * 3,
        "sort[]": "publicdate+desc",
    }

    async with httpx.AsyncClient(timeout=30) as client:
        try:
            resp = await client.get("https://archive.org/advancedsearch.php", params=params)
            resp.raise_for_status()
            data = resp.json()

            items: list[MaterialItem] = []
            for doc in data.get("response", {}).get("docs", []):
                duration = float(doc.get("duration", 0))
                if duration < min_duration:
                    continue
                identifier = doc.get("identifier", "")
                items.append(MaterialItem(
                    url=f"https://archive.org/download/{identifier}/{identifier}.mp4",
                    thumbnail=f"https://archive.org/download/{identifier}/{identifier}.thumb",
                    duration=duration,
                    width=1280,
                    height=720,
                    source="archive_org",
                    search_term=query,
                    asset_id=identifier,
                    source_page=f"https://archive.org/details/{identifier}",
                    score=0.5,
                ))

            return MaterialSearchResult(query=query, source="archive_org", total=len(items), items=items[:count])
        except Exception as e:
            logger.error(f"Archive.org search failed: {e}")
            return MaterialSearchResult(query=query, source="archive_org", total=0, items=[], error=str(e))


async def search_materials(query: str, source: str = "all", count: int = 10, min_duration: int = 5) -> dict[str, Any]:
    """搜索素材 (聚合多个来源)"""
    results: dict[str, Any] = {}

    sources_to_search = ["pexels", "pixabay", "archive_org"] if source == "all" else [source]

    for src in sources_to_search:
        if src == "pexels":
            result = await search_pexels(query, count, min_duration)
        elif src == "pixabay":
            result = await search_pixabay(query, count, min_duration)
        elif src == "archive_org":
            result = await search_archive_org(query, count, min_duration)
        else:
            result = MaterialSearchResult(query=query, source=src, total=0, items=[], error=f"Unknown source: {src}")

        results[src] = result.model_dump()

    return results


__all__ = [
    "MaterialItem",
    "MaterialSearchConfig",
    "MaterialSearchResult",
    "search_archive_org",
    "search_materials",
    "search_pexels",
    "search_pixabay",
]
