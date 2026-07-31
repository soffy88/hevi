"""直播排班调度器 — 定时开播/下播。"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

__all__ = ["LiveStreamSchedule", "StreamScheduler"]


class LiveStreamSchedule(BaseModel):
    id: str = ""
    stream_request_id: str = ""
    start_at: datetime = Field(default_factory=datetime.utcnow)
    end_at: Optional[datetime] = None
    repeat: str = "once"  # once, daily, weekdays
    enabled: bool = True
    title: str = ""


class StreamScheduler:
    """直播排班调度器。"""

    def __init__(self, poll_interval: float = 30.0):
        self._schedules: dict[str, LiveStreamSchedule] = {}
        self._poll_interval = poll_interval
        self._running = False

    def add_schedule(self, schedule: LiveStreamSchedule) -> str:
        import uuid
        if not schedule.id:
            schedule.id = uuid.uuid4().hex[:8]
        self._schedules[schedule.id] = schedule
        logger.info("Scheduled stream %s at %s", schedule.id, schedule.start_at.isoformat())
        return schedule.id

    def remove_schedule(self, schedule_id: str) -> bool:
        return self._schedules.pop(schedule_id, None) is not None

    def get_schedules(self) -> list[LiveStreamSchedule]:
        return list(self._schedules.values())

    async def run(self) -> None:
        self._running = True
        logger.info("Stream scheduler started")
        while self._running:
            now = datetime.utcnow()
            for schedule in list(self._schedules.values()):
                if not schedule.enabled:
                    continue
                if schedule.start_at <= now:
                    logger.info("Firing scheduled stream %s", schedule.id)
                    # In production: call start_livestream()
                    if schedule.repeat == "once":
                        schedule.enabled = False
                    elif schedule.repeat == "daily":
                        schedule.start_at += timedelta(days=1)
                    elif schedule.repeat == "weekdays":
                        schedule.start_at += timedelta(days=1)
                        # Skip weekends
                        while schedule.start_at.weekday() >= 5:
                            schedule.start_at += timedelta(days=1)
            await asyncio.sleep(self._poll_interval)

    def stop(self) -> None:
        self._running = False
