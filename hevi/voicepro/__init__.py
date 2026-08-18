"""Voice-Pro 配音内核 3O 包 —— 字幕时钟 / 人声床混音 / Cosy 三模式 / F5 目录 / 翻译退避。

分层(与 script2video 同构,目标上游见各模块头注释):
    schemas.py  obase 契约
    oprim/      无状态原子(不得引用 oskill/omodul)
    oskill/     组合 ≥2 个原语
    omodul/     文本规划(供 production 三件套 workflow 调用)

Hevi 护城河(阈值/路由/成片导出)留在 dub / audio / production,不进本包。
"""

from __future__ import annotations

from hevi.voicepro.schemas import (
    CosyLinePayload,
    DubPlan,
    F5ModelSpec,
    MixPlan,
    SpeakerTurn,
    TimedCue,
    TimelineSlot,
    TranslateLineResult,
)

__all__ = [
    "CosyLinePayload",
    "DubPlan",
    "F5ModelSpec",
    "MixPlan",
    "SpeakerTurn",
    "TimedCue",
    "TimelineSlot",
    "TranslateLineResult",
]
