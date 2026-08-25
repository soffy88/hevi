"""material_corpus —— 免费/开放素材语料库(3O oskill 风格组合, 差距 A4/B9)。

对标 MoneyPrinterTurbo 的 Pexels/Pixabay/Coverr 三源 + 素材缓存, 与 OpenMontage 的
开放档案(Archive.org)路径, 补 hevi 差距: 此前只有 Pexels stock, 素材源单一。

能力:
  - 多源检索: Pexels(视频/图片) / Pixabay(视频/图片) / Coverr(视频) /
    Archive.org(开放档案视频, 无需 key)
  - 源间去重 + 归一化 MaterialInfo(aspect/时长/分辨率/来源 URL/本地缓存路径)
  - 本地磁盘缓存(素材下载缓存, 命中不重复下载; 元数据缓存可选)
  - 匹配工具: aspect 过滤(9:16/16:9/1:1) + 时长区间 + 关键词相关性排序
  - 缺 key 的源自动跳过(不阻断)

设计:
  - 纯函数层(plan_material_match / filter_by_aspect / pick_best)可单测, 无网络。
  - IO 层(search_* / ensure_cached)走 httpx, 由调用方注入 client; 失败降级跳过。
  - CLIP 语义索引(文本-图像对齐)留待素材量级上来后复用 vault embedding 设施(见
    COMPETITIVE-GAP.md §4.1 TODO)。
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_ASPECT_SCORE: dict[str, dict[str, float]] = {
    "9:16": {"9:16": 1.0, "16:9": 0.2, "1:1": 0.5, "4:5": 0.7},
    "16:9": {"16:9": 1.0, "9:16": 0.2, "1:1": 0.5, "4:3": 0.8, "4:5": 0.4},
    "1:1": {"1:1": 1.0, "9:16": 0.5, "16:9": 0.5, "4:5": 0.7},
    "4:5": {"4:5": 1.0, "9:16": 0.7, "1:1": 0.7, "16:9": 0.4},
    "4:3": {"4:3": 1.0, "16:9": 0.8, "1:1": 0.7},
}

# Archive.org 高级搜索端点(无需 key, 开放档案)。
_ARCHIVE_SEARCH_URL = "https://archive.org/advancedsearch.php"


@dataclass(frozen=True)
class MaterialInfo:
    """归一化素材条目。source 为 pexels/pixabay/coverr/archive。"""

    source: str
    id: str
    url: str  # 直链(下载用)
    page_url: str = ""
    width: int = 0
    height: int = 0
    duration_s: float = 0.0
    title: str = ""
    keywords: tuple[str, ...] = ()
    cached_path: str = ""  # 本地缓存路径(ensure_cached 后填充)

    @property
    def aspect(self) -> str:
        if self.width and self.height:
            ratio = self.width / self.height
            if ratio > 1.15:
                return "16:9"
            if 1.0 / ratio > 1.15:
                return "9:16"
            return "1:1"
        return ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# 纯函数层(无网络, 可单测)
# ---------------------------------------------------------------------------


def aspect_fit(target: str, candidate: str | None) -> float:
    """目标画幅对候选画幅的契合分(0-1)。candidate 未知 → 0(不参与排序)。"""
    if not candidate:
        return 0.0
    return _ASPECT_SCORE.get(target, {}).get(candidate, 0.0)


def filter_by_aspect(
    items: Sequence[MaterialInfo], target: str, *, min_fit: float = 0.5
) -> list[MaterialInfo]:
    """按画幅契合分过滤(低于 min_fit 剔除; 未知画幅剔除)。"""
    return [m for m in items if aspect_fit(target, m.aspect) >= min_fit]


def filter_by_duration(
    items: Sequence[MaterialInfo], *, min_s: float = 0.0, max_s: float | None = None
) -> list[MaterialInfo]:
    """时长过滤: 在 [min_s, max_s] 区间内(未知时长保留, 由调用方决定)。"""
    out: list[MaterialInfo] = []
    for m in items:
        if m.duration_s <= 0:
            out.append(m)
            continue
        if m.duration_s < min_s:
            continue
        if max_s is not None and m.duration_s > max_s:
            continue
        out.append(m)
    return out


def rank_by_keywords(
    items: Sequence[MaterialInfo], query: str, *, target_aspect: str = ""
) -> list[MaterialInfo]:
    """关键词相关性排序(标题/关键词命中计数) + 画幅契合加分。

    query 按空白/逗号切词; 命中标题 +2, 命中关键词 +1; 画幅契合 +0.5。
    返回按分数降序的新列表。
    """
    terms = [t.lower() for t in query.replace(",", " ").split() if t.strip()]
    scored: list[tuple[float, MaterialInfo]] = []
    for m in items:
        score = 0.0
        hay_title = m.title.lower()
        hay_kw = " ".join(m.keywords).lower()
        for t in terms:
            if t in hay_title:
                score += 2.0
            elif t in hay_kw:
                score += 1.0
        if target_aspect:
            score += aspect_fit(target_aspect, m.aspect) * 0.5
        scored.append((score, m))
    scored.sort(key=lambda t: t[0], reverse=True)
    return [m for _, m in scored]


def pick_best(
    items: Sequence[MaterialInfo],
    query: str,
    *,
    target_aspect: str = "",
    min_s: float = 0.0,
    max_s: float | None = None,
) -> MaterialInfo | None:
    """一站式挑选: 画幅过滤 → 时长过滤 → 关键词排序 → 取最优。"""
    filtered = filter_by_aspect(items, target_aspect) if target_aspect else list(items)
    filtered = filter_by_duration(filtered, min_s=min_s, max_s=max_s)
    ranked = rank_by_keywords(filtered, query, target_aspect=target_aspect)
    return ranked[0] if ranked else None


def dedupe(items: Sequence[MaterialInfo]) -> list[MaterialInfo]:
    """按 (source, id) 去重, 保序。"""
    seen: set[tuple[str, str]] = set()
    out: list[MaterialInfo] = []
    for m in items:
        key = (m.source, m.id)
        if key in seen:
            continue
        seen.add(key)
        out.append(m)
    return out


# ---------------------------------------------------------------------------
# IO 层(网络; 调用方注入 client; 失败降级)
# ---------------------------------------------------------------------------


def _cache_path(cache_dir: Path, url: str, ext: str) -> Path:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    return cache_dir / f"{digest}{ext}"


def ensure_cached(
    item: MaterialInfo,
    cache_dir: Path,
    *,
    client: httpx.Client | None = None,
) -> MaterialInfo:
    """把素材直链下载到本地缓存(命中返回 cached_path), 失败返回原条目(cached_path 空)。

    下载失败只记日志不抛(素材缺失不该阻断整条流水线)。
    """
    if item.cached_path and Path(item.cached_path).exists():
        return item
    try:
        suffix = Path(item.url.split("?")[0]).suffix or ".mp4"
    except Exception:  # pragma: no cover - URL 解析兜底
        suffix = ".mp4"
    target = _cache_path(cache_dir, item.url, suffix)
    if target.exists():
        return MaterialInfo(**{**item.to_dict(), "cached_path": str(target)})
    cache_dir.mkdir(parents=True, exist_ok=True)
    own_client = client is None
    tmp: Path | None = None
    try:
        c = client or httpx.Client(timeout=30.0, follow_redirects=True)
        with c.stream("GET", item.url) as resp:
            resp.raise_for_status()
            tmp = target.with_suffix(target.suffix + ".part")
            with tmp.open("wb") as f:
                for chunk in resp.iter_bytes(65536):
                    f.write(chunk)
        assert tmp is not None
        tmp.replace(target)
        return MaterialInfo(**{**item.to_dict(), "cached_path": str(target)})
    except (httpx.HTTPError, OSError) as exc:
        logger.warning("material download failed (%s): %s", item.url, exc)
        try:
            if tmp is not None:
                tmp.unlink(missing_ok=True)
        except OSError:  # pragma: no cover
            pass
        return item
    finally:
        if own_client and client is None:
            c.close()


def search_pexels_videos(
    query: str,
    api_key: str,
    *,
    per_page: int = 10,
    client: httpx.Client | None = None,
    orientation: str = "portrait",
) -> list[MaterialInfo]:
    """Pexels 视频搜索。无 key 或请求失败 → 空列表(降级跳过)。"""
    if not api_key:
        return []
    try:
        own = client is None
        c = client or httpx.Client(timeout=15.0)
        resp = c.get(
            "https://api.pexels.com/videos/search",
            params={"query": query, "per_page": per_page, "orientation": orientation},
            headers={"Authorization": api_key},
        )
        resp.raise_for_status()
        data = resp.json()
        items: list[MaterialInfo] = []
        for v in data.get("videos", []):
            files = v.get("video_files") or []
            best = None
            for f in files:
                if f.get("width") and f.get("height") and (
                    best is None or (f["width"] * f["height"]) > (best["width"] * best["height"])
                ):
                    best = f
            if not best or not best.get("link"):
                continue
            items.append(
                MaterialInfo(
                    source="pexels",
                    id=str(v.get("id", "")),
                    url=best["link"],
                    page_url=v.get("url", ""),
                    width=int(best.get("width") or 0),
                    height=int(best.get("height") or 0),
                    duration_s=float(v.get("duration") or 0.0),
                    title=(v.get("user", {}) or {}).get("name", "") or query,
                    keywords=tuple((v.get("tags") or [])[:8]),
                )
            )
        return items
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("pexels search failed (%s): %s", query, exc)
        return []
    finally:
        if own and client is None:
            c.close()


def search_pixabay_videos(
    query: str,
    api_key: str,
    *,
    per_page: int = 10,
    client: httpx.Client | None = None,
    orientation: str = "vertical",
) -> list[MaterialInfo]:
    """Pixabay 视频搜索。无 key 或失败 → 空列表。"""
    if not api_key:
        return []
    try:
        own = client is None
        c = client or httpx.Client(timeout=15.0)
        resp = c.get(
            "https://pixabay.com/api/videos/",
            params={"key": api_key, "q": query, "per_page": per_page, "orientation": orientation},
        )
        resp.raise_for_status()
        data = resp.json()
        items: list[MaterialInfo] = []
        for v in data.get("hits", []):
            url = v.get("videos", {}).get("large", {}).get("url")
            if not url:
                continue
            items.append(
                MaterialInfo(
                    source="pixabay",
                    id=str(v.get("id", "")),
                    url=url,
                    page_url=v.get("pageURL", ""),
                    width=int(v.get("width") or 0),
                    height=int(v.get("height") or 0),
                    duration_s=float(v.get("duration") or 0.0),
                    title=v.get("tags", query) or query,
                    keywords=tuple(str(v.get("tags", "")).split(",")[:8]),
                )
            )
        return items
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("pixabay search failed (%s): %s", query, exc)
        return []
    finally:
        if own and client is None:
            c.close()


def search_coverr_videos(
    query: str,
    api_key: str,
    *,
    per_page: int = 10,
    client: httpx.Client | None = None,
) -> list[MaterialInfo]:
    """Coverr 视频搜索(免费视频; key 可为空时走公开端点)。失败 → 空列表。"""
    try:
        own = client is None
        c = client or httpx.Client(timeout=15.0)
        headers = {"Authorization": api_key} if api_key else {}
        resp = c.get(
            "https://api.coverr.co/videos",
            params={"query": query, "per_page": per_page, "sort_by": "relevant"},
            headers=headers,
        )
        resp.raise_for_status()
        data = resp.json()
        hits = data.get("hits") or data.get("videos") or []
        items: list[MaterialInfo] = []
        for v in hits:
            url = v.get("mp4") or v.get("url")
            if not url:
                continue
            items.append(
                MaterialInfo(
                    source="coverr",
                    id=str(v.get("id", "")),
                    url=url,
                    page_url=v.get("page_url", "") or v.get("poster", ""),
                    width=int(v.get("width") or 0),
                    height=int(v.get("height") or 0),
                    duration_s=float(v.get("duration") or 0.0),
                    title=v.get("title", query) or query,
                    keywords=tuple((v.get("tags") or [])[:8]),
                )
            )
        return items
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("coverr search failed (%s): %s", query, exc)
        return []
    finally:
        if own and client is None:
            c.close()


def search_archive_videos(
    query: str,
    *,
    per_page: int = 10,
    client: httpx.Client | None = None,
    media_type: str = "movies",
) -> list[MaterialInfo]:
    """Archive.org 开放档案视频搜索(无需 key)。失败 → 空列表。"""
    try:
        own = client is None
        c = client or httpx.Client(timeout=20.0)
        resp = c.get(
            _ARCHIVE_SEARCH_URL,
            params={
                "q": f"{query} AND mediatype:{media_type}",
                "fl[]": "identifier,title,width,height,length",
                "rows": per_page,
                "page": 1,
                "output": "json",
            },
        )
        resp.raise_for_status()
        data = resp.json()
        docs = data.get("response", {}).get("docs", [])
        items: list[MaterialInfo] = []
        for d in docs:
            ident = d.get("identifier", "")
            if not ident:
                continue
            items.append(
                MaterialInfo(
                    source="archive",
                    id=ident,
                    url=f"https://archive.org/download/{ident}/{ident}.mp4",
                    page_url=f"https://archive.org/details/{ident}",
                    width=int(d.get("width") or 0),
                    height=int(d.get("height") or 0),
                    duration_s=float(d.get("length") or 0.0),
                    title=str(d.get("title", ident))[:200],
                )
            )
        return items
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("archive search failed (%s): %s", query, exc)
        return []
    finally:
        if own and client is None:
            c.close()


def search_all(
    query: str,
    *,
    pexels_key: str = "",
    pixabay_key: str = "",
    coverr_key: str = "",
    include_archive: bool = True,
    per_source: int = 5,
    client: httpx.Client | None = None,
) -> list[MaterialInfo]:
    """多源并行检索(串行实现, 源内失败各自降级), 返回去重后的合并列表。

    排序: 按 source 固定优先级(pexels > pixabay > coverr > archive), 便于调用方
    拿 pick_best 前保证稳定顺序。
    """
    merged: list[MaterialInfo] = []
    merged += search_pexels_videos(query, pexels_key, per_page=per_source, client=client)
    merged += search_pixabay_videos(query, pixabay_key, per_page=per_source, client=client)
    merged += search_coverr_videos(query, coverr_key, per_page=per_source, client=client)
    if include_archive:
        merged += search_archive_videos(query, per_page=per_source, client=client)
    return dedupe(merged)


__all__ = [
    "MaterialInfo",
    "aspect_fit",
    "dedupe",
    "ensure_cached",
    "filter_by_aspect",
    "filter_by_duration",
    "pick_best",
    "rank_by_keywords",
    "search_all",
    "search_archive_videos",
    "search_coverr_videos",
    "search_pexels_videos",
    "search_pixabay_videos",
]
