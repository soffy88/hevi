"""v9.1 基建:WebSocket 实时进度路由。

``ws://<host>/api/ws/tasks`` —— 前端任务大盘的长连接入口。

生命周期:
  * 连接建立后登记进全局 ConnectionManager;
  * 服务端随时推送 {"type":"task_update","task_id","status","progress",...};
  * 客户端发 "ping" 心跳 → 服务端回 "pong",保持长连接不被代理/网关掐断。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from hevi.core.ws_manager import connection_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ws", tags=["ws"])


@router.websocket("/tasks")
async def ws_tasks(websocket: WebSocket) -> None:
    await connection_manager.connect(websocket)
    logger.info("ws client connected (total=%s)", connection_manager.connection_count)
    try:
        while True:
            message = await websocket.receive_text()
            if message.strip() == "ping":
                await websocket.send_text("pong")
            elif message.strip() == "pong":
                continue
            else:
                # 未知消息忽略即可;心跳协议保持最小化。
                logger.debug("ws received: %s", message[:120])
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("ws connection error")
    finally:
        await connection_manager.disconnect(websocket)
        logger.info("ws client disconnected (total=%s)", connection_manager.connection_count)
