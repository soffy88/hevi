"""v9.1 WebSocket —— 任务大盘实时进度推流 + ping/pong 保活。

客户端连 ``/api/ws/tasks`` 后:后端任何一步进度变化经
``ConnectionManager.broadcast_task_update`` 推送 ``task_update`` JSON;
``ping`` → ``pong`` 保活心跳。
"""

from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from hevi.core.ws_manager import connection_manager

router = APIRouter(prefix="/api/ws", tags=["ws"])


@router.websocket("/tasks")
async def task_socket(websocket: WebSocket) -> None:
    """任务大盘推送通道:心跳 ping/pong + 断线自动摘除。"""
    await connection_manager.connect(websocket)
    try:
        while True:
            message = await websocket.receive_text()
            if message == "ping":
                await websocket.send_text("pong")
            elif message == "close":
                break
    except WebSocketDisconnect:
        pass
    finally:
        await connection_manager.disconnect(websocket)


__all__ = ["router"]
