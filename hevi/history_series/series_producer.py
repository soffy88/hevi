"""history_series.series_producer —— 每日自动产线核心(P2)。

按教材课节序连载产片; 游标 = TaskRun 中已完成的最大课序号 + 1;
幂等防重复(同课已产 completed 跳过); 失败课节次日补产(不开天窗)。

每日自动调度: cron → POST /api/history-series/produce-daily，或直接调
produce_next_lesson()。系列元数据: source_name / lesson_order / tb_id
全部进 TaskRun.state_json，dashboard 可直接看。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

TB_ID = "TONGBIAN-G7-HISTORY-S"               # 中国历史七上（P1 已入库 21 课）
SERIES_TITLE = "历史现场·中国历史七年级上册"   # 片头
PIPELINE_TYPE = "history_series"

# 每课默认目标时长(秒)
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
    """下一个待产课节: 已完成最大课序 + 1，无则第 1 课。"""
    import os

    import asyncpg

    db_url = os.environ.get(
        "MNEME_DATABASE_URL",
        "postgresql://postgres:WmFJJAEtVFknjCDwNmi9bu45cK3mwi4@localhost:5433/mneme",
    )
    conn = await asyncpg.connect(db_url)
    try:
        # 查教材课节列表
        rows = await conn.fetch(
            """
            SELECT display_order, name,
                   (SELECT COUNT(*) FROM knowledge_units ku
                    WHERE ku.cluster_id = kc.id) AS ku_cnt
            FROM knowledge_clusters kc
            WHERE textbook_id = $1
            ORDER BY display_order
            """,
            tb_id,
        )
    finally:
        await conn.close()

    if not rows:
        return None

    # 读取 hevi 侧 DB 游标: 已完成的最大课序号
    from sqlmodel import Session, select

    from hevi.core.db import engine
    from hevi.core.models import TaskRun

    produced: set[int] = set()
    with Session(engine) as s:
        runs = s.exec(
            select(TaskRun)
            .where(TaskRun.pipeline_type == PIPELINE_TYPE)
            .where(TaskRun.status == "completed")
        ).all()
        for r in runs:
            order = (r.state_json or {}).get("lesson_order")
            if order is not None:
                produced.add(int(order))

    for r in rows:
        order = int(r["display_order"])
        if order not in produced:
            return LessonInfo(order=order, title=str(r["name"]), ku_count=int(r["ku_cnt"] or 0))
    return None  # 全册已产完


async def produce_lesson(
    lesson: LessonInfo,
    *,
    tb_id: str = TB_ID,
    target_duration_s: int = DEFAULT_DURATION_S,
    aspect_ratio: str = "16:9",
    llm_layers: dict[str, str] | None = None,
) -> tuple[str, dict[str, Any]]:
    """生产一课: 组装 RunRequest → 建 TaskRun → 提交 tongjian run（异步后台）。

    返回 (task_id, run_request) 供前端轮询。幂等: 同课已有 completed TaskRun
    则跳过并返回已有 task_id。
    """
    from sqlmodel import Session, select

    from hevi.core.db import engine
    from hevi.core.models import TaskRun

    # 幂等检查
    with Session(engine) as s:
        existing = s.exec(
            select(TaskRun)
            .where(TaskRun.pipeline_type == PIPELINE_TYPE)
            .where(TaskRun.status == "completed")
        ).all()
        for r in existing:
            if (r.state_json or {}).get("lesson_order") == lesson.order:
                logger.info("课节 %d 已产(%s), 跳过", lesson.order, r.task_id)
                return r.task_id, {}

    # 组装 RunRequest（教材主述 + 古籍并陈）
    from hevi.history_series.textbook_bridge import assemble_textbook_run_request

    req = await assemble_textbook_run_request(
        lesson.title, tb_id, lesson.order,
        textbook_text="",  # 让 bridge 从 mneme 拉取
        target_duration_sec=target_duration_s,
        aspect_ratio=aspect_ratio,
    )
    # LLM 层: 生产用 opencode（已验证比本地 qwen 稳）
    llm = llm_layers or {"L0": "opencode", "L1": "opencode", "L2": "opencode"}
    for layer, model in llm.items():
        req.setdefault("layer_config", {}).setdefault(layer, {})["model"] = model

    # 创建 TaskRun
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

    # 异步提交 tongjian run（后台任务；需 auth token——由 API 层处理）
    return task_id, req


async def produce_next(tb_id: str = TB_ID, **kw: Any) -> dict[str, Any] | None:
    """自动产下一课: next_lesson → produce_lesson。全册产完返回 None。"""
    lesson = await next_lesson(tb_id)
    if lesson is None:
        return None
    task_id, req = await produce_lesson(lesson, tb_id=tb_id, **kw)
    return {"task_id": task_id, "lesson_order": lesson.order,
            "lesson_title": lesson.title, "next": True, "run_request": req}


async def series_queue(tb_id: str = TB_ID) -> list[dict[str, Any]]:
    """系列连载队列: 所有课节 + 生产状态。"""
    rows = []
    # 读 mneme 课节列表
    import os

    import asyncpg

    db_url = os.environ.get(
        "MNEME_DATABASE_URL",
        "postgresql://postgres:WmFJJAEtVFknjCDwNmi9bu45cK3mwi4@localhost:5433/mneme",
    )
    conn = await asyncpg.connect(db_url)
    try:
        mneme_rows = await conn.fetch(
            """
            SELECT display_order, name FROM knowledge_clusters
            WHERE textbook_id = $1 ORDER BY display_order
            """,
            tb_id,
        )
    finally:
        await conn.close()

    # 读 hevi 生产状态
    from sqlmodel import Session, select

    from hevi.core.db import engine
    from hevi.core.models import TaskRun

    with Session(engine) as s:
        runs = s.exec(
            select(TaskRun).where(TaskRun.pipeline_type == PIPELINE_TYPE)
        ).all()
    status_map: dict[int, dict] = {}
    for r in runs:
        order = (r.state_json or {}).get("lesson_order")
        if order is not None:
            status_map[int(order)] = {
                "task_id": r.task_id, "status": r.status,
                "progress": r.progress, "error": r.error_log or "",
            }

    for r in mneme_rows:
        order = int(r["display_order"])
        status = status_map.get(order, {})
        rows.append({
            "lesson_order": order, "title": r["name"],
            "status": status.get("status", "pending"),
            "task_id": status.get("task_id"),
            "progress": status.get("progress", 0),
            "error": status.get("error", ""),
        })
    return rows


__all__ = [
    "PIPELINE_TYPE",
    "TB_ID",
    "LessonInfo",
    "next_lesson",
    "produce_lesson",
    "produce_next",
    "series_queue",
]
