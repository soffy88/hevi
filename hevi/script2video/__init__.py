"""Script2Video 内核 3O 包 —— 角色三联画 / 首末帧拆解 / 机位树 / 过渡视频 / 参考图选择。

分层(与 pipeline_lite 同构,目标上游见各模块头注释):
    schemas.py  obase 契约
    oprim/      无状态原子(不得引用 oskill/omodul)
    oskill/     组合 ≥2 个原语
    omodul/     文本规划(供 production 三件套 workflow 调用)

Hevi 护城河(阈值/路由/ShotList 字段)留在 director / production,不进本包。
"""

from __future__ import annotations

from hevi.script2video.schemas import (
    CameraNode,
    CameraTree,
    CharacterPortrait,
    KernelPlan,
    KernelShot,
    PortraitRegistry,
    PortraitView,
    ReferenceSelection,
    ShotVisualPlan,
    TransitionResult,
    TransitionSpec,
)

__all__ = [
    "CameraNode",
    "CameraTree",
    "CharacterPortrait",
    "KernelPlan",
    "KernelShot",
    "PortraitRegistry",
    "PortraitView",
    "ReferenceSelection",
    "ShotVisualPlan",
    "TransitionResult",
    "TransitionSpec",
]
