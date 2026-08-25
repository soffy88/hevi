"""Hevi Platform Management 3O Package —— 多平台内容采集/监控/发布内核。

CreatorHub 能力内化:抖音/小红书/快手/视频号 的登录态管理、内容监控、下载、发布、评论自动化。

3O 分层(与 voicepro/script2video 同构):
    schemas.py      obase 契约
    oprim/          无状态原子(不得引用 oskill/omodul)
    oskill/         组合 ≥2 个原语
    omodul/         文本规划/任务编排(供 studio/production 调用)

Hevi 护城河(风控/调度/持久化)留在 studio/platform_ops / monitoring / producers,不进本包。
"""

from __future__ import annotations

from hevi.platforms.schemas import (
    AccountProfile,
    CommentRule,
    ContentRecord,
    MonitorTarget,
    PlatformName,
    PublishTask,
    RiskLevel,
)

__all__ = [
    "AccountProfile",
    "CommentRule",
    "ContentRecord",
    "MonitorTarget",
    "PlatformName",
    "PublishTask",
    "RiskLevel",
]