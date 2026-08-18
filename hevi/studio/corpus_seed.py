"""把 NASA / Wikimedia / Archive.org 公开域短片种进本地语料库。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_NASA_SEARCH = "https://images-api.nasa.gov/search"
_WIKI_API = "https://commons.wikimedia.org/w/api.php"
_UA = {"User-Agent": "HeviAssetPull/1.0 (https://github.com/hevi; corpus-seed)"}


def _pick_smallest_mp4(urls: list[str], *, max_mb: int) -> str | None:
    del max_mb
    mp4s = [u for u in urls if ".mp4" in u.lower()]
    if not mp4s:
        return None

    def _rank(url: str) -> int:
        low = url.lower()
        if "preview" in low or "small" in low or "mobile" in low:
            return 0
        if "medium" in low or "orig" not in low:
            return 1
        return 2

    return sorted(mp4s, key=_rank)[0]


def search_nasa_videos(query: str, *, limit: int = 2) -> list[dict[str, Any]]:
    try:
        resp = httpx.get(
            _NASA_SEARCH,
            params={"q": query, "media_type": "video"},
            timeout=20.0,
            headers=_UA,
        )
        resp.raise_for_status()
        items = (resp.json().get("collection") or {}).get("items") or []
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("nasa search failed (%s): %s", query, exc)
        return []
    out: list[dict[str, Any]] = []
    for item in items[: limit * 2]:
        data = (item.get("data") or [{}])[0]
        href = str(item.get("href") or "")
        if not href:
            continue
        try:
            assets = httpx.get(href, timeout=20.0, headers=_UA).json()
        except (httpx.HTTPError, ValueError):
            continue
        urls = [str(u) for u in assets] if isinstance(assets, list) else []
        url = _pick_smallest_mp4(urls, max_mb=25)
        if not url:
            continue
        out.append(
            {
                "id": str(data.get("nasa_id") or data.get("title") or query),
                "title": str(data.get("title") or query),
                "url": url,
                "source": "nasa",
                "license": "nasa-media",
                "page": f"https://images.nasa.gov/details-{data.get('nasa_id', '')}",
            }
        )
        if len(out) >= limit:
            break
    return out


def search_wikimedia_videos(query: str, *, limit: int = 2) -> list[dict[str, Any]]:
    try:
        resp = httpx.get(
            _WIKI_API,
            params={
                "action": "query",
                "format": "json",
                "generator": "search",
                "gsrsearch": f"filetype:video {query}",
                "gsrlimit": str(limit * 3),
                "gsrnamespace": "6",
                "prop": "imageinfo",
                "iiprop": "url|size|mime",
            },
            timeout=20.0,
            headers=_UA,
        )
        resp.raise_for_status()
        pages = (resp.json().get("query") or {}).get("pages") or {}
    except (httpx.HTTPError, ValueError) as ext:
        logger.warning("wikimedia search failed (%s): %s", query, ext)
        return []
    out: list[dict[str, Any]] = []
    for page in pages.values():
        info = (page.get("imageinfo") or [{}])[0]
        url = str(info.get("url") or "")
        mime = str(info.get("mime") or "")
        if "video" not in mime and not url.lower().endswith((".mp4", ".webm", ".ogv")):
            continue
        if info.get("size") and int(info["size"]) > 25 * 1024 * 1024:
            continue
        out.append(
            {
                "id": str(page.get("pageid") or page.get("title") or query),
                "title": str(page.get("title") or query),
                "url": url,
                "source": "wikimedia",
                "license": "cc-by-sa",
                "page": f"https://commons.wikimedia.org/wiki/{page.get('title', '')}",
            }
        )
        if len(out) >= limit:
            break
    return out


async def seed_open_corpus(
    dest: Path,
    queries: list[dict[str, Any]],
    *,
    max_each: int = 2,
    max_mb: int = 25,
) -> list[dict[str, Any]]:
    from hevi.sourcing.corpus import Corpus

    dest.mkdir(parents=True, exist_ok=True)
    corpus = Corpus.load(dest)
    added: list[dict[str, Any]] = []
    for spec in queries:
        query = str(spec.get("q") or "").strip()
        if not query:
            continue
        source = str(spec.get("source") or "archive")
        limit = int(spec.get("max_each") or max_each)
        if source == "nasa":
            hits = search_nasa_videos(query, limit=limit)
            for hit in hits:
                rec = _add_http_clip(corpus, dest, hit, query=query, max_mb=max_mb)
                if rec:
                    added.append(rec)
            continue
        if source == "wikimedia":
            hits = search_wikimedia_videos(query, limit=limit)
            for hit in hits:
                rec = _add_http_clip(corpus, dest, hit, query=query, max_mb=max_mb)
                if rec:
                    added.append(rec)
            continue
        collection = str(spec.get("collection") or "prelinger")
        try:
            recs = await corpus.add_archive_org(
                query=query,
                count=limit,
                max_clip_mb=max_mb,
                collection=collection,
            )
            added.extend(r.to_dict() for r in recs)
        except Exception as exc:
            logger.warning("archive seed %s failed: %s", query, exc)
    corpus.save()
    return added


def _add_http_clip(
    corpus: Any,
    dest: Path,
    hit: dict[str, Any],
    *,
    query: str,
    max_mb: int,
) -> dict[str, Any] | None:
    from hevi.sourcing.corpus import ClipRecord

    url = str(hit.get("url") or "")
    if not url:
        return None
    ident = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in str(hit["id"]))[:40]
    suffix = Path(url.split("?")[0]).suffix or ".mp4"
    clip_id = f"{hit.get('source', 'web')}_{ident}"
    local = dest / "clips" / f"{clip_id}{suffix}"
    local.parent.mkdir(parents=True, exist_ok=True)
    if not local.exists():
        try:
            with httpx.stream(
                "GET", url, timeout=60.0, follow_redirects=True, headers=_UA
            ) as resp:
                resp.raise_for_status()
                size = 0
                tmp = local.with_suffix(local.suffix + ".part")
                with tmp.open("wb") as handle:
                    for chunk in resp.iter_bytes(65536):
                        size += len(chunk)
                        if size > max_mb * 1024 * 1024:
                            tmp.unlink(missing_ok=True)
                            logger.info("skip %s over %sMB", clip_id, max_mb)
                            return None
                        handle.write(chunk)
                tmp.replace(local)
        except (httpx.HTTPError, OSError) as exc:
            logger.warning("download %s failed: %s", url, exc)
            return None
    rec = ClipRecord(
        clip_id=clip_id,
        source=str(hit.get("source") or "web"),
        source_id=str(hit["id"]),
        source_url=str(hit.get("page") or url),
        local_path=str(local.relative_to(dest)),
        query=query,
        title=str(hit.get("title") or query),
        license=str(hit.get("license") or ""),
    )
    if any(existing.clip_id == rec.clip_id for existing in corpus.records):
        return rec.to_dict()
    corpus._index_record(rec)
    return rec.to_dict()
