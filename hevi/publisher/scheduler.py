"""发布调度器 — 定时发布 + 状态追踪。"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Optional

from hevi.publisher.publisher_service import (
    PublishStatus,
    PublishTask,
    publish_video,
)

logger = logging.getLogger(__name__)

__all__ = ["PublishScheduler"]


class PublishScheduler:
    """有状态发布调度器。"""

    def __init__(self, poll_interval: float = 10.0):
        self._queue: dict[str, PublishTask] = {}
        self._poll_interval = poll_interval
        self._running = False

    def add(self, task: PublishTask, publish_at: datetime) -> str:
        task.scheduled_at = publish_at
        task.status = PublishStatus.pending
        self._queue[task.id] = task
        logger.info("Scheduled task %s at %s", task.id, publish_at.isoformat())
        return task.id

    def cancel(self, task_id: str) -> bool:
        task = self._queue.pop(task_id, None)
        if task:
            task.status = PublishStatus.cancelled
            logger.info("Cancelled scheduled task %s", task_id)
            return True
        return False

    def get_pending(self) -> list[PublishTask]:
        return [t for t in self._queue.values() if t.status == PublishStatus.pending]

    def get_all(self) -> list[PublishTask]:
        return list(self._queue.values())

    def snapshot(self) -> dict:
        now = datetime.utcnow()
        return {
            "total": len(self._queue),
            "pending": sum(1 for t in self._queue.values() if t.status == PublishStatus.pending),
            "ready": sum(1 for t in self._queue.values() if t.status == PublishStatus.ready_to_publish),
            "published": sum(1 for t in self._queue.values() if t.status == PublishStatus.published),
            "failed": sum(1 for t in self._queue.values() if t.status == PublishStatus.failed),
        }

    async def run(self) -> None:
        self._running = True
        logger.info("Publish scheduler started (poll_interval=%.1fs)", self._poll_interval)
        while self._running:
            now = datetime.utcnow()
            due = [
                t for t in self._queue.values()
                if t.status == PublishStatus.pending
                and t.scheduled_at
                and t.scheduled_at <= now
            ]
            for task in due:
                logger.info("Firing scheduled task %s for %s", task.id, task.platform.value)
                task.auto_publish = True
                try:
                    await publish_video(task)
                except Exception as e:
                    logger.error("Scheduled publish failed for %s: %s", task.id, e)
            await asyncio.sleep(self._poll_interval)

    def stop(self) -> None:
        self._running = False
        logger.info("Publish scheduler stopped")
