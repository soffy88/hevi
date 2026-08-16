"""series_producer —— 每日自动产线核心 (P2)。"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

TB_ID = "TONGBIAN-G7-HISTORY-S"
SERIES_TITLE = "历史现场·中国历史七年级上册"
PIPELINE_TYPE = "history_series"
DEFAULT_DURATION_S = 120


@dataclass
class LessonInfo:
    order: int
    title: str = ""
    ku_count: int = 0

    @property
    def source_name(self) -> str:
        return f"{SERIES_TITLE}·第{self.order}课·{self.title}"


async def next_lesson(tb_id: str = TB_ID) -> LessonInfo | None:
    import os

    import asyncpg

    db_url = os.environ.get(
        "MNEME_DATABASE_URL",
        "postgresql://postgres:WmFJJAEtVFknjCDwNmi9bu45cK3mwi4@localhost:5433/mneme",
    )
    conn = await asyncpg.connect(db_url)
    try:
        rows = await conn.fetch(
            """SELECT display_order, name, (SELECT COUNT(*) FROM knowledge_units ku
            WHERE ku.cluster_id = kc.id) AS ku_cnt FROM knowledge_clusters kc
            WHERE textbook_id=$1 ORDER BY display_order""",
            tb_id,
        )
    finally:
        await conn.close()
    if not rows:
        return None
    from sqlmodel import Session, select

    from hevi.core.db import engine
    from hevi.core.models import TaskRun

    produced: set[int] = set()
    with Session(engine) as s:
        for r in s.exec(
            select(TaskRun)
            .where(TaskRun.pipeline_type == PIPELINE_TYPE)
            .where(TaskRun.status == "completed")
        ).all():
            o = (r.state_json or {}).get("lesson_order")
            if o is not None:
                produced.add(int(o))
    for r in rows:
        order = int(r["display_order"])
        if order not in produced:
            return LessonInfo(
                order=order, title=str(r["name"]), ku_count=int(r["ku_cnt"] or 0)
            )
    return None


async def produce_lesson(
    lesson: LessonInfo,
    *,
    tb_id: str = TB_ID,
    target_duration_s: int = DEFAULT_DURATION_S,
    aspect_ratio: str = "16:9",
    llm_layers: dict[str, str] | None = None,
) -> tuple[str, dict[str, Any]]:
    from sqlmodel import Session, select

    from hevi.core.db import engine
    from hevi.core.models import TaskRun

    with Session(engine) as s:
        for r in s.exec(
            select(TaskRun)
            .where(TaskRun.pipeline_type == PIPELINE_TYPE)
            .where(TaskRun.status == "completed")
        ).all():
            if (r.state_json or {}).get("lesson_order") == lesson.order:
                logger.info("课节 %d 已产(%s), 跳过", lesson.order, r.task_id)
                return r.task_id, {}
    from hevi.history_series.textbook_bridge import assemble_textbook_run_request

    req = await assemble_textbook_run_request(
        lesson.title,
        tb_id,
        lesson.order,
        target_duration_sec=target_duration_s,
        aspect_ratio=aspect_ratio,
    )
    llm = llm_layers or {"L0": "opencode", "L1": "opencode", "L2": "opencode"}
    for layer, model in llm.items():
        req.setdefault("layer_config", {}).setdefault(layer, {})["model"] = model
    from hevi.core.workspace import new_task_id

    task_id = new_task_id()
    run_row = TaskRun(
        task_id=task_id,
        pipeline_type=PIPELINE_TYPE,
        status="pending",
        progress=0,
        state_json={
            "lesson_order": lesson.order,
            "lesson_title": lesson.title,
            "tb_id": tb_id,
            "series": SERIES_TITLE,
            "source_name": req.get("source_name"),
        },
    )
    with Session(engine) as s:
        s.add(run_row)
        s.commit()
    return task_id, req


async def produce_next(tb_id: str = TB_ID, **kw: Any) -> dict[str, Any] | None:
    lesson = await next_lesson(tb_id)
    if lesson is None:
        return None
    task_id, req = await produce_lesson(lesson, tb_id=tb_id, **kw)
    return {
        "task_id": task_id,
        "lesson_order": lesson.order,
        "lesson_title": lesson.title,
        "next": True,
        "run_request": req,
    }


async def series_queue(tb_id: str = TB_ID) -> list[dict[str, Any]]:
    import os

    import asyncpg

    db_url = os.environ.get(
        "MNEME_DATABASE_URL",
        "postgresql://postgres:WmFJJAEtVFknjCDwNmi9bu45cK3mwi4@localhost:5433/mneme",
    )
    conn = await asyncpg.connect(db_url)
    try:
        rows = await conn.fetch(
            """SELECT display_order, name FROM knowledge_clusters
            WHERE textbook_id=$1 ORDER BY display_order""",
            tb_id,
        )
    finally:
        await conn.close()
    from sqlmodel import Session, select

    from hevi.core.db import engine
    from hevi.core.models import TaskRun

    with Session(engine) as s:
        runs = s.exec(
            select(TaskRun).where(TaskRun.pipeline_type == PIPELINE_TYPE)
        ).all()
    sm: dict[int, dict[str, Any]] = {}
    for r in runs:
        o = (r.state_json or {}).get("lesson_order")
        if o is not None:
            sm[int(o)] = {
                "task_id": r.task_id,
                "status": r.status,
                "progress": r.progress,
                "error": r.error_log or "",
            }
    return [
        {
            "lesson_order": int(r["display_order"]),
            "title": r["name"],
            "status": sm.get(int(r["display_order"]), {}).get("status", "pending"),
            "task_id": sm.get(int(r["display_order"]), {}).get("task_id"),
            "progress": sm.get(int(r["display_order"]), {}).get("progress", 0),
            "error": sm.get(int(r["display_order"]), {}).get("error", ""),
        }
        for r in rows
    ]
