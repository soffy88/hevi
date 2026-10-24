"""v9.1 WebSocket —— 任务大盘实时进度推流 + ping/pong 保活。

客户端连 ``/api/ws/tasks`` 后:后端任何一步进度变化经
``ConnectionManager.broadcast_task_update`` 推送 ``task_update`` JSON;
``ping`` → ``pong`` 保活心跳。
"""

from __future__ import annotations

import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from hevi.auth.jwt_handler import decode_access_token

from hevi.core.ws_manager import connection_manager

router = APIRouter(prefix="/api/ws", tags=["ws"])


@router.websocket("/tasks")
async def task_socket(websocket: WebSocket) -> None:
    """任务大盘推送通道:心跳 ping/pong + 断线自动摘除。"""
    # G10: token check before accept (browser WebSocket cannot send an
    # Authorization header, so ?token= query param, same shape as the tasks
    # media token-query-param endpoints). No token / invalid / no sub -> 1008
    # close without accept.
    _token = websocket.query_params.get("token")
    try:
        _sub = (decode_access_token(_token) or {}).get("sub") if _token else None
    except Exception:
        _sub = None
    if not _sub:
        await websocket.close(code=1008)
        return
    await connection_manager.connect(websocket)
    try:
        while True:
            message = await websocket.receive_text()
            if message == "ping":
                await websocket.send_text("pong")
            elif message == "close":
                break
            else:
                try:
                    command = json.loads(message)
                except json.JSONDecodeError:
                    continue
                if command.get("type") == "subscribe":
                    resource_ids = {
                        str(item)
                        for item in command.get("resource_ids", command.get("task_ids", []))
                        if item
                    }
                    await connection_manager.set_subscription(websocket, resource_ids)
                    await websocket.send_json(
                        {"type": "subscribed", "resource_ids": sorted(resource_ids)}
                    )
    except WebSocketDisconnect:
        pass
    finally:
        await connection_manager.disconnect(websocket)


__all__ = ["router"]
