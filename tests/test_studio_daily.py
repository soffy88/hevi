"""解说 / 历史现场日更排产。"""

from __future__ import annotations

import pytest

from hevi.studio.daily import (
    add_topics,
    list_calendars,
    reset_daily,
    tick,
)


@pytest.fixture(autouse=True)
def _clean() -> None:
    reset_daily()
    yield
    reset_daily()


def test_default_calendars_exist() -> None:
    ids = {c.calendar_id for c in list_calendars()}
    assert ids == {"explainer-daily", "history-scene-daily"}


@pytest.mark.asyncio
async def test_tick_fires_one_topic_per_calendar() -> None:
    add_topics(
        "explainer-daily",
        [{"title": "盐税是什么", "scheduled_date": "2026-08-18"}],
    )
    add_topics(
        "history-scene-daily",
        [
            {
                "title": "三家分晋",
                "source_text": "智伯请地于韩康子。",
                "scheduled_date": "2026-08-18",
            }
        ],
    )
    jobs = await tick(now="2026-08-18", publish=True)
    assert len(jobs) == 2
    lines = {j.line_id for j in jobs}
    assert lines == {"explainer", "history_scene"}
    expl = next(j for j in jobs if j.line_id == "explainer")
    assert expl.status == "scheduled"
    assert expl.publish and expl.publish[0]["status"] == "queued"

    again = await tick(now="2026-08-18")
    assert again == []
