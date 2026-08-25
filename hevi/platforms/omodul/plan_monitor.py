"""omodul:监控计划构建。组合 oskill.content.monitor_targets + oskill.account.AccountManager。

供 studio/production 工作流调用。
"""

from __future__ import annotations

from typing import Any

from hevi.platforms.schemas import MonitorTarget


def build_monitor_plan(
    targets: list[MonitorTarget],
    account_ids: dict[str, int],  # platform -> account_id
    interval_seconds: int = 300,
    backfill_count: int = 0,
) -> dict[str, Any]:
    """构建监控任务计划。

    将监控目标转换为可执行的计划结构，包含：
    - 目标列表（按平台分组）
    - 账号绑定
    - 调度参数
    - 回填策略
    """

    # 按平台分组
    by_platform: dict[str, list[dict[str, Any]]] = {}
    for t in targets:
        if not t.enabled:
            continue
        plan = t.model_dump()
        plan["account_id"] = account_ids.get(t.platform)
        plan["interval_seconds"] = interval_seconds
        plan["backfill_count"] = backfill_count if t.backfill_count <= 0 else t.backfill_count
        by_platform.setdefault(t.platform, []).append(plan)

    return {
        "type": "monitor",
        "platforms": list(by_platform.keys()),
        "targets_by_platform": by_platform,
        "schedule": {
            "interval_seconds": interval_seconds,
            "max_concurrent": 2,  # 并发限制
        },
        "risk_control": {
            "enabled": True,
            "cooldown_policy": "conservative",
        },
    }