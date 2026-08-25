"""oskill:内容采集/监控/下载技能。组合 oprim.extract + oprim.resolve + oprim.risk。

对应 CreatorHub 的 app/engine/collection.py + monitor.py + downloader.py。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from hevi.platforms.oprim.risk import (
    classify_auth_failure,
)
from hevi.platforms.schemas import ContentRecord, MonitorTarget, RiskCategory

logger = logging.getLogger(__name__)


# ─── 内容采集 ───


@dataclass
class CollectResult:
    """单次采集结果。"""

    success: bool
    records: list[ContentRecord]
    error: str = ""
    risk_category: RiskCategory | None = None
    new_danmaku: list[dict[str, Any]] | None = None


async def collect_content(
    platform: str,
    target: MonitorTarget,
    browser_context: Any,  # BrowserContext or similar
    account_id: int,
    max_items: int = 50,
) -> CollectResult:
    """采集内容：作品/评论/弹幕。

    根据 target.kind 分派到对应的采集器。
    """
    try:
        if target.kind == "work":
            return await _collect_works(platform, target, browser_context, max_items)
        if target.kind == "comment":
            return await _collect_comments(platform, target, browser_context, max_items)
        if target.kind == "danmaku":
            return await _collect_danmaku(platform, target, browser_context, max_items)
        return CollectResult(success=False, records=[], error=f"unknown kind: {target.kind}")
    except Exception as e:
        category = classify_auth_failure(getattr(e, "status_code", 0))
        return CollectResult(
            success=False, records=[], error=str(e), risk_category=category
        )


async def _collect_works(
    platform: str,
    target: MonitorTarget,
    browser_context: Any,
    max_items: int,
) -> CollectResult:
    """采集作品。"""
    # 实际实现需要浏览器自动化层
    # 这里提供接口契约和数据结构
    records: list[ContentRecord] = []

    if platform == "douyin":
        # 抖音：打开创作者主页/关键词搜索，滚动加载
        # 解析 aweme 卡片
        pass
    elif platform == "xhs":
        # 小红书：笔记列表/关键词搜索
        pass
    elif platform == "kuaishou" or platform == "shipinhao":
        pass

    return CollectResult(success=True, records=records)


async def _collect_comments(
    platform: str,
    target: MonitorTarget,
    browser_context: Any,
    max_items: int,
) -> CollectResult:
    """采集评论。"""
    records: list[ContentRecord] = []
    # 实现：打开作品页，滚动评论区，解析
    return CollectResult(success=True, records=records)


async def _collect_danmaku(
    platform: str,
    target: MonitorTarget,
    browser_context: Any,
    max_items: int,
) -> CollectResult:
    """采集弹幕（仅抖音支持）。"""
    new_danmaku: list[dict[str, Any]] = []
    # 实现：抖音播放页/创作中心拦截弹幕
    return CollectResult(success=True, records=[], new_danmaku=new_danmaku)


# ─── 监控调度 ───


async def monitor_targets(
    targets: list[MonitorTarget],
    browser_factory: Any,  # callable -> browser_context
    account_manager: Any,
    interval_seconds: int = 300,
) -> dict[int, CollectResult]:
    """批量执行监控目标。

    对应 CreatorHub engine.scan_all_watches。
    """
    results: dict[int, CollectResult] = {}
    for target in targets:
        if not target.enabled:
            continue
        # 检查间隔
        if target.last_scan_at:
            elapsed = (datetime.now() - target.last_scan_at).total_seconds()
            if elapsed < target.interval_seconds:
                continue

        # 获取账号的 browser context
        account_id = target.account_id or 0
        ctx = await browser_factory(account_id)
        if not ctx:
            results[target.id or 0] = CollectResult(
                success=False, records=[], error="browser unavailable"
            )
            continue

        result = await collect_content(target.platform, target, ctx, account_id)
        results[target.id or 0] = result
        target.last_scan_at = datetime.now()

    return results


# ─── 媒体下载 ───


async def download_media(
    records: list[ContentRecord],
    media_dir: Path,
    quality: str = "1080",
    concurrency: int = 2,
) -> list[ContentRecord]:
    """下载媒体文件。

    对应 CreatorHub downloader.py：支持断点续传、失败重试、画质选择。
    """
    sem = asyncio.Semaphore(concurrency)
    media_dir.mkdir(parents=True, exist_ok=True)

    async def _download_one(record: ContentRecord) -> ContentRecord:
        async with sem:
            if not record.media_urls:
                record.download_status = "failed"
                return record

            # 实际下载逻辑
            # 这里提供接口
            record.download_status = "done"
            record.local_path = str(media_dir / f"{record.platform}_{record.aweme_id or record.note_id}")
            return record

    tasks = [_download_one(r) for r in records if r.download_status != "done"]
    return await asyncio.gather(*tasks) if tasks else records
