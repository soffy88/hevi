"""oprim:oprim_broll —— Pexels 高清 B-roll 视频检索原子能力(绝对无状态)。

只负责:按查询词向 Pexels 检索动态视频素材, 返回归一化候选列表。
不涉及状态写入、不落任何数据库(Lite 管道零 Postgres 依赖, 与主管道
hevi/sourcing/stock_search.py 的 StockSearchService 同源但更轻)。

约定:
  * PEXELS_API_KEY 未配置 / 网络失败 → 返回 None(omodul 据此降级为纯色背景,
    绝不中断装配);
  * 返回候选含 preview_url(视频直链, 供 <video> 直接播放)。
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_PEXELS_API = "https://api.pexels.com"


class BrollUnavailable(RuntimeError):
    """Pexels 检索不可用(未配置 key / 授权失败)。"""


async def fetch_broll_video_url(
    query: str,
    *,
    count: int = 3,
    orientation: str | None = "portrait",
    api_key: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> list[dict[str, Any]] | None:
    """按查询词检索 Pexels 视频素材。

    Args:
        query: 检索词(如 cue 核心名词或整片 topic)。
        count: 期望候选数。
        orientation: landscape/portrait/square; None 不限制。
        api_key: 显式 key; 缺省读 PEXELS_API_KEY 环境变量。

    Returns:
        归一化素材列表 [{preview_url, thumbnail_url, title, source_url}],
        不可用(无 key/授权失败/网络异常)返回 None —— 调用方降级不中断。
    """
    key = (api_key if api_key is not None else os.getenv("PEXELS_API_KEY", "")).strip()
    if not key:
        logger.warning("PEXELS_API_KEY 未配置, B-roll 背景降级为纯色")
        return None
    params: dict[str, str | int] = {"query": query, "per_page": min(max(count, 1), 80)}
    if orientation:
        params["orientation"] = orientation
    try:
        if client is not None:
            response = await client.get(
                f"{_PEXELS_API}/videos/search",
                params=params,
                headers={"Authorization": key},
            )
        else:
            async with httpx.AsyncClient(timeout=20.0) as http:
                response = await http.get(
                    f"{_PEXELS_API}/videos/search",
                    params=params,
                    headers={"Authorization": key},
                )
    except httpx.HTTPError as exc:
        logger.warning("Pexels 请求失败, 降级: %s", exc)
        return None
    if response.status_code in {401, 403}:
        logger.warning("Pexels 授权失败(检查 PEXELS_API_KEY), 降级")
        return None
    if response.status_code >= 400:
        logger.warning("Pexels 返回 HTTP %s, 降级", response.status_code)
        return None
    try:
        payload = response.json()
    except ValueError:
        return None
    items = payload.get("videos") or []
    candidates: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict) or item.get("id") is None or not item.get("url"):
            continue
        files = item.get("video_files") or []
        # 优先 SD/HD mp4(浏览器直接可播); 跳过 hls 索引。
        link = next(
            (
                str(file["link"])
                for file in files
                if isinstance(file, dict)
                and file.get("link")
                and file.get("file_type", "").startswith("video/mp4")
            ),
            None,
        )
        if not link:
            continue
        photographer = item.get("user") or {}
        candidates.append(
            {
                "provider": "pexels",
                "external_id": str(item["id"]),
                "media_type": "video",
                "title": f"{query} · {photographer.get('name', 'Pexels')}",
                "source_url": str(item["url"]),
                "preview_url": link,
                "thumbnail_url": item.get("image"),
                "query": query,
            }
        )
        if len(candidates) >= count:
            break
    if not candidates:
        logger.warning("Pexels 检索「%s」无结果, 降级", query)
        return None
    return candidates


__all__ = ["BrollUnavailable", "fetch_broll_video_url"]
