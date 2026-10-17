"""长任务取消机制。

对标 Jellyfish 的统一任务取消能力:
- 任务可从 pending/queued/running 状态被取消
- 取消后:pending/queued 任务直接标记 cancelled;running 任务发送取消信号
- asyncio.Task 追踪:通过 task_id 找到对应的 asyncio.Task 并 cancel()

集成方式:
- TaskService 维护 _running_tasks: dict[uuid, asyncio.Task]
- 创建任务时注册,完成/失败时移除
- cancel_task() 查找并取消对应的 asyncio.Task
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

logger = logging.getLogger(__name__)

# 全局运行任务追踪表(同 shortdrama._RUN_TASKS 模式)
_running_tasks: dict[uuid.UUID, asyncio.Task[Any]] = {}


def register_running_task(task_id: uuid.UUID, aio_task: asyncio.Task[Any]) -> None:
    """注册一个正在运行的 asyncio.Task。"""
    _running_tasks[task_id] = aio_task

    def _cleanup(t: asyncio.Task[Any]) -> None:
        _running_tasks.pop(task_id, None)

    aio_task.add_done_callback(_cleanup)


def unregister_running_task(task_id: uuid.UUID) -> None:
    """移除已完成的 asyncio.Task。"""
    _running_tasks.pop(task_id, None)


def get_running_task(task_id: uuid.UUID) -> asyncio.Task[Any] | None:
    """获取正在运行的 asyncio.Task。"""
    return _running_tasks.get(task_id)


def cancel_running_task(task_id: uuid.UUID) -> bool:
    """取消正在运行的 asyncio.Task。

    Returns:
        True 如果成功取消, False 如果任务不存在或已完成
    """
    aio_task = _running_tasks.get(task_id)
    if aio_task is None:
        logger.warning("Task %s not found in running tasks", task_id)
        return False

    if aio_task.done():
        logger.info("Task %s already done", task_id)
        _running_tasks.pop(task_id, None)
        return False

    aio_task.cancel()
    logger.info("Cancelled asyncio.Task for task %s", task_id)
    return True


def get_running_task_ids() -> list[uuid.UUID]:
    """获取所有正在运行的任务 ID。"""
    return [tid for tid, t in _running_tasks.items() if not t.done()]


def is_task_running(task_id: uuid.UUID) -> bool:
    """检查任务是否正在运行。"""
    t = _running_tasks.get(task_id)
    return t is not None and not t.done()
