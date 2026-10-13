"""omodul:平台管理文本规划/任务编排。正式三件套签名在 hevi/studio/platform_ops_workflow.py。"""

from __future__ import annotations

from hevi.layer4_legacy.platforms.omodul_impl.plan_comment import build_comment_plan
from hevi.layer4_legacy.platforms.omodul_impl.plan_monitor import build_monitor_plan

__all__ = [
    "build_comment_plan",
    "build_monitor_plan",
]
