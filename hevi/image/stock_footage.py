"""素材自动搜索服务 — 对标 MoneyPrinterTurbo 的素材自动获取。

支持平台:
- Pexels API (https://api.pexels.com)
- Pixabay API (https://pixabay.com/api/)

能力:
- 关键词搜索素材 (图片/视频)
- 自动下载 + 缓存
- 批量搜索 (脚本关键词 → 多段素材)
- 按分辨率/方向/颜色过滤

参考: https://github.com/harry0703/MoneyPrinterTurbo
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from enum import Enum
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlencode

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

__all__ = [
    "StockProvider",
    "StockMediaType",
    "StockSearchRequest",
    "StockItem",
    "StockSearchResult",
    "search_stock",
    "search_and_download",
    "script_to_stock_clips",
]


class StockProvider(str, Enum):
    pexels = "pexels"
    pixabay = "pixabay"


class StockMediaType(str, Enum):
    image = "image"
    video = "video"


class StockSearchRequest(BaseModel):
    query: str
    media_type: StockMediaType = StockMediaType.video
    provider: StockProvider = StockProvider.pexels
    count: int = 5
    min_width: int = 1280
    min_height: int = 720
    orientation: str = "landscape"  # landscape, portrait, square
    language: str = "zh"
    color: Optional[str] = None  # red, blue, green, black, white, etc.


class StockItem(BaseModel):
    id: str
    url: str  # download URL
    preview_url: str
    width: int = 0
    height: int = 0
    duration: float = 0.0  # seconds (video only)
    provider: str = ""
    media_type: str = ""
    tags: list[str] = Field(default_factory=list)
    photographer: str = ""
    license: str = "free"


class StockSearchResult(BaseModel):
    query: str
    provider: str
    items: list[StockItem] = Field(default_factory=list)
    total_available: int = 0
    success: bool = False
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# API keys (from env)
# ---------------------------------------------------------------------------

def _get_pexels_key() -> str:
    return os.environ.get("PEXELS_API_KEY", "")


def _get_pixabay_key() -> str:
    return os.environ.get("PIXABAY_API_KEY", "")


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

_CACHE_DIR = Path(".stock_cache")
_CACHE_DIR.mkdir(exist_ok=True)


def _cache_key(query: str, provider: str, media_type: str) -> str:
    h = hashlib.md5(f"{query}:{provider}:{media_type}".encode()).hexdigest()[:12]
    return h


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------

async def _search_pexels(request: StockSearchRequest) -> StockSearchResult:
    """Pexels API 搜索。"""
    api_key = _get_pexels_key()
    if not api_key:
        return StockSearchResult(
            query=request.query, provider="pexels",
            error="PEXELS_API_KEY not set. Get one at https://www.pexels.com/api/",
        )

    endpoint = "videos" if request.media_type == StockMediaType.video else "photos"
    params = {
        "query": request.query,
        "per_page": min(request.count, 80),
        "orientation": request.orientation,
        "size": "large",
    }
    if request.color:
        params["color"] = request.color

    url = f"https://api.pexels.com/v1/search?{urlencode(params)}"
    headers = {"Authorization": api_key}

    try:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=15) as resp:
                if resp.status != 200:
                    return StockSearchResult(
                        query=request.query, provider="pexels",
                        error=f"HTTP {resp.status}: {await resp.text()}",
                    )
                data = await resp.json()

        items: list[StockItem] = []
        if request.media_type == StockMediaType.video:
            for v in data.get("videos", []):
                # Pick best quality >= min resolution
                best = None
                for f in v.get("video_files", []):
                    if f.get("width", 0) >= request.min_width and f.get("quality") == "hd":
                        best = f
                        break
                if not best and v.get("video_files"):
                    best = v["video_files"][0]
                if best:
                    items.append(StockItem(
                        id=str(v["id"]),
                        url=best["link"],
                        preview_url=v.get("image", ""),
                        width=best.get("width", 0),
                        height=best.get("height", 0),
                        duration=float(v.get("duration", 0)),
                        provider="pexels",
                        media_type="video",
                        photographer=v.get("user", {}).get("name", ""),
                    ))
        else:
            for p in data.get("photos", []):
                items.append(StockItem(
                    id=str(p["id"]),
                    url=p["src"].get("large2x", p["src"].get("large", "")),
                    preview_url=p["src"].get("medium", ""),
                    width=p.get("width", 0),
                    height=p.get("height", 0),
                    provider="pexels",
                    media_type="image",
                    photographer=p.get("photographer", ""),
                ))

        return StockSearchResult(
            query=request.query,
            provider="pexels",
            items=items[:request.count],
            total_available=data.get("total_results", 0),
            success=True,
        )
    except Exception as e:
        return StockSearchResult(query=request.query, provider="pexels", error=str(e))


async def _search_pixabay(request: StockSearchRequest) -> StockSearchResult:
    """Pixabay API 搜索。"""
    api_key = _get_pixabay_key()
    if not api_key:
        return StockSearchResult(
            query=request.query, provider="pixabay",
            error="PIXABAY_API_KEY not set. Get one at https://pixabay.com/api/docs/",
        )

    media = "videos" if request.media_type == StockMediaType.video else ""
    params = {
        "key": api_key,
        "q": request.query,
        "per_page": min(request.count, 200),
        "orientation": request.orientation,
        "min_width": request.min_width,
        "min_height": request.min_height,
        "safesearch": "true",
    }
    if request.color:
        params["colors"] = request.color

    base = f"https://pixabay.com/api/{media}/" if media else "https://pixabay.com/api/"
    url = f"{base}?{urlencode(params)}"

    try:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=15) as resp:
                if resp.status != 200:
                    return StockSearchResult(
                        query=request.query, provider="pixabay",
                        error=f"HTTP {resp.status}",
                    )
                data = await resp.json()

        items: list[StockItem] = []
        for hit in data.get("hits", []):
            if request.media_type == StockMediaType.video:
                videos = hit.get("videos", {})
                best = videos.get("large", videos.get("medium", videos.get("small", {})))
                items.append(StockItem(
                    id=str(hit["id"]),
                    url=best.get("url", ""),
                    preview_url=videos.get("tiny", {}).get("url", ""),
                    width=best.get("width", 0),
                    height=best.get("height", 0),
                    duration=float(hit.get("duration", 0)),
                    provider="pixabay",
                    media_type="video",
                    tags=hit.get("tags", "").split(", "),
                ))
            else:
                items.append(StockItem(
                    id=str(hit["id"]),
                    url=hit.get("largeImageURL", hit.get("webformatURL", "")),
                    preview_url=hit.get("previewURL", ""),
                    width=hit.get("imageWidth", 0),
                    height=hit.get("imageHeight", 0),
                    provider="pixabay",
                    media_type="image",
                    tags=hit.get("tags", "").split(", "),
                ))

        return StockSearchResult(
            query=request.query,
            provider="pixabay",
            items=items[:request.count],
            total_available=data.get("totalHits", 0),
            success=True,
        )
    except Exception as e:
        return StockSearchResult(query=request.query, provider="pixabay", error=str(e))


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------

async def search_stock(request: StockSearchRequest) -> StockSearchResult:
    """搜索素材。"""
    if request.provider == StockProvider.pexels:
        return await _search_pexels(request)
    return await _search_pixabay(request)


async def _download(url: str, dest: Path) -> bool:
    """下载文件。"""
    try:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=60) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    dest.write_bytes(data)
                    return True
    except Exception as e:
        logger.warning("Download failed %s: %s", url, e)
    return False


async def search_and_download(
    request: StockSearchRequest,
    output_dir: str = "/tmp/stock_clips",
) -> list[Path]:
    """搜索并下载素材。"""
    result = await search_stock(request)
    if not result.success:
        logger.error("Stock search failed: %s", result.error)
        return []

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    downloaded: list[Path] = []
    for item in result.items:
        ext = "mp4" if item.media_type == "video" else "jpg"
        dest = out / f"{item.provider}_{item.id}.{ext}"
        if dest.exists():
            downloaded.append(dest)
            continue
        ok = await _download(item.url, dest)
        if ok:
            downloaded.append(dest)

    logger.info("Downloaded %d/%d clips for query='%s'", len(downloaded), len(result.items), request.query)
    return downloaded


async def script_to_stock_clips(
    script: str,
    keywords_per_clip: int = 2,
    clips_count: int = 5,
    provider: StockProvider = StockProvider.pexels,
    output_dir: str = "/tmp/stock_clips",
) -> dict[str, Any]:
    """从脚本自动提取关键词 → 搜索素材 → 下载。

    简单关键词提取: 按句子分割, 取前N个名词/动词作为关键词。
    生产环境可接入 LLM 做更精准的关键词提取。
    """
    # Extract keywords (simple: split by punctuation, take first words)
    sentences = [s.strip() for s in script.replace("。", "\n").replace("！", "\n").replace("？", "\n").split("\n") if s.strip()]

    all_clips: list[dict] = []
    for i, sentence in enumerate(sentences[:clips_count]):
        # Simple keyword extraction
        words = sentence.split()[:keywords_per_clip]
        query = " ".join(words) if words else sentence[:20]

        request = StockSearchRequest(
            query=query,
            media_type=StockMediaType.video,
            provider=provider,
            count=1,
        )
        clips = await search_and_download(request, output_dir)
        for clip in clips:
            all_clips.append({
                "sentence": sentence,
                "query": query,
                "clip_path": str(clip),
                "index": i,
            })

    return {
        "script": script,
        "clips": all_clips,
        "total_clips": len(all_clips),
        "output_dir": output_dir,
    }
