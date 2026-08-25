"""v9.1 基建:全局 WebSocket 连接管理器(单例)。

管理所有活跃的任务大盘客户端连接。后端任何一步(oprim/omodul)通过
``WorkspaceManager`` 更新进度时,都会同步调用 ``broadcast_task_update``,
把任务状态瞬间穿透到所有已连接前端 —— 无需刷新页面即可看到进度条丝滑上涨。

线程安全:FastAPI 的 WebSocket 处理器与后台任务可能跑在不同线程/事件循环,
这里用 asyncio.Lock 保护连接列表;广播失败(客户端掉线)自动静默摘除,绝不
让推流异常反噬生产任务本身。
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)


@dataclass
class _Connection:
    websocket: WebSocket
    resource_ids: set[str] = field(default_factory=set)


class ConnectionManager:
    """连接层；权威事件来自 outbox/event consumer,不来自此进程内存。"""

    def __init__(self) -> None:
        self._connections: list[_Connection] = []
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, resource_ids: set[str] | None = None) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections.append(_Connection(websocket, set(resource_ids or set())))

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._connections = [
                item for item in self._connections if item.websocket is not websocket
            ]

    async def set_subscription(self, websocket: WebSocket, resource_ids: set[str]) -> None:
        async with self._lock:
            for item in self._connections:
                if item.websocket is websocket:
                    item.resource_ids = set(resource_ids)
                    break

    async def broadcast_event(
        self, event: dict[str, Any], *, resource_id: str | None = None
    ) -> None:
        """Broadcast a canonical event to interested connections only."""

        payload = json.dumps(event, ensure_ascii=False, default=str)
        async with self._lock:
            alive: list[_Connection] = []
            for item in self._connections:
                if item.resource_ids and resource_id and resource_id not in item.resource_ids:
                    alive.append(item)
                    continue
                try:
                    await item.websocket.send_text(payload)
                    alive.append(item)
                except Exception:  # client disconnected: remove without affecting producers
                    logger.debug("ws client dropped during event broadcast: %s", item.websocket)
            self._connections = alive

    async def broadcast_task_update(
        self, task_id: str, status: str, progress: int, **extra: object
    ) -> None:
        """向所有活跃连接推送任务状态 JSON。掉线/异常连接静默摘除。"""
        payload = json.dumps(
            {
                "type": "task_update",
                "task_id": task_id,
                "status": status,
                "progress": progress,
                **extra,
            },
            ensure_ascii=False,
        )
        await self.broadcast_event(
            json.loads(payload),
            resource_id=task_id,
        )

    @property
    def connection_count(self) -> int:
        return len(self._connections)


# 进程级单例:整个后端共享一个连接池。
connection_manager = ConnectionManager()

__all__ = ["ConnectionManager", "connection_manager"]
