"""v9.1 基建:TaskRun —— 任务大盘的关系型核心模型(SQLModel)。

替代旧的 state.json 单文件状态管理。每个工单一行:
  * ``task_id``:工单唯一标识(与沙盒目录 data/workspace/{task_id}/ 同名)
  * ``pipeline_type``:区分主管道 ``main_remotion`` 与 Lite 管道 ``lite_html``
  * ``status`` / ``progress``:顶层流转状态,WebSocket 实时推流的主干字段
  * ``state_json``:颗粒度状态机(tts_status/asr_status/render_status 等),存
    步骤级断点,重试时跳过已完成步骤,绝不重复消耗算力与 API 额度
  * ``error_log``:崩溃原因,失败重试/大盘排障直接可读
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class TaskRun(SQLModel, table=True):
    """一张工单 = 一行;workspace 目录与 DB 行一一对应。"""

    id: int | None = Field(default=None, primary_key=True)
    task_id: str = Field(index=True, unique=True, max_length=128)
    pipeline_type: str = Field(default="main_remotion", max_length=32)
    status: str = Field(default="pending", max_length=32, index=True)
    progress: int = Field(default=0, ge=0, le=100)
    error_log: str | None = Field(default=None, max_length=4000)
    # 颗粒度状态机:{"tts_status": "done", "asr_status": "done", ...}
    state_json: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, default=dict)
    )
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


__all__ = ["TaskRun"]
