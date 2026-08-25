"""series_producer —— 每日自动产线核心 (P2)。"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any

from obase.persistence import PgPool

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


async def _produced_orders(pool: PgPool | None = None) -> set[int]:
    if pool is not None:
        from hevi.tasks.repository import TaskRepository

        tasks = await TaskRepository(pool).list_tasks(limit=1000)
        produced: set[int] = set()
        for task in tasks:
            if task.get("status") != "completed":
                continue
            config = task.get("config_json") or {}
            request = config.get("request") or {}
            order = config.get("lesson_order") or request.get("lesson_order")
            if order is not None:
                produced.add(int(order))
        return produced

    from sqlmodel import Session, select

    from hevi.core.db import engine
    from hevi.core.models import TaskRun

    with Session(engine) as s:
        return {
            int((row.state_json or {}).get("lesson_order") or 0)
            for row in s.exec(
                select(TaskRun)
                .where(TaskRun.pipeline_type == PIPELINE_TYPE)
                .where(TaskRun.status == "completed")
            ).all()
            if (row.state_json or {}).get("lesson_order") is not None
        }


async def _existing_produced_task_id(
    lesson_order: int, pool: PgPool | None = None
) -> str | None:
    """Return the durable task identity for an already-produced lesson.

    Idempotent callers must receive the original task id.  Generating a new
    id for an already completed lesson makes retries look like duplicate
    production requests and breaks the series queue's canonical identity.
    """
    if pool is not None:
        from hevi.tasks.repository import TaskRepository

        tasks = await TaskRepository(pool).list_tasks(limit=1000)
        for task in tasks:
            if task.get("status") != "completed":
                continue
            config = task.get("config_json") or {}
            request = config.get("request") or {}
            order = config.get("lesson_order") or request.get("lesson_order")
            if order is not None and int(order) == lesson_order:
                return str(task.get("id") or task.get("task_id"))
        return None

    from sqlmodel import Session, select

    from hevi.core.db import engine
    from hevi.core.models import TaskRun

    with Session(engine) as s:
        rows = s.exec(
            select(TaskRun)
            .where(TaskRun.pipeline_type == PIPELINE_TYPE)
            .where(TaskRun.status == "completed")
        ).all()
    for row in rows:
        if int((row.state_json or {}).get("lesson_order", -1)) == lesson_order:
            return str(row.task_id)
    return None


async def next_lesson(tb_id: str = TB_ID, pool: PgPool | None = None) -> LessonInfo | None:
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
    produced = await _produced_orders(pool)
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
    pool: PgPool | None = None,
) -> tuple[str, dict[str, Any]]:
    if lesson.order in await _produced_orders(pool):
        logger.info("课节 %d 已产,跳过", lesson.order)
        existing_task_id = await _existing_produced_task_id(lesson.order, pool)
        return existing_task_id or str(uuid.uuid4()), {}
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
    req["lesson_order"] = lesson.order
    req["tb_id"] = tb_id
    from hevi.core.workspace import new_task_id

    task_id = new_task_id()
    if pool is not None:
        # The authenticated history route submits this request directly to the
        # canonical Tongjian run endpoint.  No SQLite placeholder is created.
        return task_id, req

    from sqlmodel import Session

    from hevi.core.db import engine
    from hevi.core.models import TaskRun

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
    pool = kw.pop("pool", None)
    lesson = await next_lesson(tb_id, pool=pool)
    if lesson is None:
        return None
    task_id, req = await produce_lesson(lesson, tb_id=tb_id, pool=pool, **kw)
    return {
        "task_id": task_id,
        "lesson_order": lesson.order,
        "lesson_title": lesson.title,
        "next": True,
        "run_request": req,
    }


async def series_queue(tb_id: str = TB_ID, pool: PgPool | None = None) -> list[dict[str, Any]]:
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
    sm: dict[int, dict[str, Any]] = {}
    runs: list[Any]
    if pool is not None:
        from hevi.tasks.repository import TaskRepository

        runs = await TaskRepository(pool).list_tasks(limit=1000)
    else:
        from sqlmodel import Session, select

        from hevi.core.db import engine
        from hevi.core.models import TaskRun

        with Session(engine) as s:
            runs = list(s.exec(select(TaskRun).where(TaskRun.pipeline_type == PIPELINE_TYPE)).all())
    for r in runs:
        raw_config = r.get("config_json") if isinstance(r, dict) else (r.state_json or {})
        config = raw_config if isinstance(raw_config, dict) else {}
        o = config.get("lesson_order") or (config.get("request") or {}).get("lesson_order")
        if o is not None:
            sm[int(o)] = {
                "task_id": str(r["id"]) if isinstance(r, dict) else r.task_id,
                "status": r.get("status") if isinstance(r, dict) else r.status,
                "progress": r.get("progress_pct", 0) if isinstance(r, dict) else r.progress,
                "error": (r.get("error") or "") if isinstance(r, dict) else (r.error_log or ""),
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
