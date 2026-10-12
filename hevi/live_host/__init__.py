"""hevi.live_host —— 赛博小雅式全本地实时 AI 直播主持（3O）。

oprim：VAD / STT / LLM / TTS 原子 + 引擎注册表
oskill：听 / 想 / 说 技能组合
omodul：整轮编排（LiveHost）
ingest：弹幕/音频输入源
"""

from __future__ import annotations

from hevi.live_host.omodul.live_loop import LiveHost
from hevi.live_host.oprim.registry import EngineRegistry
from hevi.live_host.schemas import (
    EngineConfig,
    StageTiming,
    TurnInput,
    TurnOutput,
    Utterance,
)

__all__ = [
    "LiveHost",
    "EngineConfig",
    "EngineRegistry",
    "StageTiming",
    "TurnInput",
    "TurnOutput",
    "Utterance",
]
