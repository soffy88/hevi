"""弹幕输入源：本地 websocket 监听（127.0.0.1，仅接收浏览器转发，不主动联网）。

对应 DESIGN §6 方案1：主播浏览器内脚本把直播间弹幕转发到本地端口。
本模块只监听本地回环地址，不对外暴露。仅作接入骨架（依赖 websockets）。
"""

from __future__ import annotations

import asyncio

from hevi.live_host.schemas import TurnInput


async def ws_danmaku(host: str = "127.0.0.1", port: int = 8765) -> None:
    """启动本地 websocket 服务，收到文本即作为弹幕（演示骨架，需外部 loop 消费）。

    真实直播循环会把它与 :class:`LiveHost` 串起来；此处提供最小可用服务端点。
    """
    import websockets

    async def handler(ws):
        async for message in ws:
            text = message.strip()
            if text:
                yield TurnInput(text=text, source="danmaku_ws")  # 类型提示占位

    # 占位：实际编排在 live_host CLI 中组合；此处仅暴露启动入口
    async with websockets.serve(lambda ws: ws, host, port):
        await asyncio.Future()  # 常驻
