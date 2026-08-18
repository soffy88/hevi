"""日更排产 —— 解说线按系列选题、历史现场按史料选题,每日一条并写发布交接单。

不重开管线:选题进已有 `explainer` / `history_scene` 配方,出片交接既有产品线,
发布走 `publish.matrix`。历史现场教科书连载仍可由 `/history-series/produce-daily`
走通鉴;本层给「选题日历」和 Veya/cron 同一把 tick。
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from hevi.studio.slate import Slate, run_slate

_CALS: dict[str, DailyCalendar] = {}
_JOBS: dict[str, DailyJob] = {}

DEFAULT_LINES = ("explainer", "history_scene")


@dataclass
class TopicItem:
    topic_id: str
    line_id: str
    title: str
    slots: dict[str, Any] = field(default_factory=dict)
    scheduled_date: str | None = None
    produced_job_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DailyCalendar:
    calendar_id: str
    name: str
    line_id: str
    platforms: list[str] = field(default_factory=list)
    topics: list[TopicItem] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "calendar_id": self.calendar_id,
            "name": self.name,
            "line_id": self.line_id,
            "platforms": list(self.platforms),
            "topics": [t.to_dict() for t in self.topics],
            "remaining": sum(1 for t in self.topics if not t.produced_job_id),
        }


@dataclass
class DailyJob:
    job_id: str
    calendar_id: str
    line_id: str
    topic_id: str
    date: str
    status: str
    title: str = ""
    slate: dict[str, Any] = field(default_factory=dict)
    publish: list[dict[str, Any]] = field(default_factory=list)
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def reset_daily() -> None:
    _CALS.clear()
    _JOBS.clear()


def ensure_default_calendars() -> None:
    if "explainer-daily" not in _CALS:
        _CALS["explainer-daily"] = DailyCalendar(
            calendar_id="explainer-daily",
            name="解说日更",
            line_id="explainer",
            platforms=["douyin", "bilibili"],
        )
    if "history-scene-daily" not in _CALS:
        _CALS["history-scene-daily"] = DailyCalendar(
            calendar_id="history-scene-daily",
            name="历史现场日更",
            line_id="history_scene",
            platforms=["bilibili", "shipinhao"],
        )


def upsert_calendar(
    *,
    calendar_id: str,
    name: str,
    line_id: str,
    platforms: list[str] | None = None,
) -> DailyCalendar:
    if line_id not in DEFAULT_LINES:
        raise ValueError(f"daily line must be one of {DEFAULT_LINES}")
    cal = DailyCalendar(
        calendar_id=calendar_id,
        name=name,
        line_id=line_id,
        platforms=list(platforms or []),
    )
    existing = _CALS.get(calendar_id)
    if existing:
        cal.topics = existing.topics
    _CALS[calendar_id] = cal
    return cal


def get_calendar(calendar_id: str) -> DailyCalendar | None:
    ensure_default_calendars()
    return _CALS.get(calendar_id)


def list_calendars() -> list[DailyCalendar]:
    ensure_default_calendars()
    return list(_CALS.values())


def add_topics(calendar_id: str, items: list[dict[str, Any]]) -> DailyCalendar:
    cal = get_calendar(calendar_id)
    if cal is None:
        raise KeyError(calendar_id)
    for raw in items:
        title = str(raw.get("title") or raw.get("topic") or "").strip()
        if not title:
            continue
        slots = dict(raw.get("slots") or {})
        if cal.line_id == "explainer":
            slots.setdefault("topic", title)
        elif cal.line_id == "history_scene":
            slots.setdefault("source_name", title)
            slots.setdefault("source_text", str(raw.get("source_text") or title))
        cal.topics.append(
            TopicItem(
                topic_id=str(raw.get("topic_id") or uuid.uuid4()),
                line_id=cal.line_id,
                title=title,
                slots=slots,
                scheduled_date=raw.get("scheduled_date"),
            )
        )
    return cal


def list_jobs(*, calendar_id: str | None = None) -> list[DailyJob]:
    jobs = list(_JOBS.values())
    if calendar_id:
        jobs = [j for j in jobs if j.calendar_id == calendar_id]
    return jobs


def _today(now: date | str | None) -> str:
    if isinstance(now, str) and now:
        return now[:10]
    if isinstance(now, date):
        return now.isoformat()
    return datetime.now(UTC).date().isoformat()


def _pick(cal: DailyCalendar, day: str) -> TopicItem | None:
    for topic in cal.topics:
        if topic.produced_job_id:
            continue
        if topic.scheduled_date and topic.scheduled_date > day:
            continue
        return topic
    return None


async def _publish(platforms: list[str], media: str, title: str) -> list[dict[str, Any]]:
    from hevi.studio.tools import invoke_tool

    results: list[dict[str, Any]] = []
    for platform in platforms:
        res = await invoke_tool(
            "publish.matrix",
            {"platform": platform, "media_path": media, "title": title},
        )
        results.append(res.to_dict())
    return results


async def tick(
    *,
    now: date | str | None = None,
    calendar_id: str | None = None,
    publish: bool = True,
) -> list[DailyJob]:
    """每个日历至多排一条到期选题。"""
    ensure_default_calendars()
    day = _today(now)
    cals = [get_calendar(calendar_id)] if calendar_id else list_calendars()
    fired: list[DailyJob] = []
    for cal in cals:
        if cal is None:
            continue
        topic = _pick(cal, day)
        if topic is None:
            continue
        slate = await run_slate(Slate(line_id=cal.line_id, slots=dict(topic.slots)))
        job = DailyJob(
            job_id=str(uuid.uuid4()),
            calendar_id=cal.calendar_id,
            line_id=cal.line_id,
            topic_id=topic.topic_id,
            date=day,
            status=slate.status,
            title=topic.title,
            slate=slate.to_dict(),
            reason=slate.reason,
        )
        media = ""
        plan = slate.data.get("edit_plan") if isinstance(slate.data, dict) else None
        if isinstance(plan, dict):
            media = str(plan.get("preview_path") or "")
        if publish and cal.platforms and media:
            job.publish = await _publish(cal.platforms, media, topic.title)
        elif publish and cal.platforms:
            job.publish = [
                {
                    "status": "queued",
                    "platform": p,
                    "reason": "waiting-delivery",
                    "title": topic.title,
                }
                for p in cal.platforms
            ]
        topic.produced_job_id = job.job_id
        _JOBS[job.job_id] = job
        fired.append(job)
    return fired
