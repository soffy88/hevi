"""多平台视频发布服务 — 对标 video-publisher-skill。

支持平台: 小红书 / 抖音 / Bilibili / 微信视频号 / YouTube(已有)。
架构: 浏览器自动化 (Playwright) + 有状态调度器 + 安全预发布模式。

Safety:
  pre_publish_mode = True  — 上传 + 填写元数据, 但不点击发布。
  用户需显式 auto_publish=True 或调用 confirm_publish() 才能上线。

参考: https://github.com/nicepkg/video-publisher-skill
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from abc import ABC, abstractmethod
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

__all__ = [
    "PublishPlatform",
    "PublishStatus",
    "PublishTask",
    "PublishBatchRequest",
    "PublishBatchResult",
    "PublishPlatformConfig",
    "publish_video",
    "publish_batch",
    "schedule_publish",
    "get_platform_config",
    "validate_platform_credentials",
    "confirm_publish",
]


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class PublishPlatform(str, Enum):
    xiaohongshu = "xiaohongshu"
    douyin = "douyin"
    bilibili = "bilibili"
    wechat_video = "wechat_video"
    youtube = "youtube"


class PublishStatus(str, Enum):
    pending = "pending"
    uploading = "uploading"
    processing = "processing"
    ready_to_publish = "ready_to_publish"
    published = "published"
    failed = "failed"
    cancelled = "cancelled"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class PublishPlatformConfig(BaseModel):
    platform: PublishPlatform
    cookies_path: str = ""
    publish_url: str = ""
    title_limit: int = 100
    tags_limit: int = 20
    max_file_size_mb: int = 4096
    supported_formats: list[str] = Field(default_factory=lambda: ["mp4", "mov"])
    extra: dict[str, Any] = Field(default_factory=dict)


class PublishTask(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:16])
    platform: PublishPlatform
    video_path: str
    title: str = ""
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    cover_path: Optional[str] = None
    scheduled_at: Optional[datetime] = None
    status: PublishStatus = PublishStatus.pending
    error: Optional[str] = None
    published_url: Optional[str] = None
    auto_publish: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)


class PublishBatchRequest(BaseModel):
    tasks: list[PublishTask]
    auto_publish: bool = False
    max_parallel: int = 3


class PublishBatchResult(BaseModel):
    total: int = 0
    succeeded: int = 0
    failed: int = 0
    task_results: list[PublishTask] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Platform configs
# ---------------------------------------------------------------------------

_PLATFORM_CONFIGS: dict[PublishPlatform, PublishPlatformConfig] = {
    PublishPlatform.xiaohongshu: PublishPlatformConfig(
        platform=PublishPlatform.xiaohongshu,
        publish_url="https://creator.xiaohongshu.com/publish/publish",
        title_limit=20,
        tags_limit=10,
    ),
    PublishPlatform.douyin: PublishPlatformConfig(
        platform=PublishPlatform.douyin,
        publish_url="https://creator.douyin.com/creator-micro/content/upload",
        title_limit=55,
        tags_limit=20,
    ),
    PublishPlatform.bilibili: PublishPlatformConfig(
        platform=PublishPlatform.bilibili,
        publish_url="https://member.bilibili.com/platform/upload/video/frame",
        title_limit=80,
        tags_limit=12,
        extra={"partition": "", "copyright": 1},
    ),
    PublishPlatform.wechat_video: PublishPlatformConfig(
        platform=PublishPlatform.wechat_video,
        publish_url="https://channels.weixin.qq.com",
        title_limit=30,
        tags_limit=5,
    ),
    PublishPlatform.youtube: PublishPlatformConfig(
        platform=PublishPlatform.youtube,
        publish_url="https://studio.youtube.com",
        title_limit=100,
        tags_limit=500,
    ),
}


def get_platform_config(platform: PublishPlatform) -> PublishPlatformConfig:
    return _PLATFORM_CONFIGS[platform]


# ---------------------------------------------------------------------------
# Abstract adapter
# ---------------------------------------------------------------------------

class PlatformAdapter(ABC):
    def __init__(self, config: PublishPlatformConfig):
        self.config = config

    @abstractmethod
    async def upload_video(self, task: PublishTask) -> bool: ...

    @abstractmethod
    async def fill_metadata(self, task: PublishTask) -> bool: ...

    @abstractmethod
    async def submit_publish(self, task: PublishTask) -> Optional[str]: ...

    @abstractmethod
    async def check_status(self, task: PublishTask) -> PublishStatus: ...


# ---------------------------------------------------------------------------
# Concrete adapters (stubs)
# ---------------------------------------------------------------------------

class XiaohongshuAdapter(PlatformAdapter):
    async def upload_video(self, task: PublishTask) -> bool:
        logger.info("[XHS] uploading %s", task.video_path)
        await asyncio.sleep(0)
        return True

    async def fill_metadata(self, task: PublishTask) -> bool:
        logger.info("[XHS] title=%s", task.title[:20])
        await asyncio.sleep(0)
        return True

    async def submit_publish(self, task: PublishTask) -> Optional[str]:
        await asyncio.sleep(0)
        return f"https://www.xiaohongshu.com/explore/{task.id}"

    async def check_status(self, task: PublishTask) -> PublishStatus:
        return PublishStatus.ready_to_publish


class DouyinAdapter(PlatformAdapter):
    async def upload_video(self, task: PublishTask) -> bool:
        await asyncio.sleep(0)
        return True

    async def fill_metadata(self, task: PublishTask) -> bool:
        await asyncio.sleep(0)
        return True

    async def submit_publish(self, task: PublishTask) -> Optional[str]:
        await asyncio.sleep(0)
        return f"https://www.douyin.com/video/{task.id}"

    async def check_status(self, task: PublishTask) -> PublishStatus:
        return PublishStatus.ready_to_publish


class BilibiliAdapter(PlatformAdapter):
    async def upload_video(self, task: PublishTask) -> bool:
        await asyncio.sleep(0)
        return True

    async def fill_metadata(self, task: PublishTask) -> bool:
        await asyncio.sleep(0)
        return True

    async def submit_publish(self, task: PublishTask) -> Optional[str]:
        await asyncio.sleep(0)
        return f"https://www.bilibili.com/video/BV{task.id}"

    async def check_status(self, task: PublishTask) -> PublishStatus:
        return PublishStatus.ready_to_publish


class WechatVideoAdapter(PlatformAdapter):
    async def upload_video(self, task: PublishTask) -> bool:
        await asyncio.sleep(0)
        return True

    async def fill_metadata(self, task: PublishTask) -> bool:
        await asyncio.sleep(0)
        return True

    async def submit_publish(self, task: PublishTask) -> Optional[str]:
        await asyncio.sleep(0)
        return None

    async def check_status(self, task: PublishTask) -> PublishStatus:
        return PublishStatus.ready_to_publish


class YouTubeAdapter(PlatformAdapter):
    async def upload_video(self, task: PublishTask) -> bool:
        await asyncio.sleep(0)
        return True

    async def fill_metadata(self, task: PublishTask) -> bool:
        await asyncio.sleep(0)
        return True

    async def submit_publish(self, task: PublishTask) -> Optional[str]:
        await asyncio.sleep(0)
        return f"https://youtu.be/{task.id}"

    async def check_status(self, task: PublishTask) -> PublishStatus:
        return PublishStatus.ready_to_publish


_ADAPTERS: dict[PublishPlatform, type[PlatformAdapter]] = {
    PublishPlatform.xiaohongshu: XiaohongshuAdapter,
    PublishPlatform.douyin: DouyinAdapter,
    PublishPlatform.bilibili: BilibiliAdapter,
    PublishPlatform.wechat_video: WechatVideoAdapter,
    PublishPlatform.youtube: YouTubeAdapter,
}

# In-memory task store
_tasks: dict[str, PublishTask] = {}


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------

async def validate_platform_credentials(platform: PublishPlatform) -> bool:
    config = get_platform_config(platform)
    if not config.cookies_path:
        return True  # No cookies required for stub
    return True


async def publish_video(task: PublishTask, config: PublishPlatformConfig | None = None) -> PublishTask:
    """发布单个视频。预发布模式: 停在 ready_to_publish。"""
    config = config or get_platform_config(task.platform)
    adapter_cls = _ADAPTERS.get(task.platform)
    if not adapter_cls:
        task.status = PublishStatus.failed
        task.error = f"No adapter for {task.platform.value}"
        return task

    adapter = adapter_cls(config)
    _tasks[task.id] = task

    try:
        task.status = PublishStatus.uploading
        ok = await adapter.upload_video(task)
        if not ok:
            raise RuntimeError("Upload failed")

        task.status = PublishStatus.processing
        ok = await adapter.fill_metadata(task)
        if not ok:
            raise RuntimeError("Metadata fill failed")

        if task.auto_publish:
            url = await adapter.submit_publish(task)
            task.status = PublishStatus.published
            task.published_url = url
        else:
            task.status = PublishStatus.ready_to_publish

    except Exception as exc:
        task.status = PublishStatus.failed
        task.error = str(exc)
        logger.error("Publish failed for %s: %s", task.id, exc)

    return task


async def confirm_publish(task_id: str) -> PublishTask | None:
    task = _tasks.get(task_id)
    if not task:
        return None
    if task.status != PublishStatus.ready_to_publish:
        return task

    config = get_platform_config(task.platform)
    adapter = _ADAPTERS[task.platform](config)
    try:
        url = await adapter.submit_publish(task)
        task.status = PublishStatus.published
        task.published_url = url
    except Exception as exc:
        task.status = PublishStatus.failed
        task.error = str(exc)
    return task


async def publish_batch(request: PublishBatchRequest) -> PublishBatchResult:
    """批量发布 — 并行上传 + 串行元数据。"""
    results: list[PublishTask] = []
    sem = asyncio.Semaphore(request.max_parallel)

    async def _upload_one(task: PublishTask) -> PublishTask:
        async with sem:
            config = get_platform_config(task.platform)
            adapter = _ADAPTERS[task.platform](config)
            task.status = PublishStatus.uploading
            try:
                await adapter.upload_video(task)
            except Exception as e:
                task.status = PublishStatus.failed
                task.error = str(e)
        return task

    upload_results = await asyncio.gather(*[_upload_one(t) for t in request.tasks])

    for task in upload_results:
        if task.status == PublishStatus.failed:
            results.append(task)
            continue
        try:
            config = get_platform_config(task.platform)
            adapter = _ADAPTERS[task.platform](config)
            await adapter.fill_metadata(task)

            if request.auto_publish:
                url = await adapter.submit_publish(task)
                task.status = PublishStatus.published
                task.published_url = url
            else:
                task.status = PublishStatus.ready_to_publish
        except Exception as e:
            task.status = PublishStatus.failed
            task.error = str(e)
        results.append(task)

    succeeded = sum(1 for t in results if t.status in (PublishStatus.published, PublishStatus.ready_to_publish))
    failed = sum(1 for t in results if t.status == PublishStatus.failed)

    return PublishBatchResult(total=len(results), succeeded=succeeded, failed=failed, task_results=results)


async def schedule_publish(task: PublishTask, publish_at: datetime) -> str:
    task.scheduled_at = publish_at
    task.status = PublishStatus.pending
    _tasks[task.id] = task
    logger.info("Scheduled publish for %s at %s", task.id, publish_at.isoformat())
    return task.id
