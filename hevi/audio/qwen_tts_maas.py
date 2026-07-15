"""阿里云百炼(MaaS workspace)qwen3-tts-flash 表情级中文 TTS —— 戏剧化角色配音。

跟 `hevi/video/dashscope_i2v_service.py` 同一把 `ALIBABA_MAAS_API_KEY` + workspace 专属
域名 `ALIBABA_MAAS_HOST`(dashScope 端点 = https://{host}/api/v1)。**必须走这个 workspace
端点**,不能走 dashscope SDK 默认的公共 `dashscope.aliyuncs.com`——后者对应的
DASHSCOPE_API_KEY 账户欠费。qwen3-tts-flash 多音色、按语义自然带情绪,远比 edge-tts 的
"念旁白"腔有戏剧感(scene_v2 那种对白感就是这条路 + 会说话的画面)。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)


class QwenTTSError(Exception):
    """qwen-tts 合成失败(缺 key/host、请求失败、无音频产物)。"""


def qwen_tts(
    *,
    text: str,
    voice: str,
    output_path: Path,
    model: str = "qwen3-tts-flash",
    rate: float | None = None,
    language_type: str | None = None,
    instruction: str | None = None,
    api_key: str | None = None,
    host: str | None = None,
) -> Path:
    """text + voice → 音频落到 output_path(同步阻塞)。voice 为 qwen3-tts 音色名
    (Ethan/Marcus/Eric/Cherry...);dialect 音色(Dylan北京/Jada上海/Sunny四川)非普通话,
    要标准普通话别用。rate<1 放慢语速(如 0.9)。"""
    import dashscope

    key = api_key or os.getenv("ALIBABA_MAAS_API_KEY")
    h = host or os.getenv("ALIBABA_MAAS_HOST")
    if not key:
        raise QwenTTSError("ALIBABA_MAAS_API_KEY not configured")
    if not h:
        raise QwenTTSError("ALIBABA_MAAS_HOST not configured (workspace-dedicated domain)")

    # workspace 专属 dashScope 端点(非公共欠费域名)。全局设置,同一进程内复用。
    dashscope.base_http_api_url = f"https://{h}/api/v1"

    extra: dict = {}
    if rate is not None:
        extra["rate"] = rate
    if language_type is not None:
        extra["language_type"] = language_type  # 强制语种(如 "Chinese" 逼出普通话,避免粤语)
    if instruction is not None:
        extra["instruction"] = instruction  # 语气/情绪指令(同一音色出不同角色语气)
    rsp = dashscope.MultiModalConversation.call(
        model=model, api_key=key, text=text, voice=voice, **extra
    )
    if rsp.status_code != 200:
        raise QwenTTSError(
            f"qwen-tts({voice}) 失败 status={rsp.status_code}: {getattr(rsp, 'message', '')}"
        )
    out = getattr(rsp, "output", None) or {}
    audio = out.get("audio") if hasattr(out, "get") else None
    url = (audio or {}).get("url") if audio else None
    if not url:
        raise QwenTTSError(f"qwen-tts({voice}) 无音频产物: {out}")

    data = httpx.get(url, timeout=httpx.Timeout(120.0)).content
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(data)
    if not output_path.exists() or output_path.stat().st_size < 512:
        raise QwenTTSError(f"qwen-tts({voice}) 产出空/过小: {output_path}")
    return output_path
