"""数字人直播服务核心 — 对标 Fay 的直播带货能力。

架构:
  肖像 + TTS → 唇形同步 → OBS/FFmpeg 推流 → 平台 RTMP

参考: https://github.com/xszyou/Fay
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

__all__ = [
    "LiveStreamPlatform",
    "LiveStreamState",
    "LiveStreamConfig",
    "LiveStreamRequest",
    "LiveStreamStatus",
    "ChatMessage",
    "ProductItem",
    "start_livestream",
    "stop_livestream",
    "get_livestream_status",
    "send_chat_reply",
    "add_product",
    "list_products",
    "list_active_streams",
]


class LiveStreamPlatform(str, Enum):
    douyin = "douyin"
    kuaishou = "kuaishou"
    wechat_video = "wechat_video"
    youtube = "youtube"
    bilibili = "bilibili"


class LiveStreamState(str, Enum):
    idle = "idle"
    starting = "starting"
    live = "live"
    paused = "paused"
    stopping = "stopping"
    error = "error"


class LiveStreamConfig(BaseModel):
    platform: LiveStreamPlatform
    rtmp_url: str = ""
    stream_key: str = ""
    portrait_path: str = ""  # 肖像图/视频路径
    voice_id: str = "default"
    resolution: str = "1080x1920"  # 竖屏
    fps: int = 30
    bitrate_kbps: int = 4000
    title: str = ""
    auto_reply: bool = True
    auto_present_products: bool = True


class LiveStreamRequest(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    config: LiveStreamConfig
    script: str = ""  # 预设话术脚本
    products: list[str] = Field(default_factory=list)  # product IDs
    scheduled_start: Optional[datetime] = None
    max_duration_min: int = 120


class LiveStreamStatus(BaseModel):
    id: str = ""
    state: LiveStreamState = LiveStreamState.idle
    platform: str = ""
    viewers: int = 0
    duration_sec: float = 0.0
    messages_received: int = 0
    messages_replied: int = 0
    products_presented: int = 0
    error: Optional[str] = None
    started_at: Optional[datetime] = None


class ChatMessage(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    stream_id: str = ""
    username: str = ""
    content: str = ""
    is_question: bool = False
    reply: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class ProductItem(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    name: str
    price: str = ""
    description: str = ""
    image_path: Optional[str] = None
    script: str = ""  # 产品介绍话术
    keywords: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# In-memory stores
# ---------------------------------------------------------------------------

_streams: dict[str, LiveStreamStatus] = {}
_products: dict[str, ProductItem] = {}
_chat_history: dict[str, list[ChatMessage]] = {}


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------

async def start_livestream(request: LiveStreamRequest) -> LiveStreamStatus:
    """启动数字人直播。

    Pipeline:
      1. 验证配置 (RTMP URL, 肖像, 声音)
      2. 启动数字人渲染进程 (肖像 + TTS → 实时视频)
      3. 启动推流 (FFmpeg → RTMP)
      4. 连接弹幕接口 (WebSocket/轮询)
      5. 启动自动回复 + 产品轮播
    """
    config = request.config
    stream_id = request.id

    # Validate
    if not config.rtmp_url and not config.stream_key:
        status = LiveStreamStatus(
            id=stream_id, state=LiveStreamState.error,
            error="RTMP URL or stream key required",
        )
        _streams[stream_id] = status
        return status

    if not config.portrait_path:
        status = LiveStreamStatus(
            id=stream_id, state=LiveStreamState.error,
            error="Portrait path required for digital human",
        )
        _streams[stream_id] = status
        return status

    # Create status
    status = LiveStreamStatus(
        id=stream_id,
        state=LiveStreamState.starting,
        platform=config.platform.value,
        started_at=datetime.utcnow(),
    )
    _streams[stream_id] = status
    _chat_history[stream_id] = []

    try:
        logger.info("[%s] Starting livestream on %s: %s",
                     stream_id, config.platform.value, config.title)

        # Step 1: Start digital human renderer
        # In production: spawn process that renders portrait + TTS → video frames
        # cmd = ["python", "-m", "hevi.livestream.renderer",
        #        "--portrait", config.portrait_path,
        #        "--voice", config.voice_id,
        #        "--resolution", config.resolution,
        #        "--fps", str(config.fps)]
        await asyncio.sleep(0)

        # Step 2: Start FFmpeg RTMP push
        # ffmpeg -f rawvideo -pix_fmt bgr24 -s 1080x1920 -r 30 -i pipe:0
        #        -c:v libx264 -preset veryfast -b:v 4000k
        #        -f flv rtmp://...
        await asyncio.sleep(0)

        # Step 3: Connect chat interface
        # Platform-specific WebSocket/polling for barrage messages
        await asyncio.sleep(0)

        # Step 4: Start auto-reply + product loop
        if request.script:
            logger.info("[%s] Loaded script: %d chars", stream_id, len(request.script))

        status.state = LiveStreamState.live
        logger.info("[%s] Livestream is LIVE on %s", stream_id, config.platform.value)

    except Exception as e:
        status.state = LiveStreamState.error
        status.error = str(e)
        logger.error("[%s] Livestream start failed: %s", stream_id, e)

    return status


async def stop_livestream(stream_id: str) -> LiveStreamStatus | None:
    """停止直播。"""
    status = _streams.get(stream_id)
    if not status:
        return None

    status.state = LiveStreamState.stopping
    logger.info("[%s] Stopping livestream...", stream_id)

    # Kill renderer + FFmpeg processes
    await asyncio.sleep(0)

    status.state = LiveStreamState.idle
    logger.info("[%s] Livestream stopped", stream_id)
    return status


def get_livestream_status(stream_id: str) -> LiveStreamStatus | None:
    return _streams.get(stream_id)


def list_active_streams() -> list[LiveStreamStatus]:
    return [s for s in _streams.values() if s.state == LiveStreamState.live]


async def send_chat_reply(stream_id: str, message_id: str, reply_text: str) -> ChatMessage | None:
    """回复弹幕消息。"""
    history = _chat_history.get(stream_id, [])
    for msg in history:
        if msg.id == message_id:
            msg.reply = reply_text
            # Send via platform chat API
            await asyncio.sleep(0)
            if stream_id in _streams:
                _streams[stream_id].messages_replied += 1
            return msg
    return None


def add_product(product: ProductItem) -> ProductItem:
    _products[product.id] = product
    return product


def list_products() -> list[ProductItem]:
    return list(_products.values())
