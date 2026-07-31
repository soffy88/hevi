"""数字人直播服务 — 对标 xszyou/Fay。

能力:
- 数字人唇形同步 (肖像 + TTS → 实时视频流)
- 多平台推流 (抖音/快手/视频号/YouTube)
- 产品知识库 Q&A (RAG + LLM)
- 自动互动 (弹幕识别 → 回复生成)
- 排班调度 (定时开播/下播)

参考: https://github.com/xszyou/Fay
"""
from hevi.livestream.livestream_service import (
    LiveStreamConfig,
    LiveStreamState,
    LiveStreamPlatform,
    LiveStreamRequest,
    LiveStreamStatus,
    ChatMessage,
    ProductItem,
    start_livestream,
    stop_livestream,
    get_livestream_status,
    send_chat_reply,
    add_product,
    list_products,
    list_active_streams,
)
from hevi.livestream.scheduler import (
    LiveStreamSchedule,
    StreamScheduler,
)

__all__ = [
    "LiveStreamConfig",
    "LiveStreamState",
    "LiveStreamPlatform",
    "LiveStreamRequest",
    "LiveStreamStatus",
    "ChatMessage",
    "ProductItem",
    "LiveStreamSchedule",
    "StreamScheduler",
    "start_livestream",
    "stop_livestream",
    "get_livestream_status",
    "send_chat_reply",
    "add_product",
    "list_products",
    "list_active_streams",
]
